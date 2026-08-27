import { TrendingUp } from "lucide-react";
import type { Dashboard, DashboardDailyMessages } from "../../api/types";

const WEEKDAY = new Intl.DateTimeFormat("vi-VN", { weekday: "short", timeZone: "UTC" });

/** Parsed as UTC noon so a date-only string cannot slip a day either way. */
function dayLabels(iso: string) {
  const parsed = new Date(`${iso}T12:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return { weekday: "--", day: "--" };
  return {
    weekday: WEEKDAY.format(parsed).replace(".", ""),
    day: String(parsed.getUTCDate()).padStart(2, "0"),
  };
}

function Column({
  entry,
  maximum,
  isToday,
}: {
  entry: DashboardDailyMessages;
  maximum: number;
  isToday: boolean;
}) {
  const { weekday, day } = dayLabels(entry.date);
  const total = entry.sent + entry.failed;
  // Percentages of the tallest day, so the shape survives any volume.
  const sentHeight = (entry.sent / maximum) * 100;
  const failedHeight = (entry.failed / maximum) * 100;

  return (
    <div className="flex min-w-0 flex-col items-center gap-1.5">
      <div
        className="flex h-28 w-full flex-col justify-end gap-px"
        title={`${weekday} ${day}: ${entry.sent} gửi thành công, ${entry.failed} thất bại`}
      >
        {entry.failed > 0 && (
          <div
            className="w-full rounded-t-sm bg-danger-fg/70"
            style={{ height: `${Math.max(3, failedHeight)}%` }}
          />
        )}
        {entry.sent > 0 ? (
          <div
            className={`w-full ${entry.failed > 0 ? "" : "rounded-t-sm"} ${
              isToday ? "bg-accent" : "bg-accent/55"
            }`}
            style={{ height: `${Math.max(3, sentHeight)}%` }}
          />
        ) : (
          !entry.failed && <div className="w-full rounded-t-sm bg-muted" style={{ height: "3px" }} />
        )}
      </div>
      <div className="text-center">
        <p
          className={`text-[10px] leading-none ${
            isToday ? "font-semibold text-accent" : "text-muted-foreground"
          }`}
        >
          {weekday}
        </p>
        <p className="mt-0.5 text-[10px] leading-none tabular-nums text-muted-foreground">{day}</p>
      </div>
      <span className="sr-only">{total} tin</span>
    </div>
  );
}

/**
 * Seven days of send volume, which is what turns "40 today" into a judgement.
 *
 * The window matches BotDeliveryLog retention deliberately: asking for more
 * would draw a decline that is only the retention job deleting rows.
 */
export function WeeklyTrendChart({ data }: { data?: Dashboard }) {
  const days = data?.daily_messages ?? [];
  const maximum = Math.max(1, ...days.map(({ sent, failed }) => sent + failed));
  const totalSent = days.reduce((sum, { sent }) => sum + sent, 0);
  const totalFailed = days.reduce((sum, { failed }) => sum + failed, 0);

  return (
    <article className="card min-w-0 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">7 ngày gần nhất</p>
          <p className="mt-0.5 text-xs text-muted-foreground">Đúng khoảng lưu nhật ký gửi</p>
        </div>
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
          <TrendingUp className="h-4 w-4" />
        </span>
      </div>

      <div className="mt-3 flex items-end justify-between gap-3">
        <div>
          <span className="font-display text-2xl leading-none">{totalSent}</span>
          <span className="ml-2 text-xs text-muted-foreground">đã gửi</span>
        </div>
        {totalFailed > 0 && (
          <span className="rounded-full bg-danger-bg px-2 py-0.5 text-[11px] font-medium text-danger-fg">
            {totalFailed} thất bại
          </span>
        )}
      </div>

      {totalSent + totalFailed === 0 ? (
        // A grid of 3px stubs under a tall empty band just looks unfinished, and
        // on the true-black theme the stubs are invisible anyway.
        <p className="mt-3 rounded-xl border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
          Chưa có lượt gửi nào trong 7 ngày qua.
        </p>
      ) : (
        <div
          className="mt-3 grid gap-1.5 border-b border-border pb-2"
          style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }}
          role="img"
          aria-label={`${totalSent} tin gửi thành công và ${totalFailed} thất bại trong 7 ngày gần nhất`}
        >
          {days.map((entry, index) => (
            <Column
              key={entry.date}
              entry={entry}
              maximum={maximum}
              isToday={index === days.length - 1}
            />
          ))}
        </div>
      )}
    </article>
  );
}
