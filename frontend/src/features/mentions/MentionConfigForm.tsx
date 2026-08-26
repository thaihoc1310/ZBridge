import { Check, ChevronDown, Clock3, Plus, Search, Trash2, UserRound, X, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { GroupMember, MentionTarget, MentionTimeWindow } from "../../api/types";
import { initials } from "../../lib/format";

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


export { defaultTimeWindows, delayUnits, delayPresets };
export type { DelayUnit };

type FeatureSectionProps = {
  icon: LucideIcon;
  title: string;
  hint: string;
  enabled: boolean;
  onToggle: () => void;
  disabled: boolean;
  children: ReactNode;
};

function FeatureSection({
  icon: Icon,
  title,
  hint,
  enabled,
  onToggle,
  disabled,
  children,
}: FeatureSectionProps) {
  return (
    <div className="p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft">
          <Icon className="h-4 w-4 text-accent" />
        </span>
        <div className="min-w-0 flex-1">
          <span className="block text-sm font-semibold">{title}</span>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{hint}</p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          aria-label={title}
          disabled={disabled}
          onClick={onToggle}
          className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition disabled:opacity-50 ${enabled ? "bg-accent" : "bg-muted-foreground/40"}`}
        >
          <span
            className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition ${enabled ? "left-6" : "left-1"}`}
          />
        </button>
      </div>
      {enabled && <div className="mt-4">{children}</div>}
    </div>
  );
}

type TargetPickerProps = {
  label: string;
  selected: MentionTarget[];
  onChange: (targets: MentionTarget[]) => void;
  members: GroupMember[];
  loading?: boolean;
  errorMessage?: string | null;
  disabled: boolean;
  onDirty: () => void;
};

