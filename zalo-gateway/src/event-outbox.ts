import { createCipheriv, createDecipheriv, createHash, randomBytes, randomUUID } from "node:crypto";
import { chmod, mkdir, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { IncomingGroupEvent } from "./zalo/types.js";

type StoredEvent = {
  id: string;
  sequence: number;
  created_at: string;
  attempts: number;
  event: IncomingGroupEvent;
};

type EncryptedRecord = {
  version: 1;
  iv: string;
  tag: string;
  ciphertext: string;
};

const RETRY_DELAYS_MS = [1_000, 2_000, 5_000, 10_000, 30_000, 60_000, 300_000];

/**
 * A small encrypted disk outbox for inbound Zalo events.
 *
 * The listener acknowledges nothing itself, so an event must reach durable
 * storage before this method resolves. Each group is drained in FIFO order and
 * failures retry forever; a backend outage can delay an acknowledgement, but
 * can no longer erase it and leave a customer in an endless mention loop.
 */
export class DurableEventOutbox {
  private readonly queues = new Map<string, StoredEvent[]>();
  private readonly runningGroups = new Set<string>();
  private readonly retryTimers = new Map<string, NodeJS.Timeout>();
  private initialized = false;
  private storageFailed = false;
  private nextSequence = Date.now() * 1_000;
  private enqueueTail: Promise<void> = Promise.resolve();

  constructor(
    private readonly directory: string,
    secret: string,
    private readonly deliver: (event: IncomingGroupEvent) => Promise<void>,
  ) {
    this.key = createHash("sha256").update(secret, "utf8").digest();
  }

  private readonly key: Buffer;

  async initialize(): Promise<void> {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    const records: StoredEvent[] = [];
    for (const name of await readdir(this.directory)) {
      if (!name.endsWith(".event")) continue;
      try {
        records.push(this.decrypt(await readFile(join(this.directory, name), "utf8")));
      } catch (error) {
        this.storageFailed = true;
        console.error(
          "ZALO_EVENT_OUTBOX_CORRUPT file=%s error=%s",
          name,
          error instanceof Error ? error.message : "unknown",
        );
      }
    }
    records.sort((left, right) => left.sequence - right.sequence);
    this.nextSequence = Math.max(
      this.nextSequence,
      ...records.map((record) => record.sequence + 1),
    );
    for (const record of records) this.queue(record);
    this.initialized = true;
    for (const groupId of this.queues.keys()) this.pump(groupId);
  }

  async enqueue(event: IncomingGroupEvent): Promise<void> {
    const write = this.enqueueTail.then(() => this.enqueueOne(event));
    // Listener callbacks may overlap. Serializing the durable write and queue
    // insertion preserves the sequence in which enqueue() was called.
    this.enqueueTail = write.catch(() => undefined);
    await write;
  }

  private async enqueueOne(event: IncomingGroupEvent): Promise<void> {
    const record: StoredEvent = {
      id: `${Date.now()}-${randomUUID()}`,
      sequence: this.nextSequence++,
      created_at: new Date().toISOString(),
      attempts: 0,
      event,
    };
    try {
      await this.persist(record);
    } catch (error) {
      this.storageFailed = true;
      throw error;
    }
    this.queue(record);
    this.pump(event.group_id);
  }

  status(): { healthy: boolean; pending: number } {
    const pending = [...this.queues.values()].reduce((total, queue) => total + queue.length, 0);
    return {
      healthy: this.initialized && !this.storageFailed && pending === 0,
      pending,
    };
  }

  private queue(record: StoredEvent): void {
    const groupId = record.event.group_id;
    const queue = this.queues.get(groupId) ?? [];
    queue.push(record);
    this.queues.set(groupId, queue);
  }

  private pump(groupId: string): void {
    if (!this.initialized || this.runningGroups.has(groupId) || this.retryTimers.has(groupId)) {
      return;
    }
    this.runningGroups.add(groupId);
    void this.drain(groupId).finally(() => this.runningGroups.delete(groupId));
  }

  private async drain(groupId: string): Promise<void> {
    const queue = this.queues.get(groupId);
    const record = queue?.[0];
    if (!queue || !record) return;
    try {
      await this.deliver(record.event);
      await rm(this.path(record), { force: true });
      queue.shift();
      if (queue.length === 0) this.queues.delete(groupId);
      setImmediate(() => this.pump(groupId));
    } catch (error) {
      record.attempts += 1;
      try {
        await this.persist(record);
      } catch (persistError) {
        this.storageFailed = true;
        console.error(
          "ZALO_EVENT_OUTBOX_WRITE_FAILED group_id=%s error=%s",
          groupId,
          persistError instanceof Error ? persistError.message : "unknown",
        );
      }
      const delay = RETRY_DELAYS_MS[Math.min(record.attempts - 1, RETRY_DELAYS_MS.length - 1)]!;
      console.error(
        "ZALO_EVENT_FORWARD_RETRY group_id=%s attempt=%d delay_ms=%d error=%s",
        groupId,
        record.attempts,
        delay,
        error instanceof Error ? error.message : "unknown",
      );
      const timer = setTimeout(() => {
        this.retryTimers.delete(groupId);
        this.pump(groupId);
      }, delay);
      this.retryTimers.set(groupId, timer);
    }
  }

  private path(record: StoredEvent): string {
    return join(this.directory, `${record.id}.event`);
  }

  private async persist(record: StoredEvent): Promise<void> {
    const target = this.path(record);
    const temporary = `${target}.${randomUUID()}.tmp`;
    await writeFile(temporary, this.encrypt(record), { mode: 0o600 });
    await rename(temporary, target);
    await chmod(target, 0o600);
  }

  private encrypt(record: StoredEvent): string {
    const iv = randomBytes(12);
    const cipher = createCipheriv("aes-256-gcm", this.key, iv);
    const ciphertext = Buffer.concat([
      cipher.update(JSON.stringify(record), "utf8"),
      cipher.final(),
    ]);
    const payload: EncryptedRecord = {
      version: 1,
      iv: iv.toString("base64"),
      tag: cipher.getAuthTag().toString("base64"),
      ciphertext: ciphertext.toString("base64"),
    };
    return JSON.stringify(payload);
  }

  private decrypt(value: string): StoredEvent {
    const payload = JSON.parse(value) as EncryptedRecord;
    if (payload.version !== 1) throw new Error("Unsupported event outbox version");
    const decipher = createDecipheriv("aes-256-gcm", this.key, Buffer.from(payload.iv, "base64"));
    decipher.setAuthTag(Buffer.from(payload.tag, "base64"));
    const cleartext = Buffer.concat([
      decipher.update(Buffer.from(payload.ciphertext, "base64")),
      decipher.final(),
    ]).toString("utf8");
    return JSON.parse(cleartext) as StoredEvent;
  }
}
