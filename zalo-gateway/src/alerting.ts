import { config } from "./config.js";

export type AlertSeverity = "WARNING" | "ERROR" | "CRITICAL";

/**
 * Hand a gateway problem to the backend, which owns the shared dedup counter and
 * the Telegram credentials. Deliberately best-effort: alerting must never break
 * or slow down the Zalo work that raised it.
 */
export function reportGatewayError(
  code: string,
  message: string,
  severity: AlertSeverity = "ERROR",
  context: Record<string, string> = {},
): void {
  void (async () => {
    try {
      const response = await fetch(config.backendAlertUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Zalo-Event-Secret": config.zaloEventSecret,
        },
        body: JSON.stringify({ code, message, severity, context }),
        signal: AbortSignal.timeout(5_000),
      });
      if (!response.ok) {
        // Never re-report through this path: it would loop on a broken backend.
        console.error("ALERT_REJECTED code=%s status=%d", code, response.status);
      }
    } catch (error) {
      console.error(
        "ALERT_FORWARD_FAILED code=%s error=%s",
        code,
        error instanceof Error ? error.message : "unknown",
      );
    }
  })();
}
