import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

const NUMERIC_ID = /^\d+$/;

/**
 * The newest group message ID handed to the backend, kept across restarts.
 *
 * A reply that arrives while the listener is down (reconnect, deploy) never
 * reaches the backend, which then tags someone who already answered. Zalo
 * message IDs grow over time, so this is the point to ask Zalo to resend from.
 */
export class MessageCursor {
  private value: bigint | null = null;
  private writeTail: Promise<void> = Promise.resolve();

  constructor(private readonly path: string | null) {}

  async load(): Promise<void> {
    if (!this.path) return;
    try {
      const text = (await readFile(this.path, "utf8")).trim();
      if (NUMERIC_ID.test(text)) this.value = BigInt(text);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
      console.warn(
        "ZALO_MESSAGE_CURSOR_UNREADABLE error=%s",
        error instanceof Error ? error.message : "unknown",
      );
    }
  }

  get(): string | null {
    return this.value === null ? null : this.value.toString();
  }

  advance(messageId: string): void {
    if (!NUMERIC_ID.test(messageId)) return;
    const candidate = BigInt(messageId);
    if (this.value !== null && candidate <= this.value) return;
    this.value = candidate;
    const path = this.path;
    if (!path) return;
    const text = candidate.toString();
    // Best effort: losing the cursor only means one gap is not backfilled.
    this.writeTail = this.writeTail
      .then(async () => {
        await mkdir(dirname(path), { recursive: true, mode: 0o700 });
        const temporary = `${path}.${randomUUID()}.tmp`;
        await writeFile(temporary, text, { mode: 0o600 });
        await rename(temporary, path);
      })
      .catch((error: unknown) => {
        console.warn(
          "ZALO_MESSAGE_CURSOR_WRITE_FAILED error=%s",
          error instanceof Error ? error.message : "unknown",
        );
      });
  }

  /** Test hook: resolves once pending writes have settled. */
  flushed(): Promise<void> {
    return this.writeTail;
  }
}

/** Oldest message a backfill may forward; older history is not a missed reply. */
export const BACKFILL_MAX_AGE_MS = 24 * 60 * 60 * 1_000;

type BackfillCandidate = {
  isSelf: boolean;
  data: { msgId: string; ts: string | number };
};

/**
 * The messages from an old-messages batch that the backend has not seen: newer
 * than the cursor at request time, not already forwarded live, not the bot's
 * own, and recent. Oldest first so each group's FIFO keeps conversation order.
 */
export function missedMessages<T extends BackfillCandidate>(
  messages: T[],
  since: string,
  alreadyForwarded: ReadonlySet<string>,
  now: number = Date.now(),
): T[] {
  if (!NUMERIC_ID.test(since)) return [];
  const floor = BigInt(since);
  return messages
    .filter((message) => {
      const id = String(message.data.msgId ?? "");
      if (message.isSelf || !NUMERIC_ID.test(id) || BigInt(id) <= floor) return false;
      if (alreadyForwarded.has(id)) return false;
      const timestamp = Number(message.data.ts);
      const sentAt = timestamp < 10_000_000_000 ? timestamp * 1_000 : timestamp;
      return Number.isFinite(sentAt) && now - sentAt <= BACKFILL_MAX_AGE_MS;
    })
    .sort((left, right) => {
      const a = BigInt(left.data.msgId);
      const b = BigInt(right.data.msgId);
      return a < b ? -1 : a > b ? 1 : 0;
    });
}
