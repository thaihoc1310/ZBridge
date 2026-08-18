import { createCipheriv, createDecipheriv, randomBytes, scryptSync } from "node:crypto";
import { chmod, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import type { Credentials } from "zca-js";

type EncryptedPayload = {
  version: 1;
  salt: string;
  iv: string;
  tag: string;
  ciphertext: string;
};

export class EncryptedSessionStore {
  constructor(
    private readonly path: string,
    private readonly secret: string,
  ) {}

  async exists(): Promise<boolean> {
    try {
      await readFile(this.path);
      return true;
    } catch {
      return false;
    }
  }

  async save(credentials: Credentials): Promise<void> {
    const salt = randomBytes(16);
    const iv = randomBytes(12);
    const key = scryptSync(this.secret, salt, 32);
    const cipher = createCipheriv("aes-256-gcm", key, iv);
    const ciphertext = Buffer.concat([
      cipher.update(JSON.stringify(credentials), "utf8"),
      cipher.final(),
    ]);
    const payload: EncryptedPayload = {
      version: 1,
      salt: salt.toString("base64"),
      iv: iv.toString("base64"),
      tag: cipher.getAuthTag().toString("base64"),
      ciphertext: ciphertext.toString("base64"),
    };
    await mkdir(dirname(this.path), { recursive: true, mode: 0o700 });
    await writeFile(this.path, JSON.stringify(payload), { mode: 0o600 });
    await chmod(this.path, 0o600);
  }

  async load(): Promise<Credentials | null> {
    try {
      const payload = JSON.parse(await readFile(this.path, "utf8")) as EncryptedPayload;
      if (payload.version !== 1) return null;
      const salt = Buffer.from(payload.salt, "base64");
      const key = scryptSync(this.secret, salt, 32);
      const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(payload.iv, "base64"));
      decipher.setAuthTag(Buffer.from(payload.tag, "base64"));
      const cleartext = Buffer.concat([
        decipher.update(Buffer.from(payload.ciphertext, "base64")),
        decipher.final(),
      ]).toString("utf8");
      const credentials = JSON.parse(cleartext) as Credentials;
      if (!credentials.cookie || !credentials.imei || !credentials.userAgent) return null;
      return credentials;
    } catch {
      return null;
    }
  }

  async clear(): Promise<void> {
    await rm(this.path, { force: true });
  }
}

