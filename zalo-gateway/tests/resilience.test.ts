import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { chmod, mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { ThreadType, ZaloApiError } from "zca-js";
import { DurableEventOutbox, PermanentDeliveryError } from "../src/event-outbox.js";
import { MessageCursor, missedMessages } from "../src/message-cursor.js";
import type { IncomingGroupEvent } from "../src/zalo/types.js";
import {
  incomingMentions,
  isSessionRejected,
  ZcaJsClient,
} from "../src/zalo/zca-client.js";
import type { EncryptedSessionStore } from "../src/zalo/session.js";

function reactionEvent(groupId: string, reactor: string): IncomingGroupEvent {
  return {
    event_type: "reaction",
    group_id: groupId,
    reactor_id: reactor,
    reactor_display_name: reactor,
    reacted_at: new Date().toISOString(),
    reaction: "heart",
  };
}

async function eventually(check: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (check()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  assert.fail("condition did not become true");
}

test("a permanently rejected event is set aside and the group keeps flowing", async () => {
  const directory = await mkdtemp(join(tmpdir(), "zbridge-deadletter-"));
  try {
    const delivered: string[] = [];
    const deadLettered: string[] = [];
    const outbox = new DurableEventOutbox(
      directory,
      "test-secret",
      async (event) => {
        if (event.event_type === "reaction" && event.reactor_id === "poison") {
          throw new PermanentDeliveryError("Backend rejected Zalo event with status 422");
        }
        if (event.event_type === "reaction") delivered.push(event.reactor_id);
      },
      (event, reason) => {
        if (event.event_type === "reaction") deadLettered.push(`${event.reactor_id}:${reason}`);
      },
    );
    await outbox.initialize();
    await outbox.enqueue(reactionEvent("group-1", "poison"));
    await outbox.enqueue(reactionEvent("group-1", "after"));
    await eventually(() => outbox.status().pending === 0);

    assert.deepEqual(delivered, ["after"]);
    assert.deepEqual(deadLettered, ["poison:Backend rejected Zalo event with status 422"]);
    assert.equal(outbox.status().healthy, true);
    // Kept for inspection, and not replayed by the next start.
    const kept = await readdir(join(directory, "dead-letter"));
    assert.equal(kept.length, 1);
    const topLevel = (await readdir(directory)).filter((name) => name.endsWith(".event"));
    assert.deepEqual(topLevel, []);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("a transient backend failure is still retried, not dead-lettered", async () => {
  const directory = await mkdtemp(join(tmpdir(), "zbridge-transient-"));
  try {
    let calls = 0;
    const outbox = new DurableEventOutbox(directory, "test-secret", async () => {
      calls += 1;
      if (calls === 1) throw new Error("Backend rejected Zalo event with status 503");
    });
    await outbox.initialize();
    await outbox.enqueue(reactionEvent("group-1", "target"));
    await eventually(() => outbox.status().pending === 0);
    assert.equal(calls, 2);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("a failed disk write still delivers the event and health recovers", {
  skip: process.getuid?.() === 0 ? "root ignores directory permissions" : false,
}, async () => {
  const directory = await mkdtemp(join(tmpdir(), "zbridge-diskfull-"));
  try {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const delivered: string[] = [];
    const outbox = new DurableEventOutbox(directory, "test-secret", async (event) => {
      await gate;
      if (event.event_type === "reaction") delivered.push(event.reactor_id);
    });
    await outbox.initialize();
    await chmod(directory, 0o500);
    await outbox.enqueue(reactionEvent("group-1", "while-full"));
    // Delivered from memory, but a restart now would lose it: say so.
    assert.equal(outbox.status().healthy, false);
    await chmod(directory, 0o700);
    await outbox.enqueue(reactionEvent("group-2", "after-recovery"));
    assert.equal(outbox.status().healthy, true);
    release();
    await eventually(() => outbox.status().pending === 0);
    assert.deepEqual(delivered.sort(), ["after-recovery", "while-full"]);
  } finally {
    await chmod(directory, 0o700).catch(() => undefined);
    await rm(directory, { recursive: true, force: true });
  }
});

test("only a real Zalo rejection counts as an invalid session", () => {
  assert.equal(isSessionRejected(new ZaloApiError("Đăng nhập thất bại")), true);
  assert.equal(isSessionRejected(new ZaloApiError("Khởi tạo ngữ cảnh thất bại.")), true);
  assert.equal(
    isSessionRejected(new ZaloApiError("Failed to fetch login info: Bad Gateway")),
    false,
  );
  assert.equal(isSessionRejected(new TypeError("fetch failed")), false);
  assert.equal(isSessionRejected(new Error("getaddrinfo EAI_AGAIN wpa.chat.zalo.me")), false);
});

test("mentions the backend would reject are dropped or clamped", () => {
  const content = `@${"A".repeat(300)} và @B`;
  const mentions = incomingMentions(
    [
      { uid: "u1_0", pos: 0, len: 301 },
      { uid: "u2", pos: 5, len: 0 },
      { uid: "", pos: 0, len: 2 },
      { uid: "u3", pos: content.length - 2, len: 2 },
    ],
    content,
  );
  assert.deepEqual(
    mentions.map((mention) => [mention.user_id, mention.length, mention.text.length]),
    [
      ["u1", 301, 255],
      ["u3", 2, 2],
    ],
  );
});

test("the message cursor persists, never moves backwards and ignores non-numeric IDs", async () => {
  const directory = await mkdtemp(join(tmpdir(), "zbridge-cursor-"));
  const path = join(directory, "last-message-id");
  try {
    const cursor = new MessageCursor(path);
    await cursor.load();
    assert.equal(cursor.get(), null);
    cursor.advance("8309817628830");
    cursor.advance("8309816176490");
    cursor.advance("not-a-number");
    await cursor.flushed();
    assert.equal(await readFile(path, "utf8"), "8309817628830");

    const restarted = new MessageCursor(path);
    await restarted.load();
    assert.equal(restarted.get(), "8309817628830");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

function oldMessage(msgId: string, ageMs: number, isSelf = false) {
  return { isSelf, data: { msgId, ts: String(Date.now() - ageMs) } };
}

test("a backfill forwards only unseen, recent, non-self messages, oldest first", () => {
  const selected = missedMessages(
    [
      oldMessage("105", 1_000),
      oldMessage("100", 1_000),
      oldMessage("99", 1_000),
      oldMessage("103", 1_000, true),
      oldMessage("102", 1_000),
      oldMessage("104", 2 * 24 * 60 * 60 * 1_000),
      oldMessage("106", 1_000),
    ],
    "100",
    new Set(["106"]),
  );
  assert.deepEqual(
    selected.map((message) => message.data.msgId),
    ["102", "105"],
  );
});

class FakeListener extends EventEmitter {
  requested: Array<[ThreadType, string | null | undefined]> = [];
  start(): void {}
  stop(): void {}
  requestOldMessages(type: ThreadType, lastMsgId?: string | null): void {
    this.requested.push([type, lastMsgId]);
  }
}

function groupMessage(msgId: string, uidFrom: string) {
  return {
    type: ThreadType.Group,
    isSelf: false,
    threadId: "group-1",
    data: {
      msgId,
      cliMsgId: `c${msgId}`,
      uidFrom,
      dName: uidFrom,
      ts: String(Date.now()),
      msgType: "webchat",
      content: "đã xong",
      mentions: [],
    },
  };
}

test("a reconnect asks Zalo for what it missed and forwards the gap once", async () => {
  const directory = await mkdtemp(join(tmpdir(), "zbridge-backfill-"));
  try {
    const cursor = new MessageCursor(join(directory, "last-message-id"));
    cursor.advance("200");
    const forwarded: string[] = [];
    const client = new ZcaJsClient(
      {} as EncryptedSessionStore,
      async (event) => {
        if (event.event_type === "message") forwarded.push(event.message_id);
      },
      0,
      undefined,
      cursor,
    );
    const listener = new FakeListener();
    // The private wiring is what is under test; a real API needs a Zalo login.
    const internals = client as unknown as {
      setApi(api: unknown): void;
      startListener(): void;
    };
    internals.setApi({ listener });
    internals.startListener();

    listener.emit("connected");
    assert.deepEqual(listener.requested, [[ThreadType.Group, "200"]]);
    // A live message lands before Zalo answers the backfill request.
    listener.emit("message", groupMessage("203", "target-live"));
    listener.emit(
      "old_messages",
      [groupMessage("203", "target-live"), groupMessage("201", "target-gap"), groupMessage("150", "x")],
      ThreadType.Group,
    );
    await eventually(() => forwarded.length === 2);
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.deepEqual(forwarded, ["203", "201"]);
    assert.equal(cursor.get(), "203");
    await cursor.flushed();
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

function fakeSessions() {
  const state = { cleared: 0 };
  const sessions = {
    load: async () => ({ cookie: [], imei: "imei", userAgent: "ua" }),
    clear: async () => {
      state.cleared += 1;
    },
    save: async () => undefined,
    exists: async () => true,
  } as unknown as EncryptedSessionStore;
  return { sessions, state };
}

type RestoreInternals = {
  restoreTimer: NodeJS.Timeout | null;
  restoreSession(fromOperator: boolean): Promise<void>;
  clearRestoreTimer(): void;
};

test("a network error at boot keeps the session and retries instead of demanding a QR", async (t) => {
  const { Zalo } = await import("zca-js");
  const failures = [new TypeError("fetch failed"), new ZaloApiError("Đăng nhập thất bại")];
  t.mock.method(Zalo.prototype, "login", async () => {
    throw failures.shift();
  });
  const alerts: string[] = [];
  t.mock.method(globalThis, "fetch", async (_url: string, init: { body: string }) => {
    alerts.push(JSON.parse(init.body).code);
    return new Response(null, { status: 202 });
  });
  const { sessions, state } = fakeSessions();
  const client = new ZcaJsClient(sessions, async () => undefined, 0);
  const internals = client as unknown as RestoreInternals;

  await client.initialize();
  assert.equal((await client.getStatus()).status, "DISCONNECTED");
  assert.equal(state.cleared, 0);
  assert.notEqual(internals.restoreTimer, null);
  assert.deepEqual(alerts, []);

  // What the scheduled retry runs; this time Zalo genuinely rejects the cookie.
  await internals.restoreSession(false);
  assert.equal((await client.getStatus()).status, "AUTH_REQUIRED");
  assert.equal(internals.restoreTimer, null);
  // At boot a rejection only reports; the operator decides when to rescan.
  assert.equal(state.cleared, 0);
  await eventually(() => alerts.length === 1);
  assert.deepEqual(alerts, ["BOT_SESSION_INVALID"]);
});

test("an operator reconnect during a network blip does not wipe the session", async (t) => {
  const { Zalo } = await import("zca-js");
  t.mock.method(Zalo.prototype, "login", async () => {
    throw new Error("getaddrinfo EAI_AGAIN wpa.chat.zalo.me");
  });
  const { sessions, state } = fakeSessions();
  const client = new ZcaJsClient(sessions, async () => undefined, 0);
  const status = await client.reconnect();
  assert.equal(status.status, "DISCONNECTED");
  assert.equal(state.cleared, 0);
  (client as unknown as RestoreInternals).clearRestoreTimer();
});

test("a photo caption's mentions still point at the right text", async () => {
  const events: IncomingGroupEvent[] = [];
  const client = new ZcaJsClient({} as EncryptedSessionStore, async (event) => {
    events.push(event);
  }, 0);
  const listener = new FakeListener();
  const internals = client as unknown as { setApi(api: unknown): void; startListener(): void };
  internals.setApi({ listener });
  internals.startListener();
  listener.emit("message", {
    type: ThreadType.Group,
    isSelf: false,
    threadId: "group-1",
    data: {
      msgId: "300",
      cliMsgId: "c300",
      uidFrom: "owner",
      dName: "Owner",
      ts: String(Date.now()),
      msgType: "chat.photo",
      content: { title: "@Anh Tâm đã thanh toán", href: "https://photo" },
      mentions: [{ uid: "target-1", pos: 0, len: 8 }],
    },
  });
  await eventually(() => events.length === 1);
  const event = events[0]!;
  assert.equal(event.event_type, "message");
  if (event.event_type !== "message") return;
  assert.equal(event.content, "[image] @Anh Tâm đã thanh toán");
  assert.deepEqual(event.mentions, [
    { user_id: "target-1", position: 8, length: 8, text: "@Anh Tâm" },
  ]);
});
