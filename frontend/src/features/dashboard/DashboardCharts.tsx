import { CircleDollarSign, MessageSquareText } from "lucide-react";
import type { Dashboard } from "../../api/types";

function DebtChart({ data }: { data?: Dashboard }) {
  const owing = data?.customers_with_debt ?? 0;
  const paid = data?.customers_without_debt ?? 0;
  const total = owing + paid;
  const owingPercent = total ? Math.round((owing / total) * 100) : 0;
  const circumference = 2 * Math.PI * 48;
  const owingLength = total ? (owing / total) * circumference : 0;

  return (
    <article className="card min-w-0 p-5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold">Tình trạng công nợ</p>
          <p className="mt-1 text-xs text-muted-foreground">Phân bố trên toàn bộ khách hàng</p>
        </div>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-warning-bg text-warning-fg">
          <CircleDollarSign className="h-4 w-4" />
        </span>
      </div>

      <div className="mt-5 flex flex-col items-center gap-5 sm:flex-row lg:flex-col xl:flex-row">
        <div className="relative h-36 w-36 shrink-0" role="img" aria-label={`${owing} khách còn nợ, ${paid} khách không còn nợ`}>
          <svg className="h-full w-full -rotate-90" viewBox="0 0 120 120" aria-hidden="true">
            <circle cx="60" cy="60" r="48" fill="none" stroke="var(--border)" strokeWidth="13" />
            {total > 0 && <circle cx="60" cy="60" r="48" fill="none" stroke="#f59e0b" strokeWidth="13" strokeLinecap="round" strokeDasharray={`${owingLength} ${circumference}`} />}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="font-display text-3xl leading-none">{owingPercent}%</span>
            <span className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">còn nợ</span>
          </div>
        </div>
        <div className="grid w-full grid-cols-2 gap-3 sm:max-w-xs 2xl:max-w-none">
          <div className="rounded-xl bg-warning-bg p-3">
            <span className="flex items-center gap-2 text-xs text-warning-fg"><span className="h-2 w-2 rounded-full bg-amber-500" />Còn nợ</span>
            <strong className="mt-2 block text-xl text-warning-fg">{owing}</strong>
          </div>
          <div className="rounded-xl bg-muted p-3">
            <span className="flex items-center gap-2 text-xs text-muted-foreground"><span className="h-2 w-2 rounded-full bg-muted-foreground/50" />Không nợ</span>
            <strong className="mt-2 block text-xl text-foreground">{paid}</strong>
          </div>
        </div>
      </div>
    </article>
  );
}

function HourlyMessagesChart({ data }: { data?: Dashboard }) {
  const points = data?.messages_by_hour ?? Array.from({ length: 24 }, (_, hour) => ({ hour, count: 0 }));
  const maximum = Math.max(1, ...points.map(({ count }) => count));
  const sent = points.reduce((sum, { count }) => sum + count, 0);

  return (
    <article className="card min-w-0 p-5 sm:p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold">Tin nhắn gửi theo giờ</p>
          <p className="mt-1 text-xs text-muted-foreground">Các lượt gửi thành công trong hôm nay</p>
        </div>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
          <MessageSquareText className="h-4 w-4" />
        </span>
      </div>

      <div className="mt-5 flex items-end justify-between">
        <div><span className="font-display text-3xl">{sent}</span><span className="ml-2 text-xs text-muted-foreground">đã gửi</span></div>
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Cao nhất {maximum === 1 && sent === 0 ? 0 : maximum}/giờ</span>
      </div>
      <div className="mt-5 grid h-36 items-end gap-1 border-b border-border" style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }} role="img" aria-label={`${sent} tin nhắn gửi thành công hôm nay theo từng giờ`}>
        {points.map(({ hour, count }) => (
          <div key={hour} className="group relative flex h-full items-end" title={`${hour.toString().padStart(2, "0")}:00 — ${count} tin`}>
            <div className={`w-full min-w-0 rounded-t-sm transition-opacity ${count ? "bg-accent opacity-80 group-hover:opacity-100" : "bg-muted"}`} style={{ height: count ? `${Math.max(8, (count / maximum) * 100)}%` : "3px" }} />
            {count > 0 && <span className="pointer-events-none absolute -top-5 left-1/2 hidden -translate-x-1/2 rounded bg-inverse px-1.5 py-0.5 text-[9px] text-inverse-fg group-hover:block">{count}</span>}
          </div>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-5 text-[10px] text-muted-foreground">
        <span>00h</span><span className="text-center">06h</span><span className="text-center">12h</span><span className="text-center">18h</span><span className="text-right">23h</span>
      </div>
    </article>
  );
}

export function DashboardCharts({ data }: { data?: Dashboard }) {
  return <section className="mt-6 grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
    <DebtChart data={data} />
    <HourlyMessagesChart data={data} />
  </section>;
}