function TargetPicker({
  label,
  selected,
  onChange,
  members,
  loading = false,
  errorMessage = null,
  disabled,
  onDirty,
}: TargetPickerProps) {
  const pickerRef = useRef<HTMLDivElement>(null);
  const [search, setSearch] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);

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
  const suggestions = members
    .filter((member) => !selectedIds.has(member.user_id))
    .filter(
      (member) =>
        !normalizedSearch ||
        normalize(member.display_name).includes(normalizedSearch) ||
        member.user_id.toLowerCase().includes(normalizedSearch),
    )
    .slice(0, 50);

  const addMember = (member: GroupMember) => {
    onChange([...selected, member]);
    setSearch("");
    setPickerOpen(true);
    onDirty();
  };

  return (
          <div>
            <div className="mb-2 flex items-center justify-between gap-4">
              <label className="text-sm font-semibold">{label}</label>
              <span className="text-xs text-muted-foreground">Đã chọn {selected.length}</span>
            </div>
            <div ref={pickerRef} className="relative">
              <div
                className="flex min-h-10 flex-wrap items-center gap-2 rounded-xl border border-border bg-card p-1.5 transition focus-within:border-accent focus-within:ring-2 focus-within:ring-accent-soft"
                onClick={() => !disabled && setPickerOpen(true)}
              >
                {selected.map((target) => (
                  <span
                    key={target.user_id}
                    className="inline-flex max-w-full items-center gap-2 rounded-lg bg-accent-soft py-1.5 pl-2 pr-1 text-xs font-medium text-info-fg"
                  >
                    <Avatar member={target} small />
                    <span className="max-w-40 truncate">{target.display_name}</span>
                    <button
                      type="button"
                      disabled={disabled}
                      className="rounded-md p-1 hover:bg-accent/15 disabled:cursor-not-allowed disabled:opacity-40"
                      aria-label={`Bỏ chọn ${target.display_name}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        onChange(
                          selected.filter((item) => item.user_id !== target.user_id),
                        );
                      }}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </span>
                ))}
                <div className="relative min-w-44 flex-1">
                  <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    className="h-8 w-full bg-transparent pl-8 pr-7 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
                    value={search}
                    disabled={disabled}
                    onFocus={() => setPickerOpen(true)}
                    onChange={(event) => {
                      setSearch(event.target.value);
                      setPickerOpen(true);
                    }}
                    placeholder={selected.length ? "Chọn thêm..." : "Tìm và chọn thành viên..."}
                  />
                  <ChevronDown className="absolute right-1 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                </div>
              </div>

              {pickerOpen && (
                <div className="app-scrollbar absolute z-20 mt-2 max-h-64 w-full overflow-auto rounded-xl border border-border bg-card p-1.5 shadow-xl">
                  {loading && (
                    <div className="p-6 text-center text-sm text-muted-foreground">
                      Đang lấy danh sách thành viên từ Zalo...
                    </div>
                  )}
                  {errorMessage && (
                    <div className="p-5 text-center text-sm text-danger-fg">
                      {errorMessage}
                    </div>
                  )}
                  {!loading && !errorMessage && suggestions.length === 0 && (
                    <div className="p-6 text-center text-sm text-muted-foreground">
                      {selected.length === members.length
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
                      <Check className="h-4 w-4 text-muted-foreground" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
  );
}


function Avatar({ member, small = false }: { member: GroupMember; small?: boolean }) {
  return (
    <span
      className={`flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-accent-soft to-accent/20 font-semibold text-accent ${small ? "h-5 w-5 text-[8px]" : "h-9 w-9 text-xs"}`}
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

export { normalize, toDelayMinutes, splitDelay, formatDelay, mergeTimeWindows };
export { FeatureSection, TargetPicker };

/** The active-hours editor, shared so both forms behave identically. */
export function TimeWindowsField({
  windows,
  onChange,
  disabled,
  onDirty,
}: {
  windows: MentionTimeWindow[];
  onChange: (windows: MentionTimeWindow[]) => void;
  disabled: boolean;
  onDirty: () => void;
}) {
  return (
    <div>
      <div className="mb-3 flex items-start justify-between gap-4">
        <div>
          <span className="block text-sm font-semibold">Khung giờ hoạt động</span>
          <p className="mt-1 text-xs text-muted-foreground">
            Bot chỉ gửi tag trong các khung giờ này, theo giờ Việt Nam (UTC+7).
          </p>
        </div>
        <button
          type="button"
          disabled={disabled || windows.length >= 24}
          onClick={() => {
            onChange([...windows, { start: "", end: "" }]);
            onDirty();
          }}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-1 py-1 text-sm font-medium text-muted-foreground transition hover:text-accent disabled:pointer-events-none disabled:opacity-40"
        >
          <Plus className="h-4 w-4" />
          Thêm khung giờ
        </button>
      </div>
      <div className="space-y-2">
        {windows.map((window, index) => (
          <div
            key={index}
            className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_40px] items-center gap-2"
          >
            <input
              className="field"
              type="time"
              disabled={disabled}
              aria-label={`Giờ bắt đầu khung ${index + 1}`}
              value={window.start}
              onBlur={() => {
                const merged = mergeTimeWindows(windows);
                if (merged) onChange(merged);
              }}
              onChange={(event) => {
                onChange(
                  windows.map((item, itemIndex) =>
                    itemIndex === index ? { ...item, start: event.target.value } : item,
                  ),
                );
                onDirty();
              }}
            />
            <span className="text-xs font-medium text-muted-foreground">đến</span>
            <input
              className="field"
              type="time"
              disabled={disabled}
              aria-label={`Giờ kết thúc khung ${index + 1}`}
              value={window.end}
              onBlur={() => {
                const merged = mergeTimeWindows(windows);
                if (merged) onChange(merged);
              }}
              onChange={(event) => {
                onChange(
                  windows.map((item, itemIndex) =>
                    itemIndex === index ? { ...item, end: event.target.value } : item,
                  ),
                );
                onDirty();
              }}
            />
            <button
              type="button"
              className="flex h-10 w-10 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-danger-bg hover:text-danger-fg disabled:cursor-not-allowed disabled:opacity-30"
              aria-label={`Xóa khung giờ ${index + 1}`}
              disabled={disabled || windows.length === 1}
              onClick={() => {
                onChange(windows.filter((_, itemIndex) => itemIndex !== index));
                onDirty();
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
  );
}

/** The reminder interval, with the same presets in both forms. */
export function DelayField({
  value,
  unit,
  onChange,
  disabled,
  onDirty,
  id = "mention-delay",
}: {
  value: number | "";
  unit: DelayUnit;
  onChange: (value: number | "", unit: DelayUnit) => void;
  disabled: boolean;
  onDirty: () => void;
  id?: string;
}) {
  const delayMinutes = toDelayMinutes(value, unit);
  return (
    <div>
      <label htmlFor={id} className="mb-2 block text-sm font-semibold">
        Khoảng thời gian nhắc
      </label>
      <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-2">
        <div className="relative">
          <Clock3 className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            id={id}
            className="field pl-11"
            type="number"
            disabled={disabled}
            min={delayUnits[unit].min}
            max={delayUnits[unit].max}
            step={delayUnits[unit].step}
            value={value}
            onChange={(event) => {
              onChange(event.target.value === "" ? "" : Number(event.target.value), unit);
              onDirty();
            }}
          />
        </div>
        <select
          className="field cursor-pointer"
          value={unit}
          disabled={disabled}
          aria-label="Đơn vị thời gian chờ"
          onChange={(event) => {
            onChange(value, event.target.value as DelayUnit);
            onDirty();
          }}
        >
          {Object.entries(delayUnits).map(([option, meta]) => (
            <option key={option} value={option}>{meta.label}</option>
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
              disabled={disabled}
              className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition disabled:opacity-50 ${active ? "border-info-border bg-accent-soft text-accent" : "border-border bg-card text-muted-foreground hover:bg-muted"}`}
              onClick={() => {
                onChange(preset.value, preset.unit);
                onDirty();
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
  );
}
