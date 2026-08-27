import { AlertTriangle, CheckCircle2, ChevronRight, Clock3, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import type { Dashboard } from "../../api/types";
import { formatDate } from "../../lib/format";
import { PERMISSIONS } from "../../lib/permissions";
import { usePermissions } from "../../lib/session";

/** How stale a group sync has to get before it is worth saying out loud. */
const STALE_SYNC_HOURS = 24;

type Issue = {
  key: string;
  label: string;
  to?: string;
};

function isStale(timestamp: string | null | undefined) {
  if (!timestamp) return true;
  const parsed = new Date(timestamp).getTime();
  if (Number.isNaN(parsed)) return false;
  return Date.now() - parsed > STALE_SYNC_HOURS * 3_600_000;
}

/**
 * What needs a human, or an explicit all-clear.
 *
 * This replaced a static "the platform is ready" banner that said the same
 * thing while the bot was disconnected. Several of these states stop the
 * automation silently — a paused debt schedule raises nothing at all — so the
 * only place they were visible was a Telegram alert nobody may have kept.
 */
function useIssues(data?: Dashboard): Issue[] {
  const { can } = usePermissions();
  if (!data) return [];
  const botLink = can(PERMISSIONS.botRead) ? "/bot" : undefined;
  const customerLink = can(PERMISSIONS.customerRead);
  const issues: Issue[] = [];

  if (data.bot_status !== "CONNECTED") {
    issues.push({ key: "bot", label: "Bot Zalo chưa kết nối", to: botLink });
  } else if (data.events_healthy === false) {
    // Only worth saying while the bot is otherwise up: a disconnected bot has
    // no event channel either, and two lines for one cause reads as two faults.
    issues.push({
      key: "events",
      label: "Kênh sự kiện Zalo không khỏe — bot không nhận biết được khách đã phản hồi",
      to: botLink,
    });
  } else if (data.events_healthy === null) {
    issues.push({
      key: "gateway",
      label: "Không liên lạc được Zalo Gateway để kiểm tra kênh sự kiện",
      to: botLink,
    });
  }
  if (data.groups_unavailable > 0) {
    issues.push({
      key: "groups",
      label: `${data.groups_unavailable} nhóm Zalo không còn khả dụng`,
      to: customerLink ? "/customers?availability=unavailable" : undefined,
    });
  }
  if (data.debt_missing_file > 0) {
    issues.push({
      key: "debt-file",
      label: `${data.debt_missing_file} khách còn nợ nhưng thiếu file công nợ — lịch nhắc đang tạm dừng`,
      to: customerLink ? "/customers?debt=owed" : undefined,
    });
  }
  if (!data.ai_classifier_enabled) {
    issues.push({
      key: "ai",
      label: "AI phân loại đang tắt — tag tên gửi thẳng, không qua kiểm tra",
      to: can(PERMISSIONS.toolsRead) ? "/tools" : undefined,
    });
  }
  if (isStale(data.last_sync_at)) {
    issues.push({
      key: "sync",
      label: data.last_sync_at
        ? `Chưa đồng bộ nhóm Zalo từ ${formatDate(data.last_sync_at)}`
        : "Chưa từng đồng bộ nhóm Zalo",
      to: customerLink ? "/customers" : undefined,
    });
  }
  return issues;
}

function Timestamps({ data }: { data?: Dashboard }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="rounded-xl border border-border bg-muted/50 p-4">
        <Clock3 className="h-5 w-5 text-accent" />
        <p className="mt-3 text-xs text-muted-foreground">Đồng bộ gần nhất</p>
        <p className="mt-1 text-sm font-semibold">{formatDate(data?.last_sync_at)}</p>
      </div>
      <div className="rounded-xl border border-border bg-muted/50 p-4">
        <CheckCircle2 className="h-5 w-5 text-success-fg" />
        <p className="mt-3 text-xs text-muted-foreground">Gửi thành công gần nhất</p>
        <p className="mt-1 text-sm font-semibold">{formatDate(data?.last_successful_message_at)}</p>
      </div>
    </div>
  );
}

export function HealthStrip({ data }: { data?: Dashboard }) {
  const issues = useIssues(data);

  if (!data) {
    return (
      <section className="mt-3 rounded-2xl border border-border bg-card p-5 shadow-card">
        <div className="h-5 w-56 animate-pulse rounded bg-muted" />
        <div className="mt-4 h-20 animate-pulse rounded-xl bg-muted/60" />
      </section>
    );
  }

  if (!issues.length) {
    return (
      <section className="mt-3 rounded-2xl border border-success-border bg-card p-5 shadow-card sm:p-6">
        <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr] lg:items-center">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-success-border bg-success-bg px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-success-fg">
              <ShieldCheck className="h-3 w-3" />
              Vận hành bình thường
            </span>
            <h2 className="mt-3 font-display text-xl sm:text-2xl">
              Không có gì cần <span className="gradient-text">xử lý.</span>
            </h2>
            <p className="mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground">
              Bot đang kết nối, mọi nhóm còn khả dụng và các lịch tự động đều đang chạy.
            </p>
          </div>
          <Timestamps data={data} />
        </div>
      </section>
    );
  }

  return (
    <section className="mt-3 rounded-2xl border border-warning-border bg-card p-5 shadow-card sm:p-6">
      <div className="grid gap-5 lg:grid-cols-[1.15fr_1fr] lg:items-start">
        <div>
          <span className="inline-flex items-center gap-2 rounded-full border border-warning-border bg-warning-bg px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-warning-fg">
            <AlertTriangle className="h-3 w-3" />
            {issues.length} việc cần xem
          </span>
          <ul className="mt-3 space-y-1.5">
            {issues.map(({ key, label, to }) => {
              const content = (
                <>
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-warning-fg" />
                  <span className="flex-1 leading-relaxed">{label}</span>
                  {to && (
                    <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-accent" />
                  )}
                </>
              );
              return (
                <li key={key}>
                  {to ? (
                    <Link
                      to={to}
                      className="group flex w-full items-start gap-2.5 rounded-lg px-2 py-1.5 text-left text-sm transition hover:bg-muted"
                    >
                      {content}
                    </Link>
                  ) : (
                    <div className="flex items-start gap-2.5 px-2 py-1.5 text-sm">{content}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
        <Timestamps data={data} />
      </div>
    </section>
  );
}
