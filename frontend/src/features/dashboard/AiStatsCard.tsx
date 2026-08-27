import { ArrowUpRight, ShieldCheck, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import type { Dashboard } from "../../api/types";
import { PERMISSIONS } from "../../lib/permissions";
import { usePermissions } from "../../lib/session";

function compact(value: number) {
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-border bg-muted/40 px-3 py-2.5">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="mt-1 font-display text-lg leading-none">{value}</p>
      {hint && <p className="mt-1 text-[10px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

/**
 * What the classifier cost today, and what it bought.
 *
 * "Blocked" is the number that matters: those are tags the model decided not to
 * send, which is the entire reason for paying per message. Without it the AI
 * only ever looks like an expense.
 */
export function AiStatsCard({ data }: { data?: Dashboard }) {
  const { can } = usePermissions();
  const calls = data?.ai_calls_today ?? 0;
  const blocked = data?.ai_blocked_today ?? 0;
  const latency = data?.ai_avg_latency_ms;
  const inputTokens = data?.ai_tokens_today?.input ?? 0;
  const outputTokens = data?.ai_tokens_today?.output ?? 0;
  const blockedShare = calls > 0 ? Math.round((blocked / calls) * 100) : 0;
  const logLink = can(PERMISSIONS.modelActivityRead) ? "/activity?view=model" : undefined;

  return (
    <article className="card flex min-w-0 flex-col p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">AI phân loại hôm nay</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {data && !data.ai_classifier_enabled
              ? "Đang tắt — tag gửi thẳng"
              : "Quyết định trước mỗi lượt tag"}
          </p>
        </div>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <Sparkles className="h-4 w-4" />
        </span>
      </div>

      {calls ? (
        <>
          <div className="mt-3.5 flex items-center gap-2.5 rounded-xl border border-success-border bg-success-bg px-3 py-2.5">
            <ShieldCheck className="h-5 w-5 shrink-0 text-success-fg" />
            <p className="text-sm text-success-fg">
              <span className="font-display text-xl leading-none">{blocked}</span>
              <span className="ml-2 text-xs">
                lượt tag đã được chặn ({blockedShare}% số lần hỏi)
              </span>
            </p>
          </div>
          <div className="mt-2.5 grid grid-cols-3 gap-2">
            <Metric label="Lượt hỏi" value={String(calls)} />
            <Metric
              label="Độ trễ TB"
              value={latency === null || latency === undefined ? "—" : `${latency}ms`}
            />
            <Metric
              label="Token"
              value={compact(inputTokens + outputTokens)}
              hint={`${compact(inputTokens)} vào · ${compact(outputTokens)} ra`}
            />
          </div>
        </>
      ) : (
        <p className="mt-3.5 rounded-xl border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
          Chưa có lượt phân loại nào hôm nay.
        </p>
      )}

      {logLink && (
        <Link
          to={logLink}
          className="group mt-3 flex items-center justify-between gap-2 border-t border-border pt-3 text-xs text-muted-foreground transition hover:text-accent"
        >
          Xem nhật ký gọi model
          <ArrowUpRight className="h-3.5 w-3.5 transition group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
        </Link>
      )}
    </article>
  );
}
