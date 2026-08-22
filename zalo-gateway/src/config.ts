export const config = {
  port: Number(process.env.PORT ?? 3001),
  gatewaySecret: process.env.ZALO_GATEWAY_SECRET ?? "dev-gateway-secret",
  backendEventUrl:
    process.env.BACKEND_EVENT_URL ?? "http://backend:8000/internal/zalo/events",
  backendAlertUrl:
    process.env.BACKEND_ALERT_URL ?? "http://backend:8000/internal/zalo/alerts",
  zaloEventSecret:
    process.env.ZALO_EVENT_SECRET ?? "dev-zalo-event-secret",
  sessionPath: process.env.ZALO_SESSION_PATH ?? "/data/zalo-session/session.enc",
  sessionSecret: process.env.ZALO_SESSION_SECRET ?? "dev-session-secret-change-me",
  eventOutboxPath:
    process.env.ZALO_EVENT_OUTBOX_PATH ?? "/data/zalo-session/event-outbox",
  sendReceiptPath:
    process.env.ZALO_SEND_RECEIPT_PATH ?? "/data/zalo-session/send-receipts.json",
  mock: process.env.ZALO_MOCK === "true",
  sendIntervalMs: Math.max(0, Number(process.env.ZALO_SEND_INTERVAL_MS ?? 1000)),
};
