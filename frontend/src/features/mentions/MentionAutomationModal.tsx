import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AtSign,
  Check,
  ChevronDown,
  Clock3,
  Plus,
  Search,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import type {
  GroupMember,
  MentionAutomation,
  MentionTimeWindow,
  MentionTarget,
} from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { initials } from "../../lib/format";
import { PERMISSIONS } from "../../lib/permissions";
import { usePermissions } from "../../lib/session";

type Props = {
  customerId: string;
  customerName: string;
  open: boolean;
  onClose: () => void;
};

type DelayUnit = "minutes" | "hours" | "days";

const defaultTimeWindows: MentionTimeWindow[] = [
  { start: "08:00", end: "12:00" },
  { start: "14:00", end: "18:00" },
];

const delayUnits: Record<
  DelayUnit,
  { label: string; multiplier: number; min: number; max: number; step: number }
> = {
  minutes: { label: "Phút", multiplier: 1, min: 1, max: 10_080, step: 1 },
  hours: { label: "Giờ", multiplier: 60, min: 0.25, max: 168, step: 0.25 },
  days: { label: "Ngày", multiplier: 1_440, min: 0.25, max: 7, step: 0.25 },
};

const delayPresets: Array<{ label: string; value: number; unit: DelayUnit }> = [
  { label: "15 phút", value: 15, unit: "minutes" },
  { label: "30 phút", value: 30, unit: "minutes" },
  { label: "1 giờ", value: 1, unit: "hours" },
  { label: "2 giờ", value: 2, unit: "hours" },
  { label: "1 ngày", value: 1, unit: "days" },
  { label: "3 ngày", value: 3, unit: "days" },
];

