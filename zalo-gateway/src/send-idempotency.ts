import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { randomUUID } from "node:crypto";
import type { SendResult } from "./zalo/types.js";

type Receipt = { result: SendResult; stored_at: string };
type ReceiptFile = { version: 1; receipts: Record<string, Receipt> };

const RETENTION_MS = 45 * 24 * 60 * 60 * 1_000;
const MAX_RECEIPTS = 20_000;

/** Deduplicates backend retries after Zalo has already accepted a send. */
export class SendIdempotencyStore {
  private readonly receipts = new Map<string, Receipt>();
  private readonly inFlight = new Map<string, Promise<SendResult>>();
  private initialized = false;
  private persistTail: Promise<void> = Promise.resolve();

  constructor(private readonly path: string) {}

  async initialize(): Promise<void> {
    try {
      const parsed = JSON.parse(await readFile(this.path, "utf8")) as ReceiptFile;
      if (parsed.version !== 1) throw new Error("Unsupported receipt store version");
      const cutoff = Date.now() - RETENTION_MS;
      for (const [key, receipt] of Object.entries(parsed.receipts)) {
        if (Date.parse(receipt.stored_at) >= cutoff) this.receipts.set(key, receipt);
      }
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code !== "ENOENT") throw error;
    }
    this.initialized = true;
  }

  async run(key: string | undefined, operation: () => Promise<SendResult>): Promise<SendResult> {
    if (!key) return operation();
    if (!this.initialized) throw new Error("Send idempotency store is not initialized");
    const cached = this.receipts.get(key);
    if (cached) {
      // Also heals a previous disk-write failure: the Zalo send must never be
      // repeated merely because persisting its receipt had a transient error.
      await this.persist();
      return cached.result;
    }
    const running = this.inFlight.get(key);
    if (running) return running;

    const promise = operation().then(async (result) => {
      this.receipts.set(key, { result, stored_at: new Date().toISOString() });
      this.prune();
      await this.persist();
      return result;
    }).finally(() => this.inFlight.delete(key));
    this.inFlight.set(key, promise);
    return promise;
  }

  private prune(): void {
    const cutoff = Date.now() - RETENTION_MS;
    for (const [key, receipt] of this.receipts) {
      if (Date.parse(receipt.stored_at) < cutoff) this.receipts.delete(key);
    }
    if (this.receipts.size <= MAX_RECEIPTS) return;
    const oldest = [...this.receipts.entries()]
      .sort((left, right) => left[1].stored_at.localeCompare(right[1].stored_at))
      .slice(0, this.receipts.size - MAX_RECEIPTS);
    for (const [key] of oldest) this.receipts.delete(key);
  }

  private async persist(): Promise<void> {
    const write = this.persistTail.then(() => this.persistNow());
    this.persistTail = write.catch(() => undefined);
    await write;
  }

  private async persistNow(): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true, mode: 0o700 });
    const temporary = `${this.path}.${randomUUID()}.tmp`;
    const payload: ReceiptFile = {
      version: 1,
      receipts: Object.fromEntries(this.receipts),
    };
    await writeFile(temporary, JSON.stringify(payload), { mode: 0o600 });
    await rename(temporary, this.path);
  }
}
