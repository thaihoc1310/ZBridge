import express, { type NextFunction, type Request, type Response } from "express";
import helmet from "helmet";
import { z } from "zod";
import { config } from "./config.js";
import { GatewayError } from "./errors.js";
import { MockZaloClient } from "./zalo/mock-client.js";
import { EncryptedSessionStore } from "./zalo/session.js";
import type { ZaloClient } from "./zalo/types.js";
import type { IncomingGroupMessageEvent } from "./zalo/types.js";
import { ZcaJsClient } from "./zalo/zca-client.js";

const app = express();
app.use(helmet());
app.use(express.json({ limit: "32kb" }));

type AsyncRoute = (req: Request, res: Response) => Promise<unknown>;

function asyncRoute(handler: AsyncRoute) {
  return (req: Request, res: Response, next: NextFunction) => {
    void handler(req, res).catch(next);
  };
}

const client: ZaloClient = config.mock
  ? new MockZaloClient()
  : new ZcaJsClient(
      new EncryptedSessionStore(config.sessionPath, config.sessionSecret),
      forwardGroupMessageEvent,
      config.sendIntervalMs,
    );

async function forwardGroupMessageEvent(event: IncomingGroupMessageEvent): Promise<void> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(config.backendEventUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Zalo-Event-Secret": config.zaloEventSecret,
        },
        body: JSON.stringify(event),
        signal: AbortSignal.timeout(10_000),
      });
      if (response.ok) return;
      throw new Error(`Backend rejected Zalo event with status ${response.status}`);
    } catch (error) {
      lastError = error;
      if (attempt < 3) {
        await new Promise((resolve) => setTimeout(resolve, attempt * 1_000));
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Could not forward Zalo event");
}

app.get("/health", asyncRoute(async (_req, res) => {
  const state = await client.getStatus();
  res.json({ gateway: "UP", zalo: state.status });
}));

app.use((req, res, next) => {
  if (req.header("X-Gateway-Secret") !== config.gatewaySecret) {
    res.status(401).json({ error: { code: "UNAUTHORIZED", message: "Invalid gateway secret." } });
    return;
  }
  next();
});

app.get("/bot/status", asyncRoute(async (_req, res) => res.json(await client.getStatus())));
app.post("/bot/connect", asyncRoute(async (_req, res) => res.status(202).json(await client.connect())));
app.get("/bot/qr", asyncRoute(async (_req, res) => res.json(await client.getQr())));
app.post("/bot/reconnect", asyncRoute(async (_req, res) => res.json(await client.reconnect())));
app.post("/bot/disconnect", asyncRoute(async (_req, res) => res.json(await client.disconnect())));
app.get("/groups", asyncRoute(async (_req, res) => res.json({ groups: await client.getGroups() })));
app.get("/groups/:groupId/members", asyncRoute(async (req, res) => {
  const groupId = z.string().min(1).max(128).parse(req.params.groupId);
  res.json({ members: await client.getGroupMembers(groupId) });
}));

const sendTextSchema = z.object({
  group_id: z.string().min(1).max(128),
  content: z.string().trim().min(1).max(5000),
});

app.post("/messages/text", asyncRoute(async (req, res) => {
  const body = sendTextSchema.parse(req.body);
  res.json(await client.sendText(body.group_id, body.content));
}));

const sendMentionSchema = z.object({
  group_id: z.string().min(1).max(128),
  targets: z
    .array(
      z.object({
        user_id: z.string().min(1).max(128),
        display_name: z.string().trim().min(1).max(255),
      }),
    )
    .min(1)
    .max(100),
});

app.post("/messages/mention", asyncRoute(async (req, res) => {
  const body = sendMentionSchema.parse(req.body);
  res.json(await client.sendMention(body.group_id, body.targets));
}));

const sendImageQuerySchema = z.object({
  group_id: z.string().min(1).max(128),
  width: z.coerce.number().int().min(1).max(20_000),
  height: z.coerce.number().int().min(1).max(20_000),
});

app.post(
  "/messages/image",
  express.raw({ type: "image/png", limit: "20mb" }),
  asyncRoute(async (req, res) => {
    const query = sendImageQuerySchema.parse(req.query);
    if (!Buffer.isBuffer(req.body) || req.body.length === 0) {
      throw new GatewayError("VALIDATION_ERROR", "Ảnh PNG không được để trống.", 422);
    }
    res.json(
      await client.sendImage(query.group_id, {
        data: req.body,
        width: query.width,
        height: query.height,
      }),
    );
  }),
);

const sendLinkSchema = z.object({
  group_id: z.string().min(1).max(128),
  link: z.string().url().max(2000),
});

app.post("/messages/link", asyncRoute(async (req, res) => {
  const body = sendLinkSchema.parse(req.body);
  res.json(await client.sendLink(body.group_id, body.link));
}));

const richTextPartSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("text"), text: z.string().min(1).max(5000) }),
  z.object({
    type: z.literal("mention"),
    user_id: z.string().min(1).max(128),
    display_name: z.string().min(1).max(255),
  }),
]);
const sendRichTextSchema = z.object({
  group_id: z.string().min(1).max(128),
  parts: z.array(richTextPartSchema).min(1).max(200),
});

app.post("/messages/rich-text", asyncRoute(async (req, res) => {
  const body = sendRichTextSchema.parse(req.body);
  res.json(await client.sendRichText(body.group_id, body.parts));
}));

app.use((error: unknown, _req: Request, res: Response, _next: NextFunction) => {
  if (error instanceof z.ZodError) {
    res.status(422).json({ error: { code: "VALIDATION_ERROR", message: error.issues[0]?.message ?? "Invalid request." } });
    return;
  }
  if (error instanceof GatewayError) {
    res.status(error.statusCode).json({ error: { code: error.code, message: error.message } });
    return;
  }
  const message = error instanceof Error ? error.message : "Unknown gateway error.";
  console.error("ZALO_GATEWAY_ERROR", message);
  res.status(500).json({ error: { code: "UNKNOWN_ERROR", message } });
});

await client.initialize();
app.listen(config.port, "0.0.0.0", () => {
  console.info(`Zalo Gateway listening on port ${config.port} mock=${config.mock}`);
});
