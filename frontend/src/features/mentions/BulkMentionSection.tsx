import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Check, CheckCircle2, Tag, AtSign } from "lucide-react";
import { useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import type {
  BulkMentionApplyResult,
  BulkMentionPreview,
  MentionTarget,
  MentionTimeWindow,
  StaffMember,
} from "../../api/types";
import { Button } from "../../components/ui/Button";
import {
  DelayField,
  FeatureSection,
  TargetPicker,
  TimeWindowsField,
  defaultTimeWindows,
  mergeTimeWindows,
  toDelayMinutes,
  type DelayUnit,
} from "./MentionConfigForm";

type Step = "config" | "customers" | "done";

/**
 * Applies one tag setup across many customers, overwriting what is there.
 *
 * Overwrite is deliberate: this company runs the same setup nearly everywhere,
 * and the escape hatch for an exception is unticking its row on step two rather
 * than a merge rule nobody would remember.
 */
export function BulkMentionSection({ canEdit }: { canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState<Step>("config");
  const [mentionEnabled, setMentionEnabled] = useState(true);
  const [priceEnabled, setPriceEnabled] = useState(false);
  const [mentionTargets, setMentionTargets] = useState<MentionTarget[]>([]);
  const [priceTargets, setPriceTargets] = useState<MentionTarget[]>([]);
  const [delayValue, setDelayValue] = useState<number | "">(2);
  const [delayUnit, setDelayUnit] = useState<DelayUnit>("hours");
  const [activeWindows, setActiveWindows] = useState<MentionTimeWindow[]>(defaultTimeWindows);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkMentionApplyResult | null>(null);

  const roster = useQuery({
    queryKey: ["staff"],
    queryFn: () => api<StaffMember[]>("/staff"),
  });
  const staff = useMemo(() => roster.data ?? [], [roster.data]);

  const delayMinutes = toDelayMinutes(delayValue, delayUnit);
  const body = useMemo(
    () => ({
      mention_tag_enabled: mentionEnabled,
      price_inquiry_enabled: priceEnabled,
      delay_minutes: delayMinutes,
      active_windows: mergeTimeWindows(activeWindows) ?? defaultTimeWindows,
      targets: mentionEnabled ? mentionTargets : [],
      price_targets: priceEnabled ? priceTargets : [],
    }),
    [mentionEnabled, priceEnabled, mentionTargets, priceTargets, delayMinutes, activeWindows],
  );

  /** The roster is the pool here, the way group members are in the per-customer form. */
  const pool = useMemo(
    () =>
      staff.map((member) => ({
        user_id: member.user_id,
        display_name: member.display_name,
        avatar_url: member.avatar_url,
      })),
    [staff],
  );

  const preview = useMutation({
    mutationFn: () =>
      api<BulkMentionPreview>("/staff/bulk-mention/preview", {
        method: "POST",
        body: JSON.stringify({ ...body, customer_ids: [] }),
      }),
    onSuccess: (data) => {
      setSelected(
        new Set(data.rows.filter((row) => row.is_available).map((row) => row.customer_id)),
      );
      setStep("customers");
      setError(null);
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Không dựng được bản xem trước."),
  });

  const apply = useMutation({
    mutationFn: () =>
      api<BulkMentionApplyResult>("/staff/bulk-mention/apply", {
        method: "POST",
        body: JSON.stringify({ ...body, customer_ids: [...selected] }),
      }),
    onSuccess: (data) => {
      setResult(data);
      setStep("done");
      queryClient.invalidateQueries({ queryKey: ["staff"] });
      queryClient.invalidateQueries({ queryKey: ["customers"] });
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Không áp được cấu hình."),
  });

  const start = () => {
    if (!mergeTimeWindows(activeWindows)) {
      setError("Hãy nhập đầy đủ khung giờ và đảm bảo giờ bắt đầu sớm hơn giờ kết thúc.");
      return;
    }
    if (!Number.isFinite(delayMinutes) || delayMinutes < 1 || delayMinutes > 10_080) {
      setError("Thời gian chờ phải từ 1 phút đến 7 ngày.");
      return;
    }
    setError(null);
    preview.mutate();
  };

  const rows = preview.data?.rows ?? [];
  const willChange = rows.filter((row) => selected.has(row.customer_id));
  const followupsToCancel = willChange.reduce((sum, row) => sum + row.active_followups, 0);

  return (
    <div>

      {error && (
        <p className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </p>
      )}

      {step === "config" && (
        <div className="space-y-5">
          <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
            <div className="divide-y divide-border rounded-xl border border-border">
              <FeatureSection
                icon={AtSign}
                title="Tag lại khi có người tag"
                hint="Bot nhắc lại đến khi người được tag nhắn hoặc thả tim/like trong nhóm."
                enabled={mentionEnabled}
                onToggle={() => { setMentionEnabled((on) => !on); setError(null); }}
                disabled={!canEdit}
              >
                <TargetPicker
                  label="Người cần tag lại"
                  selected={mentionTargets}
                  onChange={setMentionTargets}
                  members={pool}
                  loading={roster.isLoading}
                  errorMessage={
                    pool.length === 0 && !roster.isLoading
                      ? "Chưa có nhân sự nào. Thêm ở mục Nhân sự trước."
                      : null
                  }
                  disabled={!canEdit}
                  onDirty={() => setError(null)}
                />
              </FeatureSection>

              <FeatureSection
                icon={Tag}
                title="Tag khi khách hỏi giá"
                hint="Khách nhắn có “giá”, “bgia”, “baogia” hoặc “bao gia” thì AI đọc xem có phải hỏi giá thật không, đúng mới tag. AI lỗi thì bỏ qua, không tag."
                enabled={priceEnabled}
                onToggle={() => { setPriceEnabled((on) => !on); setError(null); }}
                disabled={!canEdit}
              >
                <TargetPicker
                  label="Người phụ trách báo giá"
                  selected={priceTargets}
                  onChange={setPriceTargets}
                  members={pool}
                  loading={roster.isLoading}
                  errorMessage={
                    pool.length === 0 && !roster.isLoading
                      ? "Chưa có nhân sự nào. Thêm ở mục Nhân sự trước."
                      : null
                  }
                  disabled={!canEdit}
                  onDirty={() => setError(null)}
                />
              </FeatureSection>
            </div>

            <div className="space-y-6">
              <TimeWindowsField
                windows={activeWindows}
                onChange={setActiveWindows}
                disabled={!canEdit}
                onDirty={() => setError(null)}
              />
              <DelayField
                id="bulk-delay"
                value={delayValue}
                unit={delayUnit}
                onChange={(value, unit) => { setDelayValue(value); setDelayUnit(unit); }}
                disabled={!canEdit}
                onDirty={() => setError(null)}
              />
            </div>
          </div>

          <div className="flex justify-end border-t border-border pt-5">
            <Button disabled={!canEdit} loading={preview.isPending} onClick={start}>
              Tiếp tục
              <Check className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}

      {step === "customers" && (
        <div>
          {preview.data?.gateway_error && (
            <p className="mb-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              Không đọc được thành viên nhóm ({preview.data.gateway_error}). Khi bấm áp,
              hệ thống sẽ kiểm tra lại; nhóm nào Zalo vẫn không trả dữ liệu sẽ được bỏ qua.
            </p>
          )}
          <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
            Zalo chỉ tag được người đang ở trong nhóm. Ai không có mặt trong nhóm nào thì
            sẽ được bỏ khỏi riêng khách hàng đó, phần còn lại vẫn ghi bình thường.
          </p>
          <div className="mb-3 flex items-center justify-between gap-4">
            <span className="text-sm font-semibold">
              Áp cho {selected.size}/{rows.filter((row) => row.is_available).length} khách hàng
            </span>
            <button
              type="button"
              className="text-xs font-medium text-accent hover:underline"
              onClick={() =>
                setSelected(
                  selected.size === 0
                    ? new Set(rows.filter((r) => r.is_available).map((r) => r.customer_id))
                    : new Set(),
                )
              }
            >
              {selected.size === 0 ? "Chọn tất cả" : "Bỏ chọn tất cả"}
            </button>
          </div>
          <div className="app-scrollbar max-h-96 divide-y divide-border overflow-auto rounded-xl border border-border">
            {rows.map((row) => (
              <label
                key={row.customer_id}
                className={`flex cursor-pointer items-center gap-3 p-3.5 ${row.is_available ? "hover:bg-muted/40" : "opacity-50"}`}
              >
                <input
                  type="checkbox"
                  className="h-4 w-4 shrink-0 accent-blue-600"
                  disabled={!row.is_available}
                  checked={selected.has(row.customer_id)}
                  onChange={(event) =>
                    setSelected((current) => {
                      const next = new Set(current);
                      if (event.target.checked) next.add(row.customer_id);
                      else next.delete(row.customer_id);
                      return next;
                    })
                  }
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{row.name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {!row.is_available
                      ? "Nhóm không khả dụng"
                      : !row.will_change
                        ? "Đã đúng cấu hình này, sẽ giữ nguyên"
                        : `Đang có ${row.current_target_count} người${row.active_followups ? ` · ${row.active_followups} vòng nhắc sẽ bị huỷ` : ""}`}
                  </span>
                </span>
                {row.missing_members.length > 0 && (
                  <span
                    title={`${row.missing_members.join(", ")} không phải thành viên nhóm Zalo này nên sẽ không được ghi vào danh sách tag của khách hàng này.`}
                    className="flex max-w-56 shrink-0 items-start gap-1 rounded-lg bg-amber-50 px-2 py-1 text-[11px] font-medium leading-snug text-amber-700"
                  >
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                    <span>
                      Không có trong nhóm nên sẽ bỏ:{" "}
                      {row.missing_members.join(", ")}
                    </span>
                  </span>
                )}
              </label>
            ))}
          </div>
          <div className="mt-5 flex items-center justify-between gap-3 border-t border-border pt-5">
            <Button variant="ghost" onClick={() => setStep("config")}>
              <ArrowLeft className="h-4 w-4" />
              Quay lại
            </Button>
            <Button
              variant="danger"
              disabled={selected.size === 0}
              loading={apply.isPending}
              onClick={() => apply.mutate()}
            >
              Ghi đè {selected.size} khách hàng
              {followupsToCancel > 0 && `, huỷ ${followupsToCancel} vòng nhắc`}
            </Button>
          </div>
        </div>
      )}

      {step === "done" && result && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5">
          <p className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
            <CheckCircle2 className="h-4 w-4" />
            Cập nhật {result.updated} khách hàng, tạo mới {result.created}
            {result.unchanged > 0 && `, giữ nguyên ${result.unchanged}`}.
          </p>
          <ul className="mt-3 space-y-1 text-sm text-emerald-900">
            {result.cancelled_followups > 0 && (
              <li>Đã huỷ {result.cancelled_followups} vòng nhắc đang chạy.</li>
            )}
            {result.skipped.length > 0 && (
              <li>Bỏ qua: {result.skipped.join(", ")}.</li>
            )}
            {Object.entries(result.dropped_members).map(([name, count]) => (
              <li key={name}>
                {name} không có trong {count} nhóm nên đã bị bỏ khỏi những nhóm đó.
              </li>
            ))}
          </ul>
          <Button variant="secondary" className="mt-4" onClick={() => setStep("config")}>
            Cấu hình tiếp
          </Button>
        </div>
      )}
    </div>
  );
}
