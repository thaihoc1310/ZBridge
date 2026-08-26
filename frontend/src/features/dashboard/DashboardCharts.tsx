import { CircleDollarSign, MessageSquareText } from "lucide-react";
import type { Dashboard } from "../../api/types";

function DebtBar({
  label,
  value,
  max,
  barClass,
  trackClass,
  valueClass,
}: {
  label: string;
  value: number;
  max: number;
  barClass: string;
  trackClass: string;
  valueClass: string;
}) {
  const width = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <span className={`font-display text-xl leading-none ${valueClass}`}>{value}</span>
      </div>
      <div className={`h-3 overflow-hidden rounded-full ${trackClass}`}>
        <div className={`h-full rounded-full ${barClass}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function DebtChart({ data }: { data?: Dashboard }) {
  const owing = data?.customers_with_debt ?? 0;
  const paid = data?.customers_without_debt ?? 0;
  const total = owing + paid;
  const max = Math.max(owing, paid, 1);

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

      <div
        className="mt-5 space-y-4"
        role="img"
        aria-label={`${owing} khách còn nợ, ${paid} khách không còn nợ`}
      >
        <DebtBar
          label="Còn nợ"
          value={owing}
          max={max}
          barClass="bg-amber-500"
          trackClass="bg-warning-bg"
          valueClass="text-warning-fg"
        />
        <DebtBar
          label="Không nợ"
          value={paid}
          max={max}
          barClass="bg-emerald-500"
          trackClass="bg-success-bg"
          valueClass="text-success-fg"
        />
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
