import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { DurableEventOutbox } from "../src/event-outbox.js";
import { SendIdempotencyStore } from "../src/send-idempotency.js";
import type { IncomingGroupEvent } from "../src/zalo/types.js";

const event: IncomingGroupEvent = {
  event_type: "reaction",
  group_id: "group-1",
  reactor_id: "target-1",
  reactor_display_name: "Target",
  reacted_at: new Date().toISOString(),
  reaction: "heart",
};

async function eventually(check: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.fail("condition did not become true");
}

test("event outbox survives a gateway restart before backend delivery", async () => {
  const directory = await mkdtemp(join(tmpdir(), "zbridge-outbox-"));
  try {
    const blocked = new DurableEventOutbox(
      directory,
      "test-secret",
      () => new Promise(() => undefined),
    );
    await blocked.initialize();
    await blocked.enqueue(event);
    assert.equal(blocked.status().pending, 1);
    assert.equal(blocked.status().healthy, false);

    const delivered: IncomingGroupEvent[] = [];
    const restarted = new DurableEventOutbox(directory, "test-secret", async (item) => {
      delivered.push(item);
    });
    await restarted.initialize();
    await eventually(() => restarted.status().pending === 0);
    assert.deepEqual(delivered, [event]);
    assert.equal(restarted.status().healthy, true);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("send receipt deduplicates concurrent calls and survives restart", async () => {
  const directory = await mkdtemp(join(tmpdir(), "zbridge-receipts-"));
  const path = join(directory, "receipts.json");
  try {
    const store = new SendIdempotencyStore(path);
    await store.initialize();
    let calls = 0;
    const operation = async () => {
      calls += 1;
      return { message_id: "zalo-message-1" };
    };
    const [first, second] = await Promise.all([
      store.run("debt:run:image", operation),
      store.run("debt:run:image", operation),
    ]);
    assert.deepEqual(first, second);
    assert.equal(calls, 1);

    const restarted = new SendIdempotencyStore(path);
    await restarted.initialize();
    const replay = await restarted.run("debt:run:image", operation);
    assert.equal(replay.message_id, "zalo-message-1");
    assert.equal(calls, 1);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
