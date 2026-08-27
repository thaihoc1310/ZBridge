import { ArrowUpRight, CalendarClock } from "lucide-react";
import { Link } from "react-router-dom";
import type { Dashboard } from "../../api/types";
import { PERMISSIONS } from "../../lib/permissions";
import { usePermissions } from "../../lib/session";

const CLOCK = new Intl.DateTimeFormat("vi-VN", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Ho_Chi_Minh",
});

function timeOfDay(iso: string) {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? "--:--" : CLOCK.format(parsed);
}

/**
 * The operator's first question: what is the bot about to do?
 *
 * Answering it needed a trip to the customer list and a mental sort by
 * next_run_at, so in practice nobody asked until something went wrong.
 */
export function TodayPlanCard({ data }: { data?: Dashboard }) {
  const { can } = usePermissions();
  const reminders = data?.reminders_due_today ?? [];
  const total = data?.reminders_due_today_count ?? 0;
  const waiting = data?.active_mention_followups ?? 0;
  const hidden = Math.max(0, total - reminders.length);
  const now = Date.now();
  const followupLink = can(PERMISSIONS.mentionFollowupRead) ? "/tools" : undefined;
  const historyLink = can(PERMISSIONS.debtReminderHistoryRead) ? "/tools" : undefined;

  return (
    <article className="card flex min-w-0 flex-col p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">Hôm nay bot sẽ làm gì</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {total ? `${total} lượt nhắc công nợ trong hôm nay` : "Lịch nhắc công nợ và vòng tag"}
          </p>
        </div>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <CalendarClock className="h-4 w-4" />
        </span>
      </div>

      {reminders.length ? (
        <ul className="mt-3.5 space-y-1">
          {reminders.map(({ customer_id, customer_name, next_run_at }) => {
            const overdue = new Date(next_run_at).getTime() <= now;
            return (
              <li
                key={customer_id}
                className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm odd:bg-muted/40"
              >
                <span className="font-mono text-xs tabular-nums text-muted-foreground">
                  {timeOfDay(next_run_at)}
                </span>
                <span className="min-w-0 flex-1 truncate">{customer_name}</span>
                {overdue && (
                  <span className="shrink-0 rounded-full bg-warning-bg px-2 py-0.5 text-[10px] font-medium text-warning-fg">
                    đang chờ gửi
                  </span>
                )}
              </li>
            );
          })}
          {hidden > 0 && (
            <li className="px-2 pt-1 text-xs text-muted-foreground">
              {historyLink ? (
                <Link to={historyLink} className="transition hover:text-accent">
                  +{hidden} lượt nữa →
                </Link>
              ) : (
                `+${hidden} lượt nữa`
              )}
            </li>
          )}
        </ul>
      ) : (
        // Content-height, not flex-1: the grid already matches this card to its
        // neighbour, and a stretched dashed box reads as a broken container.
        <p className="mt-3.5 rounded-xl border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
          Không có lượt nhắc công nợ nào trong hôm nay.
        </p>
      )}

      <div className="mt-auto border-t border-border pt-3">
        {followupLink ? (
          <Link
            to={followupLink}
            className="group flex items-center justify-between gap-2 text-sm transition hover:text-accent"
          >
            <span>
              <span className="font-display text-lg leading-none">{waiting}</span>
              <span className="ml-2 text-xs text-muted-foreground">
                vòng tag đang chờ khách phản hồi
              </span>
            </span>
            <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground transition group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-accent" />
          </Link>
        ) : (
          <p className="text-sm">
            <span className="font-display text-lg leading-none">{waiting}</span>
            <span className="ml-2 text-xs text-muted-foreground">
              vòng tag đang chờ khách phản hồi
            </span>
          </p>
        )}
      </div>
    </article>
  );
}
