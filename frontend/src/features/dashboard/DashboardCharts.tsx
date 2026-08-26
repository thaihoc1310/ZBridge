import { CircleDollarSign, MessageSquareText } from "lucide-react";
import type { Dashboard } from "../../api/types";

function DebtChart({ data }: { data?: Dashboard }) {
  const owing = data?.customers_with_debt ?? 0;
  const paid = data?.customers_without_debt ?? 0;
  const total = owing + paid;
  const owingPercent = total ? Math.round((owing / total) * 100) : 0;
  const paidPercent = total ? 100 - owingPercent : 0;
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const split = owing > 0 && paid > 0;
  const gap = split ? 8 : 0;
  const owingLength = total ? Math.max(0, (owing / total) * circumference - gap) : 0;
  const paidLength = total ? Math.max(0, (paid / total) * circumference - gap) : 0;

  return (
    <article className="card min-w-0 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">Tình trạng công nợ</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {total ? `${total} khách hàng` : "Phân bố trên toàn bộ khách hàng"}
          </p>
        </div>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-warning-bg text-warning-fg">
          <CircleDollarSign className="h-4 w-4" />
        </span>
      </div>

      <div className="mt-3 flex items-center gap-4">
        <div
          className="relative h-[5.5rem] w-[5.5rem] shrink-0"
          role="img"
          aria-label={`${owing} khách còn nợ, ${paid} khách không còn nợ`}
        >
          <svg className="h-full w-full -rotate-90" viewBox="0 0 120 120" aria-hidden="true">
            <circle cx="60" cy="60" r={radius} fill="none" stroke="rgb(var(--muted))" strokeWidth="14" />
            {paid > 0 && (
              <circle
                cx="60"
                cy="60"
                r={radius}
                fill="none"
                stroke="rgb(var(--success-fg))"
                strokeWidth="14"
                strokeLinecap="round"
                strokeDasharray={`${paidLength} ${circumference}`}
                strokeDashoffset={-(owingLength + (owing > 0 ? gap : 0))}
              />
            )}
            {owing > 0 && (
              <circle
                cx="60"
                cy="60"
                r={radius}
                fill="none"
                stroke="#f59e0b"
                strokeWidth="14"
                strokeLinecap="round"
                strokeDasharray={`${owingLength} ${circumference}`}
              />
            )}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="font-display text-2xl leading-none">{owingPercent}%</span>
            <span className="mt-0.5 text-[9px] uppercase tracking-wider text-muted-foreground">còn nợ</span>
          </div>
        </div>

        <div className="min-w-0 flex-1 space-y-2.5">
          <div className="flex h-2 overflow-hidden rounded-full bg-muted">
            {owing > 0 && <div className="h-full rounded-full bg-amber-500" style={{ width: `${owingPercent}%` }} />}
            {paid > 0 && <div className="h-full rounded-full bg-emerald-500/80" style={{ width: `${paidPercent}%` }} />}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-xl border border-warning-border bg-warning-bg px-3 py-2">
              <p className="flex items-center gap-1.5 text-[11px] font-medium text-warning-fg">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                Còn nợ
              </p>
              <p className="mt-1 font-display text-xl leading-none text-warning-fg">{owing}</p>
            </div>
            <div className="rounded-xl border border-success-border bg-success-bg px-3 py-2">
              <p className="flex items-center gap-1.5 text-[11px] font-medium text-success-fg">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                Không nợ
              </p>
              <p className="mt-1 font-display text-xl leading-none text-foreground">{paid}</p>
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}

function HourlyMessagesChart({ data }: { data?: Dashboard }) {
  const points = data?.messages_by_hour ?? Array.from({ length: 24 }, (_, hour) => ({ hour, count: 0 }));
  const maximum = Math.max(1, ...points.map(({ count }) => count));
  const sent = points.reduce((sum, { count }) => count + sum, 0);

  return (
    <article className="card min-w-0 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">Tin nhắn gửi theo giờ</p>
          <p className="mt-0.5 text-xs text-muted-foreground">Các lượt gửi thành công trong hôm nay</p>
        </div>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <MessageSquareText className="h-4 w-4" />
        </span>
      </div>

      <div className="mt-3 flex items-end justify-between">
        <div>
          <span className="font-display text-2xl leading-none">{sent}</span>
          <span className="ml-2 text-xs text-muted-foreground">đã gửi</span>
        </div>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Cao nhất {maximum === 1 && sent === 0 ? 0 : maximum}/giờ
        </span>
      </div>
      <div
        className="mt-3 grid h-24 items-end gap-1 border-b border-border"
        style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}
        role="img"
        aria-label={`${sent} tin nhắn gửi thành công hôm nay theo từng giờ`}
      >
        {points.map(({ hour, count }) => (
          <div key={hour} className="group relative flex h-full items-end" title={`${hour.toString().padStart(2, "0")}:00 — ${count} tin`}>
            <div
              className={`w-full min-w-0 rounded-t-sm transition-opacity ${count ? "bg-accent opacity-80 group-hover:opacity-100" : "bg-muted"}`}
              style={{ height: count ? `${Math.max(8, (count / maximum) * 100)}%` : "3px" }}
            />
            {count > 0 && (
              <span className="pointer-events-none absolute -top-5 left-1/2 hidden -translate-x-1/2 rounded bg-inverse px-1.5 py-0.5 text-[9px] text-inverse-fg group-hover:block">
                {count}
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="mt-1.5 grid grid-cols-5 text-[10px] text-muted-foreground">
        <span>00h</span>
        <span className="text-center">06h</span>
        <span className="text-center">12h</span>
        <span className="text-center">18h</span>
        <span className="text-right">23h</span>
      </div>
    </article>
  );
}

export function DashboardCharts({ data }: { data?: Dashboard }) {
  return (
    <section className="mt-3 grid gap-3 lg:grid-cols-[0.85fr_1.15fr]">
      <DebtChart data={data} />
      <HourlyMessagesChart data={data} />
    </section>
  );
}