export function MentionAutomationModal({
  customerId,
  customerName,
  open,
  onClose,
}: Props) {
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const canEdit = can(PERMISSIONS.mentionUpdate);
  const pickerRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<MentionTarget[]>([]);
  const [delayValue, setDelayValue] = useState<number | "">(2);
  const [delayUnit, setDelayUnit] = useState<DelayUnit>("hours");
  const [activeWindows, setActiveWindows] = useState<MentionTimeWindow[]>(
    defaultTimeWindows,
  );
  const [enabled, setEnabled] = useState(true);
  const [explanationOpen, setExplanationOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const automation = useQuery({
    queryKey: ["mention-automation", customerId],
    queryFn: () => api<MentionAutomation>(`/customers/${customerId}/mention-automation`),
    enabled: open,
    refetchOnWindowFocus: false,
  });
  const members = useQuery({
    queryKey: ["customer-members", customerId],
    queryFn: () => api<GroupMember[]>(`/customers/${customerId}/members`),
    enabled: open,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!open || !automation.data) return;
    const delay = splitDelay(automation.data.delay_minutes);
    setSelected(automation.data.targets);
    setDelayValue(delay.value);
    setDelayUnit(delay.unit);
    setActiveWindows(automation.data.active_windows);
    setEnabled(automation.data.enabled || automation.data.id === null);
    setSearch("");
    setFormError(null);
  }, [automation.data, open]);

  useEffect(() => {
    if (!pickerOpen) return;
    const closePicker = (event: MouseEvent) => {
      if (!pickerRef.current?.contains(event.target as Node)) setPickerOpen(false);
    };
    document.addEventListener("mousedown", closePicker);
    return () => document.removeEventListener("mousedown", closePicker);
  }, [pickerOpen]);

  const normalizedSearch = normalize(search);
  const selectedIds = useMemo(
    () => new Set(selected.map((target) => target.user_id)),
    [selected],
  );
  const suggestions = (members.data ?? [])
    .filter((member) => !selectedIds.has(member.user_id))
    .filter(
      (member) =>
        !normalizedSearch ||
        normalize(member.display_name).includes(normalizedSearch) ||
        member.user_id.toLowerCase().includes(normalizedSearch),
    )
    .slice(0, 50);
  const delayMinutes = toDelayMinutes(delayValue, delayUnit);

  const save = useMutation({
    mutationFn: () => {
      if (selected.length === 0) throw new Error("Hãy chọn ít nhất một thành viên.");
      if (!Number.isFinite(delayMinutes) || delayMinutes < 1 || delayMinutes > 10_080) {
        throw new Error("Thời gian chờ phải từ 1 phút đến 7 ngày.");
      }
      const normalizedWindows = mergeTimeWindows(activeWindows);
      if (!normalizedWindows) {
        throw new Error(
          "Hãy nhập đầy đủ khung giờ và đảm bảo giờ bắt đầu sớm hơn giờ kết thúc.",
        );
      }
      return api<MentionAutomation>(`/customers/${customerId}/mention-automation`, {
        method: "PUT",
        body: JSON.stringify({
          enabled,
          delay_minutes: delayMinutes,
          active_windows: normalizedWindows,
          targets: selected,
        }),
      });
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["mention-automation", customerId], data);
      onClose();
    },
    onError: (error) => {
      setFormError(
        error instanceof ApiError || error instanceof Error
          ? error.message
          : "Không thể lưu cấu hình.",
      );
    },
  });

  const addMember = (member: GroupMember) => {
    setSelected((current) => [...current, member]);
    setSearch("");
    setPickerOpen(true);
    setFormError(null);
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      className="max-w-2xl"
      title="Tag tên tự động"
      description={`Thiết lập nhắc lại tên thành viên trong ${customerName}.`}
    >
      {automation.isLoading ? (
        <div className="flex min-h-72 items-center justify-center text-sm text-muted-foreground">
          Đang tải cấu hình...
        </div>
      ) : automation.isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-700">Không thể tải cấu hình tag tên.</p>
          <Button
            variant="secondary"
            className="mt-4"
            onClick={() => void automation.refetch()}
          >
            Thử lại
          </Button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="rounded-xl border border-blue-100 bg-blue-50/70 p-4">
            <button
              type="button"
              className="flex w-full items-center gap-3 text-left"
              aria-expanded={explanationOpen}
              onClick={() => setExplanationOpen((current) => !current)}
            >
              <AtSign className="h-5 w-5 shrink-0 text-accent" />
              <span className="flex-1 text-sm font-semibold text-slate-700">
                Giải thích cách hoạt động
              </span>
              <ChevronDown
                className={`h-4 w-4 text-slate-500 transition ${explanationOpen ? "rotate-180" : ""}`}
              />
            </button>
            {explanationOpen && (
              <p className="mt-3 border-t border-blue-100 pt-3 text-sm leading-relaxed text-slate-700">
                Khi có người tag một thành viên đã chọn, bot sẽ đợi theo thời gian bên
                dưới rồi tag lại đúng thành viên đó. Việc nhắc sẽ lặp lại theo khoảng
                thời gian này cho đến khi chính thành viên đó gửi bất kỳ tin nhắn nào
                trong nhóm. Tin nhắn do bot gửi sẽ được bỏ qua.
              </p>
            )}
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between gap-4">
              <label className="text-sm font-semibold">Người cần tag lại</label>
              <span className="text-xs text-muted-foreground">Đã chọn {selected.length}</span>
            </div>
            <div ref={pickerRef} className="relative">
              <div
                className="flex min-h-14 flex-wrap items-center gap-2 rounded-xl border border-border bg-white p-2 transition focus-within:border-accent focus-within:ring-2 focus-within:ring-blue-100"
                onClick={() => setPickerOpen(true)}
              >
                {selected.map((target) => (
                  <span
                    key={target.user_id}
                    className="inline-flex max-w-full items-center gap-2 rounded-lg bg-blue-50 py-1.5 pl-2 pr-1 text-xs font-medium text-blue-800"
                  >
                    <Avatar member={target} small />
                    <span className="max-w-40 truncate">{target.display_name}</span>
                    <button
                      type="button"
                      className="rounded-md p-1 hover:bg-blue-100"
                      aria-label={`Bỏ chọn ${target.display_name}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelected((current) =>
                          current.filter((item) => item.user_id !== target.user_id),
                        );
                      }}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </span>
                ))}
                <div className="relative min-w-44 flex-1">
                  <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    className="h-9 w-full bg-transparent pl-8 pr-7 text-sm outline-none placeholder:text-slate-400"
                    value={search}
                    onFocus={() => setPickerOpen(true)}
                    onChange={(event) => {
                      setSearch(event.target.value);
                      setPickerOpen(true);
                    }}
                    placeholder={selected.length ? "Chọn thêm..." : "Tìm và chọn thành viên..."}
                  />
                  <ChevronDown className="absolute right-1 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                </div>
              </div>

              {pickerOpen && (
                <div className="app-scrollbar absolute z-20 mt-2 max-h-64 w-full overflow-auto rounded-xl border border-border bg-white p-1.5 shadow-xl">
                  {members.isLoading && (
                    <div className="p-6 text-center text-sm text-muted-foreground">
                      Đang lấy danh sách thành viên từ Zalo...
                    </div>
                  )}
                  {members.isError && (
                    <div className="p-5 text-center text-sm text-red-600">
                      Không thể lấy thành viên. Hãy kiểm tra kết nối bot rồi thử lại.
                    </div>
                  )}
                  {!members.isLoading && !members.isError && suggestions.length === 0 && (
                    <div className="p-6 text-center text-sm text-muted-foreground">
                      {selected.length === members.data?.length
                        ? "Bạn đã chọn tất cả thành viên."
                        : "Không tìm thấy thành viên phù hợp."}
                    </div>
                  )}
                  {suggestions.map((member) => (
                    <button
                      key={member.user_id}
                      type="button"
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-muted"
                      onClick={() => addMember(member)}
                    >
                      <Avatar member={member} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">
                          {member.display_name}
                        </span>
                        <span className="block truncate font-mono text-[10px] text-muted-foreground">
                          {member.user_id}
                        </span>
                      </span>
                      <Check className="h-4 w-4 text-slate-300" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div>
            <div className="mb-3 flex items-start justify-between gap-4">
              <div>
                <span className="block text-sm font-semibold">Khung giờ hoạt động</span>
                <p className="mt-1 text-xs text-muted-foreground">
                  Bot chỉ gửi tag trong các khung giờ này, theo giờ Việt Nam (UTC+7).
                </p>
              </div>
              <Button
                variant="secondary"
                className="shrink-0"
                disabled={activeWindows.length >= 24}
                onClick={() => {
                  setActiveWindows((current) => [...current, { start: "", end: "" }]);
                  setFormError(null);
                }}
              >
                <Plus className="h-4 w-4" />
                Thêm khung giờ
              </Button>
            </div>
            <div className="space-y-2">
              {activeWindows.map((window, index) => (
                <div
                  key={index}
                  className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_40px] items-center gap-2"
                >
                  <input
                    className="field"
                    type="time"
                    aria-label={`Giờ bắt đầu khung ${index + 1}`}
                    value={window.start}
                    onBlur={() => {
                      const merged = mergeTimeWindows(activeWindows);
                      if (merged) setActiveWindows(merged);
                    }}
                    onChange={(event) => {
                      setActiveWindows((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index
                            ? { ...item, start: event.target.value }
                            : item,
                        ),
                      );
                      setFormError(null);
                    }}
                  />
                  <span className="text-xs font-medium text-muted-foreground">đến</span>
                  <input
                    className="field"
                    type="time"
                    aria-label={`Giờ kết thúc khung ${index + 1}`}
                    value={window.end}
                    onBlur={() => {
                      const merged = mergeTimeWindows(activeWindows);
                      if (merged) setActiveWindows(merged);
                    }}
                    onChange={(event) => {
                      setActiveWindows((current) =>
                        current.map((item, itemIndex) =>
                          itemIndex === index
                            ? { ...item, end: event.target.value }
                            : item,
                        ),
                      );
                      setFormError(null);
                    }}
                  />
                  <button
                    type="button"
                    className="flex h-10 w-10 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-30"
                    aria-label={`Xóa khung giờ ${index + 1}`}
                    disabled={activeWindows.length === 1}
                    onClick={() => {
                      setActiveWindows((current) =>
                        current.filter((_, itemIndex) => itemIndex !== index),
                      );
                      setFormError(null);
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Các khung giờ chồng nhau hoặc liền nhau sẽ tự động được gộp lại.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
            <div>
              <label htmlFor="mention-delay" className="mb-2 block text-sm font-semibold">
                Khoảng thời gian nhắc
              </label>
              <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-2">
                <div className="relative">
                  <Clock3 className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    id="mention-delay"
                    className="field pl-11"
                    type="number"
                    min={delayUnits[delayUnit].min}
                    max={delayUnits[delayUnit].max}
                    step={delayUnits[delayUnit].step}
                    value={delayValue}
                    onChange={(event) => {
                      setDelayValue(
                        event.target.value === "" ? "" : Number(event.target.value),
                      );
                      setFormError(null);
                    }}
                  />
                </div>
                <select
                  className="field cursor-pointer"
                  value={delayUnit}
                  aria-label="Đơn vị thời gian chờ"
                  onChange={(event) => {
                    setDelayUnit(event.target.value as DelayUnit);
                    setFormError(null);
                  }}
                >
                  {Object.entries(delayUnits).map(([value, unit]) => (
                    <option key={value} value={value}>{unit.label}</option>
                  ))}
                </select>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {delayPresets.map((preset) => {
                  const presetMinutes = toDelayMinutes(preset.value, preset.unit);
                  const active = delayMinutes === presetMinutes;
                  return (
                    <button
                      key={preset.label}
                      type="button"
                      className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${active ? "border-blue-200 bg-blue-50 text-accent" : "border-border bg-white text-muted-foreground hover:bg-muted"}`}
                      onClick={() => {
                        setDelayValue(preset.value);
                        setDelayUnit(preset.unit);
                        setFormError(null);
                      }}
                    >
                      {preset.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {delayMinutes >= 1 && delayMinutes <= 10_080
                  ? `Bot sẽ tag lại sau ${formatDelay(delayMinutes)}.`
                  : "Chọn thời gian từ 1 phút đến 7 ngày."}
              </p>
            </div>

            <div>
              <span className="mb-2 block text-sm font-semibold">Trạng thái</span>
              <button
                type="button"
                role="switch"
                aria-checked={enabled}
                onClick={() => setEnabled((current) => !current)}
                className="flex min-h-12 w-full items-center justify-between rounded-xl border border-border bg-white px-4"
              >
                <span className="text-sm">{enabled ? "Đang bật" : "Đang tắt"}</span>
                <span
                  className={`relative h-6 w-11 rounded-full transition ${enabled ? "bg-accent" : "bg-slate-300"}`}
                >
                  <span
                    className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition ${enabled ? "left-6" : "left-1"}`}
                  />
                </span>
              </button>
            </div>
          </div>

          {automation.data && automation.data.pending_followups > 0 && (
            <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
              Có {automation.data.pending_followups} vòng nhắc đang hoạt động. Nếu thay
              đổi cấu hình, các vòng này sẽ được hủy.
            </p>
          )}
          {formError && (
            <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {formError}
            </p>
          )}

          {!canEdit && (
            <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              Vai trò của bạn chỉ được xem cấu hình tag tên tự động.
            </p>
          )}
          <div className="flex justify-end gap-3 border-t border-border pt-5">
            <Button variant="ghost" onClick={onClose}>Đóng</Button>
            <Button loading={save.isPending} disabled={!canEdit} onClick={() => save.mutate()}>
              Lưu cấu hình
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Avatar({ member, small = false }: { member: GroupMember; small?: boolean }) {
  return (
    <span
      className={`flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-blue-100 to-indigo-100 font-semibold text-accent ${small ? "h-5 w-5 text-[8px]" : "h-9 w-9 text-xs"}`}
    >
      {member.avatar_url ? (
        <img src={member.avatar_url} alt="" className="h-full w-full object-cover" />
      ) : member.display_name ? (
        initials(member.display_name)
      ) : (
        <UserRound className="h-4 w-4" />
      )}
    </span>
  );
}

function normalize(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/đ/g, "d")
    .replace(/Đ/g, "D")
    .toLowerCase()
    .trim();
}

function toDelayMinutes(value: number | "", unit: DelayUnit) {
  if (value === "" || !Number.isFinite(value)) return Number.NaN;
  return Math.round(value * delayUnits[unit].multiplier);
}

function splitDelay(minutes: number): { value: number; unit: DelayUnit } {
  if (minutes >= 1_440 && minutes % 1_440 === 0) {
    return { value: minutes / 1_440, unit: "days" };
  }
  if (minutes >= 60 && minutes % 60 === 0) {
    return { value: minutes / 60, unit: "hours" };
  }
  return { value: minutes, unit: "minutes" };
}

function formatDelay(minutes: number) {
  if (minutes % 1_440 === 0) return `${minutes / 1_440} ngày`;
  if (minutes % 60 === 0) return `${minutes / 60} giờ`;
  if (minutes > 60) {
    const hours = Math.floor(minutes / 60);
    return `${hours} giờ ${minutes % 60} phút`;
  }
  return `${minutes} phút`;
}

function mergeTimeWindows(windows: MentionTimeWindow[]) {
  if (
    windows.length === 0 ||
    windows.some(
      (window) =>
        !/^([01]\d|2[0-3]):[0-5]\d$/.test(window.start) ||
        !/^([01]\d|2[0-3]):[0-5]\d$/.test(window.end) ||
        window.start >= window.end,
    )
  ) {
    return null;
  }
  const sorted = [...windows].sort((left, right) =>
    left.start.localeCompare(right.start),
  );
  return sorted.reduce<MentionTimeWindow[]>((merged, window) => {
    const previous = merged[merged.length - 1];
    if (previous && window.start <= previous.end) {
      previous.end = previous.end > window.end ? previous.end : window.end;
    } else {
      merged.push({ ...window });
    }
    return merged;
  }, []);
}
