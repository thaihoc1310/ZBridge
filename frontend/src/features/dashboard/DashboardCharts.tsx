import { CircleDollarSign, MessageSquareText } from "lucide-react";
import { Link } from "react-router-dom";
import type { Dashboard } from "../../api/types";
import { PERMISSIONS } from "../../lib/permissions";
import { usePermissions } from "../../lib/session";
import { AiStatsCard } from "./AiStatsCard";
import { TodayPlanCard } from "./TodayPlanCard";
import { WeeklyTrendChart } from "./WeeklyTrendChart";

/** Below this the fill is too narrow to hold "100%", so the label sits beside it. */
const LABEL_FITS_FROM = 18;

function DebtBar({
  label,
  value,
  total,
  barClass,
  trackClass,
  valueClass,
}: {
  label: string;
  value: number;
  /** Share is taken of the whole customer base, so the two bars add up to 100%. */
  total: number;
  barClass: string;
  trackClass: string;
  valueClass: string;
}) {
  const share = total > 0 ? Math.round((value / total) * 100) : 0;
  const inside = share >= LABEL_FITS_FROM;

  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <span className={`font-display text-xl leading-none ${valueClass}`}>{value}</span>
      </div>
      <div className={`flex h-9 items-center overflow-hidden rounded-lg ${trackClass}`}>
        <div
          className={`flex h-full items-center justify-center rounded-lg px-2 ${barClass}`}
          style={{ width: `${share}%` }}
        >
          {total > 0 && inside && (
            <span className="text-xs font-semibold tabular-nums text-white">{share}%</span>
          )}
        </div>
        {total > 0 && !inside && (
          <span className={`px-2.5 text-xs font-semibold tabular-nums ${valueClass}`}>
            {share}%
          </span>
        )}
      </div>
    </div>
  );
}

function DebtChart({ data }: { data?: Dashboard }) {
  const owing = data?.customers_with_debt ?? 0;
  const paid = data?.customers_without_debt ?? 0;
  const total = owing + paid;

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
        className="mt-5 space-y-3.5"
        role="img"
        aria-label={`${owing} khách còn nợ, ${paid} khách không còn nợ, trên tổng ${total}`}
      >
        <DebtBar
          label="Còn nợ"
          value={owing}
          total={total}
          barClass="bg-amber-500"
          trackClass="bg-warning-bg"
          valueClass="text-warning-fg"
        />
        <DebtBar
          label="Không nợ"
          value={paid}
          total={total}
          barClass="bg-emerald-500"
          trackClass="bg-success-bg"
          valueClass="text-success-fg"
        />
      </div>

      <DebtFunnel data={data} />
    </article>
  );
}

/**
 * Did the reminders achieve anything this month?
 *
 * SKIPPED is the interesting one, and it has exactly one cause: the run was
 * already scheduled when staff marked the customer paid, so the worker found
 * has_debt false and sent nothing. The reminder turned out unnecessary.
 *
 * Its first label here read "khách đã trả trước", which in Vietnamese means
 * paid in advance — a different business concept entirely. It says "không cần
 * nhắc" now, with the mechanism in a title attribute.
 *
 * CANCELLED is left out by the API: it only means somebody edited a schedule.
 */
function DebtFunnel({ data }: { data?: Dashboard }) {
  const { can } = usePermissions();
  const sent = data?.debt_runs_month?.sent ?? 0;
  const skipped = data?.debt_runs_month?.skipped ?? 0;
  const failed = data?.debt_runs_month?.failed ?? 0;
  const historyLink = can(PERMISSIONS.debtReminderHistoryRead) ? "/tools" : undefined;

  return (
    <div className="mt-5 border-t border-border pt-3.5">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-xs font-medium text-muted-foreground">Nhắc công nợ tháng này</p>
        {historyLink && (
          <Link to={historyLink} className="text-[11px] text-muted-foreground transition hover:text-accent">
            Lịch sử →
          </Link>
        )}
      </div>
      {sent + skipped + failed === 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">Chưa có lượt nhắc nào trong tháng.</p>
      ) : (
        <dl className="mt-2.5 grid grid-cols-3 gap-2">
          <div
            className="rounded-lg bg-accent-soft px-2.5 py-2"
            title="Số lượt nhắc đã gửi xong. Mỗi lượt gồm 3 tin nhắn: ảnh, link và nội dung."
          >
            <dd className="font-display text-lg leading-none text-accent">{sent}</dd>
            <dt className="mt-1 text-[10px] leading-tight text-muted-foreground">đã gửi</dt>
          </div>
          <div
            className="rounded-lg bg-success-bg px-2.5 py-2"
            title="Đã lên lịch nhắc, nhưng khách được đánh dấu đã thanh toán trước khi bot gửi nên bot bỏ qua."
          >
            <dd className="font-display text-lg leading-none text-success-fg">{skipped}</dd>
            <dt className="mt-1 text-[10px] leading-tight text-muted-foreground">không cần nhắc</dt>
          </div>
          <div
            className="rounded-lg bg-danger-bg px-2.5 py-2"
            title={
              "Số lượt nhắc bỏ hẳn: bot đã thử 5 lần và vẫn không gửi được." +
              " Lượt lỗi rồi thử lại thành công được tính vào “đã gửi”, không tính ở đây." +
              " Khác với ô “Thất bại hôm nay” phía trên — ô đó đếm từng lần gửi lỗi."
            }
          >
            <dd className="font-display text-lg leading-none text-danger-fg">{failed}</dd>
            <dt className="mt-1 text-[10px] leading-tight text-muted-foreground">thất bại</dt>
          </div>
        </dl>
      )}
    </div>
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
      {sent === 0 ? (
        // Matches WeeklyTrendChart: 24 invisible stubs under a tall band read as
        // a chart that failed to draw, especially on the true-black theme.
        <p className="mt-3 rounded-xl border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
          Chưa có lượt gửi nào hôm nay.
        </p>
      ) : (
        <>
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
        </>
      )}

      <FeatureBreakdown data={data} />
    </article>
  );
}

/** Which feature the day's sends came from — turns a bare total into a cause. */
function FeatureBreakdown({ data }: { data?: Dashboard }) {
  const byType = data?.messages_by_type_today;
  const chips = [
    { key: "debt", label: "Nhắc nợ", value: byType?.debt ?? 0 },
    { key: "mention", label: "Tag tên", value: byType?.mention ?? 0 },
    { key: "manual", label: "Thủ công", value: byType?.manual ?? 0 },
  ];
  if (chips.every(({ value }) => value === 0)) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-1.5 border-t border-border pt-3">
      {chips.map(({ key, label, value }) => (
        <span
          key={key}
          className={`rounded-full px-2 py-0.5 text-[11px] ${
            value ? "bg-muted text-foreground" : "bg-muted/50 text-muted-foreground"
          }`}
        >
          {label} <span className="font-semibold tabular-nums">{value}</span>
        </span>
      ))}
    </div>
  );
}

export function DashboardCharts({ data }: { data?: Dashboard }) {
  return (
    <>
      <section className="mt-3 grid gap-3 lg:grid-cols-[0.85fr_1.15fr]">
        <DebtChart data={data} />
        <HourlyMessagesChart data={data} />
      </section>
      <section className="mt-3 grid gap-3 lg:grid-cols-2">
        <TodayPlanCard data={data} />
        <WeeklyTrendChart data={data} />
      </section>
      <section className="mt-3">
        <AiStatsCard data={data} />
      </section>
    </>
  );
}
