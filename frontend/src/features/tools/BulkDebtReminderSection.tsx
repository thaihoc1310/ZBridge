import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Repeat2,
} from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "../../api/client";
import type { DebtBulkApplyResult, DebtBulkPreview } from "../../api/types";
import { Button } from "../../components/ui/Button";

type Step = "config" | "customers" | "done";

export function BulkDebtReminderSection() {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<Step>("config");
  const [day, setDay] = useState<number | "">(25);
  const [repeatEnabled, setRepeatEnabled] = useState(true);
  const [repeat, setRepeat] = useState<number | "">(3);
  const [sendTime, setSendTime] = useState("09:00");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [result, setResult] = useState<DebtBulkApplyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const payload = {
    day_of_month: Number(day),
    repeat_enabled: repeatEnabled,
    repeat_interval_days: Number(repeat),
    send_time: sendTime,
  };
  const preview = useMutation({
    mutationFn: () =>
      api<DebtBulkPreview>("/tools/debt-reminders/bulk/preview", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: (data) => {
      setSelected(
        new Set(
          data.rows
            .filter((row) => row.is_available)
            .map((row) => row.customer_id),
        ),
      );
      setStep("customers");
      setError(null);
    },
    onError: (err) =>
      setError(
        err instanceof ApiError
          ? err.message
          : "Không dựng được bản xem trước.",
      ),
  });
  const apply = useMutation({
    mutationFn: () =>
      api<DebtBulkApplyResult>("/tools/debt-reminders/bulk/apply", {
        method: "POST",
        body: JSON.stringify({ ...payload, customer_ids: [...selected] }),
      }),
    onSuccess: (data) => {
      setResult(data);
      setStep("done");
      queryClient.invalidateQueries({ queryKey: ["customers"] });
    },
    onError: (err) =>
      setError(
        err instanceof ApiError ? err.message : "Không áp được lịch nhắc.",
      ),
  });
  const start = () => {
    if (!Number.isInteger(day) || Number(day) < 1 || Number(day) > 31)
      return setError("Ngày gửi phải từ 1 đến 31.");
    if (repeatEnabled && (!Number.isInteger(repeat) || Number(repeat) < 1 || Number(repeat) > 31))
      return setError("Khoảng lặp phải từ 1 đến 31 ngày.");
    preview.mutate();
  };
  const rows = (preview.data?.rows ?? []).filter((row) =>
    row.name.toLocaleLowerCase("vi").includes(search.toLocaleLowerCase("vi")),
  );

  return (
    <div className="space-y-5">
      {error && (
        <p className="rounded-xl border border-danger-border bg-danger-bg p-3 text-sm text-danger-fg">
          {error}
        </p>
      )}
      {step === "config" && (
        <>
          <div className="rounded-xl border border-info-border bg-info-bg p-4 text-sm text-foreground">
            <strong>Chỉ ghi đè lịch gửi.</strong> Nội dung nhắc cuối cùng và
            cấu hình riêng của từng khách hàng được giữ nguyên. Lịch tự hoạt
            động khi khách còn nợ và có Google Sheet; khi đã thanh toán thì tạm
            ngừng nhưng không mất cấu hình. Lịch rơi vào mùng 1 đến hết mùng 8
            hoặc ngày rằm âm lịch sẽ tự lùi sang ngày hợp lệ tiếp theo; dịp Tết
            tạm dừng từ 28 tháng Chạp đến hết tháng Giêng, kết hợp quy tắc trên
            bot bắt đầu gửi lại từ mùng 9 tháng Hai;
            ngày Giỗ Tổ Hùng Vương (10/03 âm lịch) và các ngày 01/01, 30/04,
            01/05, 02/09 dương lịch cũng không gửi.
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field icon={CalendarClock} label="Ngày gửi hàng tháng">
              <input
                className="field"
                type="number"
                min={1}
                max={31}
                value={day}
                onChange={(event) =>
                  setDay(
                    event.target.value === "" ? "" : Number(event.target.value),
                  )
                }
              />
            </Field>
            <Field icon={Repeat2} label="Lặp lại sau">
              <div className="mb-2 flex items-center justify-between rounded-lg border border-border bg-card px-3 py-2">
                <span className="text-xs font-medium text-muted-foreground">
                  {repeatEnabled ? "Đang bật" : "Đã tắt"}
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={repeatEnabled}
                  aria-label="Bật hoặc tắt nhắc lặp hàng loạt"
                  className={`relative h-6 w-11 rounded-full transition ${repeatEnabled ? "bg-accent" : "bg-muted-foreground/40"}`}
                  onClick={() => {
                    setRepeatEnabled((current) => !current);
                    setError(null);
                  }}
                >
                  <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${repeatEnabled ? "translate-x-5" : ""}`} />
                </button>
              </div>
              <div className="relative">
                <input
                  className="field pr-14 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
                  type="number"
                  min={1}
                  max={31}
                  disabled={!repeatEnabled}
                  value={repeat}
                  onChange={(event) =>
                    setRepeat(
                      event.target.value === ""
                        ? ""
                        : Number(event.target.value),
                    )
                  }
                />
                <span className="pointer-events-none absolute right-4 top-3.5 text-xs text-muted-foreground">
                  ngày
                </span>
              </div>
            </Field>
            <Field icon={Clock3} label="Giờ gửi">
              <input
                className="field"
                type="time"
                value={sendTime}
                onChange={(event) => setSendTime(event.target.value)}
              />
            </Field>
          </div>
          <div className="flex justify-end border-t border-border pt-5">
            <Button loading={preview.isPending} onClick={start}>
              Tiếp tục
            </Button>
          </div>
        </>
      )}
      {step === "customers" && (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <input
              className="field sm:max-w-sm"
              placeholder="Tìm khách hàng..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <div className="flex items-center gap-3 text-xs">
              <strong>{selected.size} đã chọn</strong>
              <button
                className="font-medium text-accent hover:underline"
                onClick={() =>
                  setSelected(
                    selected.size
                      ? new Set()
                      : new Set(
                          (preview.data?.rows ?? [])
                            .filter((row) => row.is_available)
                            .map((row) => row.customer_id),
                        ),
                  )
                }
              >
                {selected.size ? "Bỏ chọn tất cả" : "Chọn tất cả"}
              </button>
            </div>
          </div>
          <div className="app-scrollbar max-h-[28rem] divide-y divide-border overflow-auto rounded-xl border border-border">
            {rows.map((row) => (
              <label
                key={row.customer_id}
                className={`flex cursor-pointer items-start gap-3 p-3.5 hover:bg-muted/40 ${row.is_available ? "" : "opacity-50"}`}
              >
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 accent-accent"
                  disabled={!row.is_available}
                  checked={selected.has(row.customer_id)}
                  onChange={() =>
                    setSelected((current) => {
                      const next = new Set(current);
                      if (next.has(row.customer_id)) next.delete(row.customer_id);
                      else next.add(row.customer_id);
                      return next;
                    })
                  }
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">
                    {row.name}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {`Hiện tại: ngày ${row.current_day_of_month}, ${row.current_repeat_enabled ? `mỗi ${row.current_repeat_interval_days} ngày` : "không lặp"}, lúc ${row.current_send_time}`}
                  </span>
                  <span className="mt-1 flex flex-wrap gap-2 text-[11px]">
                    <em
                      className={
                        row.has_debt ? "text-warning-fg" : "text-success-fg"
                      }
                    >
                      {row.has_debt
                        ? row.has_debt_file
                          ? "Còn nợ · đang hoạt động"
                          : "Còn nợ · chưa thể chạy"
                        : "Đã thanh toán · tạm ngừng"}
                    </em>
                    {!row.has_debt_file && (
                      <em className="text-danger-fg">Chưa có Google Sheet</em>
                    )}
                    {!row.will_change && (
                      <em className="text-muted-foreground">Không thay đổi</em>
                    )}
                  </span>
                </span>
              </label>
            ))}
          </div>
          {selected.size === 0 && (
            <p className="flex items-center gap-2 text-sm text-warning-fg">
              <AlertTriangle className="h-4 w-4" />
              Hãy chọn ít nhất một khách hàng.
            </p>
          )}
          <div className="flex justify-between border-t border-border pt-5">
            <Button variant="ghost" onClick={() => setStep("config")}>
              <ArrowLeft className="h-4 w-4" />
              Quay lại
            </Button>
            <Button
              disabled={!selected.size}
              loading={apply.isPending}
              onClick={() => apply.mutate()}
            >
              Áp lịch cho {selected.size} khách
            </Button>
          </div>
        </>
      )}
      {step === "done" && result && (
        <div className="py-6 text-center">
          <CheckCircle2 className="mx-auto h-12 w-12 text-success-fg" />
          <h3 className="mt-4 font-display text-2xl">Đã áp lịch nhắc</h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Cập nhật {result.updated} · giữ nguyên {result.unchanged} · hủy{" "}
            {result.cancelled_runs} lượt lịch cũ
          </p>
          {result.skipped.length > 0 && (
            <p className="mt-3 text-xs text-warning-fg">
              Bỏ qua nhóm không khả dụng: {result.skipped.join(", ")}
            </p>
          )}
          <Button
            className="mt-6"
            variant="secondary"
            onClick={() => {
              setStep("config");
              setResult(null);
            }}
          >
            Cấu hình lượt khác
          </Button>
        </div>
      )}
    </div>
  );
}

function Field({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof CalendarClock;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label>
      <span className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Icon className="h-4 w-4 text-accent" />
        {label}
      </span>
      {children}
    </label>
  );
}
