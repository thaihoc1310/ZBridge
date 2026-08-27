import { timingSafeEqual } from "node:crypto";
import express, { type NextFunction, type Request, type Response } from "express";
import helmet from "helmet";
import { z } from "zod";
import { reportGatewayError } from "./alerting.js";
import { config } from "./config.js";
import { GatewayError } from "./errors.js";
import { DurableEventOutbox } from "./event-outbox.js";
import { SendIdempotencyStore } from "./send-idempotency.js";
import { MockZaloClient } from "./zalo/mock-client.js";
import { EncryptedSessionStore } from "./zalo/session.js";
import type { ZaloClient } from "./zalo/types.js";
import type { IncomingGroupEvent } from "./zalo/types.js";
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

function secretMatches(provided: string | undefined, expected: string): boolean {
  if (!provided) return false;
  const left = Buffer.from(provided, "utf8");
  const right = Buffer.from(expected, "utf8");
  if (left.length !== right.length) return false;
  return timingSafeEqual(left, right);
}

async function postGroupEvent(event: IncomingGroupEvent): Promise<void> {
  const response = await fetch(config.backendEventUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Zalo-Event-Secret": config.zaloEventSecret,
    },
    body: JSON.stringify(event),
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) {
    throw new Error(`Backend rejected Zalo event with status ${response.status}`);
  }
}

const eventOutbox = new DurableEventOutbox(
  config.eventOutboxPath,
  config.sessionSecret,
  postGroupEvent,
);
const sendReceipts = new SendIdempotencyStore(config.sendReceiptPath);
const client: ZaloClient = config.mock
  ? new MockZaloClient()
  : new ZcaJsClient(
      new EncryptedSessionStore(config.sessionPath, config.sessionSecret),
      (event) => eventOutbox.enqueue(event),
      config.sendIntervalMs,
      () => eventOutbox.status(),
    );

/** Set once the outbox and the receipt store have been read off disk. */
let storesReady = false;

app.get("/health", asyncRoute(async (_req, res) => {
  const state = await client.getStatus();
  res.json({
    gateway: "UP",
    zalo: state.status,
    listener: state.listener_status,
    events_healthy: state.events_healthy,
    events_caught_up: state.events_caught_up,
    event_backlog: state.event_backlog,
    event_backlog_age_ms: state.event_backlog_age_ms,
    stores_ready: storesReady,
  });
}));

app.use((req, res, next) => {
  if (!secretMatches(req.header("X-Gateway-Secret"), config.gatewaySecret)) {
    res.status(401).json({ error: { code: "UNAUTHORIZED", message: "Invalid gateway secret." } });
    return;
  }
  next();
});

// Sending before the receipt store is loaded would bypass dedup entirely, so
// answer with a retryable 503 instead of the bare Error the store used to throw
// (which surfaced as an opaque 500 the backend counted as a real send failure).
app.use((req, _res, next) => {
  if (req.path.startsWith("/messages/") && !storesReady) {
    next(
      new GatewayError(
        "GATEWAY_STARTING",
        "Gateway đang khởi động, chưa nhận yêu cầu gửi tin.",
        503,
      ),
    );
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

const membersBatchSchema = z.object({
  group_ids: z.array(z.string().min(1).max(128)).min(1).max(500),
});

// One round trip for every group, so building a staff roster does not fan out
// into a request per customer.
app.post("/groups/members", asyncRoute(async (req, res) => {
  const body = membersBatchSchema.parse(req.body);
  res.json({ members: await client.getGroupMembersBatch(body.group_ids) });
}));

const sendTextSchema = z.object({
  group_id: z.string().min(1).max(128),
  content: z.string().trim().min(1).max(5000),
  idempotency_key: z.string().min(1).max(255).optional(),
});

app.post("/messages/text", asyncRoute(async (req, res) => {
  const body = sendTextSchema.parse(req.body);
  res.json(await sendReceipts.run(
    body.idempotency_key,
    () => client.sendText(body.group_id, body.content),
  ));
}));

const sendMentionSchema = z.object({
  group_id: z.string().min(1).max(128),
  idempotency_key: z.string().min(1).max(255).optional(),
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
  res.json(await sendReceipts.run(
    body.idempotency_key,
    () => client.sendMention(body.group_id, body.targets),
  ));
}));

const sendImageQuerySchema = z.object({
  group_id: z.string().min(1).max(128),
  width: z.coerce.number().int().min(1).max(20_000),
  height: z.coerce.number().int().min(1).max(20_000),
  idempotency_key: z.string().min(1).max(255).optional(),
});

app.post(
  "/messages/image",
  express.raw({ type: "image/png", limit: "20mb" }),
  asyncRoute(async (req, res) => {
    const query = sendImageQuerySchema.parse(req.query);
    if (!Buffer.isBuffer(req.body) || req.body.length === 0) {
      throw new GatewayError("VALIDATION_ERROR", "Ảnh PNG không được để trống.", 422);
    }
    res.json(await sendReceipts.run(
      query.idempotency_key,
      () => client.sendImage(query.group_id, {
        data: req.body,
        width: query.width,
        height: query.height,
      }),
    ));
  }),
);

const sendLinkSchema = z.object({
  group_id: z.string().min(1).max(128),
  link: z.string().url().max(2000),
  idempotency_key: z.string().min(1).max(255).optional(),
});

app.post("/messages/link", asyncRoute(async (req, res) => {
  const body = sendLinkSchema.parse(req.body);
  res.json(await sendReceipts.run(
    body.idempotency_key,
    () => client.sendLink(body.group_id, body.link),
  ));
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
  idempotency_key: z.string().min(1).max(255).optional(),
});

app.post("/messages/rich-text", asyncRoute(async (req, res) => {
  const body = sendRichTextSchema.parse(req.body);
  res.json(await sendReceipts.run(
    body.idempotency_key,
    () => client.sendRichText(body.group_id, body.parts),
  ));
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
  reportGatewayError("GATEWAY_UNHANDLED_ERROR", message, "CRITICAL", {
    path: _req.path,
  });
  res.status(500).json({ error: { code: "UNKNOWN_ERROR", message } });
});

// Serve before restoring the Zalo session: a login that hangs must not keep the
// health check (and therefore the whole compose stack) from coming up.
app.listen(config.port, "0.0.0.0", () => {
  console.info(`Zalo Gateway listening on port ${config.port} mock=${config.mock}`);
});

void Promise.all([eventOutbox.initialize(), sendReceipts.initialize()])
  .then(() => {
    storesReady = true;
    return client.initialize();
  }).catch((error: unknown) => {
  console.error(
    "ZALO_INITIALIZE_FAILED",
    error instanceof Error ? error.message : "unknown error",
  );
  });
