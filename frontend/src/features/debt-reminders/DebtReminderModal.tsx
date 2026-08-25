import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarClock,
  Check,
  ChevronDown,
  Clock3,
  FileImage,
  Link2,
  MessageSquareText,
  Repeat2,
  UserRound,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import type {
  DebtReminder,
  DebtReminderPart,
  GroupMember,
} from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { formatDate, initials } from "../../lib/format";
import { PERMISSIONS } from "../../lib/permissions";
import { usePermissions } from "../../lib/session";

type Props = {
  customerId: string;
  customerName: string;
  hasDebtFile: boolean;
  hasDebt: boolean;
  open: boolean;
  onClose: () => void;
};

type MentionRange = GroupMember & { start: number; length: number };

const defaultText = "Vui lòng thanh toán công nợ giúp mình nhé.";

function normalize(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function editorFromParts(parts: DebtReminderPart[]) {
  let text = "";
  const mentions: MentionRange[] = [];
  for (const part of parts) {
    if (part.type === "text") {
      text += part.text;
    } else {
      const label = `@${part.display_name}`;
      mentions.push({
        user_id: part.user_id,
        display_name: part.display_name,
        avatar_url: null,
        start: text.length,
        length: label.length,
      });
      text += label;
    }
  }
  return { text: text || defaultText, mentions };
}

function partsFromEditor(text: string, mentions: MentionRange[]): DebtReminderPart[] {
  const validMentions = [...mentions]
    .filter(
      (mention) =>
        text.slice(mention.start, mention.start + mention.length) ===
        `@${mention.display_name}`,
    )
    .sort((left, right) => left.start - right.start);
  const parts: DebtReminderPart[] = [];
  let position = 0;
  for (const mention of validMentions) {
    if (mention.start < position) continue;
    if (mention.start > position) {
      parts.push({ type: "text", text: text.slice(position, mention.start) });
    }
    parts.push({
      type: "mention",
      user_id: mention.user_id,
      display_name: mention.display_name,
    });
    position = mention.start + mention.length;
  }
  if (position < text.length) parts.push({ type: "text", text: text.slice(position) });
  return parts.length ? parts : [{ type: "text", text }];
}

function highlightedContent(text: string, mentions: MentionRange[]) {
  const validMentions = [...mentions]
    .filter(
      (mention) =>
        text.slice(mention.start, mention.start + mention.length) ===
        `@${mention.display_name}`,
    )
    .sort((left, right) => left.start - right.start);
  const content: React.ReactNode[] = [];
  let position = 0;
  for (const mention of validMentions) {
    if (mention.start < position) continue;
    if (mention.start > position) {
      content.push(text.slice(position, mention.start));
    }
    content.push(
      <span
        key={`${mention.user_id}-${mention.start}`}
        className="rounded bg-blue-100 px-0.5 font-medium text-blue-700"
      >
        {text.slice(mention.start, mention.start + mention.length)}
      </span>,
    );
    position = mention.start + mention.length;
  }
  if (position < text.length) content.push(text.slice(position));
  return content;
}

function MemberAvatar({ member }: { member: GroupMember }) {
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-blue-100 to-indigo-100 text-xs font-semibold text-accent">
      {member.avatar_url ? (
        <img
          src={member.avatar_url}
          alt=""
          className="h-full w-full object-cover"
        />
      ) : member.display_name ? (
        initials(member.display_name)
      ) : (
        <UserRound className="h-4 w-4" />
      )}
    </span>
  );
}

function updateMentionRanges(
  before: string,
  after: string,
  mentions: MentionRange[],
): MentionRange[] {
  let prefix = 0;
  while (prefix < before.length && prefix < after.length && before[prefix] === after[prefix]) {
    prefix += 1;
  }
  let suffix = 0;
  while (
    suffix < before.length - prefix &&
    suffix < after.length - prefix &&
    before[before.length - 1 - suffix] === after[after.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  const oldEnd = before.length - suffix;
  const delta = after.length - before.length;
  return mentions.flatMap((mention) => {
    const mentionEnd = mention.start + mention.length;
    if (mentionEnd <= prefix) return [mention];
    if (mention.start >= oldEnd) return [{ ...mention, start: mention.start + delta }];
    return [];
  });
}

function mentionQuery(text: string, cursor: number) {
  const before = text.slice(0, cursor);
  const at = before.lastIndexOf("@");
  if (at < 0) return null;
  const prefix = before.slice(0, at);
  if (prefix && !/[\s(]$/.test(prefix)) return null;
  const query = before.slice(at + 1);
  if (query.includes("\n")) return null;
  return { start: at, query };
}

const runLabels: Record<string, string> = {
  PENDING: "Đang chờ",
  PROCESSING: "Đang xử lý",
  SENT: "Đã gửi",
  FAILED: "Thất bại",
  SKIPPED: "Đã bỏ qua vì hết nợ",
  CANCELLED: "Đã hủy",
};

export function DebtReminderModal({
  customerId,
  customerName,
  hasDebtFile,
  hasDebt,
  open,
  onClose,
}: Props) {
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const canEdit = can(PERMISSIONS.debtReminderUpdate);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);
  const [dayOfMonth, setDayOfMonth] = useState<number | "">(25);
  const [repeatEnabled, setRepeatEnabled] = useState(true);
  const [repeatIntervalDays, setRepeatIntervalDays] = useState<number | "">(3);
  const [sendTime, setSendTime] = useState("09:00");
  const [text, setText] = useState(defaultText);
  const [mentions, setMentions] = useState<MentionRange[]>([]);
  const [cursor, setCursor] = useState(0);
  const [pickerSuppressed, setPickerSuppressed] = useState(false);
  const [explanationOpen, setExplanationOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const reminder = useQuery({
    queryKey: ["debt-reminder", customerId],
    queryFn: () => api<DebtReminder>(`/customers/${customerId}/debt-reminder`),
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
    if (!open || !reminder.data) return;
    const editor = editorFromParts(reminder.data.message_parts);
    setDayOfMonth(reminder.data.day_of_month);
    setRepeatEnabled(reminder.data.repeat_enabled);
    setRepeatIntervalDays(reminder.data.repeat_interval_days);
    setSendTime(reminder.data.send_time);
    setText(editor.text);
    setMentions(editor.mentions);
    setCursor(editor.text.length);
    setPickerSuppressed(false);
    setFormError(null);
  }, [open, reminder.data]);

  const pendingQuery = pickerSuppressed ? null : mentionQuery(text, cursor);
  const activeQuery =
    pendingQuery &&
    !mentions.some(
      (mention) =>
        mention.start === pendingQuery.start &&
        cursor >= mention.start + mention.length,
    )
      ? pendingQuery
      : null;
  const suggestions = useMemo(() => {
    if (!activeQuery) return [];
    const needle = normalize(activeQuery.query.trim());
    return (members.data ?? [])
      .filter(
        (member) =>
          !needle ||
          normalize(member.display_name).includes(needle) ||
          member.user_id.toLowerCase().includes(needle),
      )
      .slice(0, 30);
  }, [activeQuery, members.data]);

  const save = useMutation({
    mutationFn: () => {
      if (!Number.isInteger(dayOfMonth) || Number(dayOfMonth) < 1 || Number(dayOfMonth) > 31) {
        throw new Error("Ngày gửi phải nằm trong khoảng từ 1 đến 31.");
      }
      if (repeatEnabled && (!Number.isInteger(repeatIntervalDays) || Number(repeatIntervalDays) < 1 || Number(repeatIntervalDays) > 31)) {
        throw new Error("Khoảng cách giữa các lần gửi phải từ 1 đến 31 ngày.");
      }
      if (!text.trim()) throw new Error("Nội dung nhắc công nợ không được để trống.");
      if (!hasDebtFile) {
        throw new Error("Hãy thêm file công nợ (Google Sheet) trước khi lưu nhắc công nợ.");
      }
      return api<DebtReminder>(`/customers/${customerId}/debt-reminder`, {
        method: "PUT",
        body: JSON.stringify({
          day_of_month: Number(dayOfMonth),
          repeat_enabled: repeatEnabled,
          repeat_interval_days: Number(repeatIntervalDays),
          send_time: sendTime,
          message_parts: partsFromEditor(text, mentions),
        }),
      });
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["debt-reminder", customerId], data);
      onClose();
    },
    onError: (error) => {
      setFormError(
        error instanceof ApiError || error instanceof Error
          ? error.message
          : "Không thể lưu cấu hình nhắc công nợ.",
      );
    },
  });

  const selectMember = (member: GroupMember) => {
    if (!activeQuery) return;
    const label = `@${member.display_name}`;
    const replacement = `${label} `;
    const nextText =
      text.slice(0, activeQuery.start) + replacement + text.slice(cursor);
    const shifted = updateMentionRanges(text, nextText, mentions);
    const nextCursor = activeQuery.start + replacement.length;
    setText(nextText);
    setMentions([
      ...shifted,
      { ...member, start: activeQuery.start, length: label.length },
    ]);
    setCursor(nextCursor);
    setPickerSuppressed(true);
    setFormError(null);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      className="max-w-2xl"
      title="Nhắc thanh toán công nợ"
      description={`Thiết lập lượt nhắc hàng tháng cho ${customerName}.`}
    >
      {reminder.isLoading ? (
        <div className="flex min-h-72 items-center justify-center text-sm text-muted-foreground">
          Đang tải cấu hình...
        </div>
      ) : reminder.isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">
          Không thể tải cấu hình nhắc công nợ.
        </div>
      ) : (
        <div className="space-y-6">
          <div
            className={`flex w-full items-center justify-between gap-4 rounded-xl border p-4 ${hasDebt && hasDebtFile ? "border-emerald-200 bg-emerald-50" : hasDebt ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50"}`}
          >
            <span>
              <span className="block text-sm font-semibold">Tự động nhắc hàng tháng</span>
              <span className="mt-1 block text-xs text-muted-foreground">
                Trạng thái tự động lấy theo công nợ và file Google Sheet của khách hàng.
              </span>
            </span>
            <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${hasDebt && hasDebtFile ? "bg-emerald-600 text-white" : hasDebt ? "bg-amber-500 text-white" : "bg-slate-200 text-slate-600"}`}>
              {hasDebt && hasDebtFile
                ? "Đang hoạt động · Còn nợ"
                : hasDebt
                  ? "Chưa thể chạy · Thiếu Google Sheet"
                  : "Tạm ngừng · Đã thanh toán"}
            </span>
          </div>

          <div className="rounded-xl border border-blue-100 bg-blue-50/70 p-4">
            <button
              type="button"
              className="flex w-full items-center gap-3 text-left"
              aria-expanded={explanationOpen}
              onClick={() => setExplanationOpen((current) => !current)}
            >
              <Repeat2 className="h-5 w-5 shrink-0 text-accent" />
              <span className="flex-1 text-sm font-semibold text-slate-700">
                Giải thích cách hoạt động
              </span>
              <ChevronDown
                className={`h-4 w-4 text-slate-500 transition ${explanationOpen ? "rotate-180" : ""}`}
              />
            </button>
            {explanationOpen && (
              <div className="mt-3 border-t border-blue-100 pt-3 text-sm leading-relaxed text-slate-700">
                <p>
                  Vào ngày {dayOfMonth || "—"} hàng tháng lúc {sendTime || "—"}, nếu
                  khách hàng còn nợ thì bot sẽ gửi đủ theo thứ tự:
                </p>
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  {[
                    [FileImage, "1. Ảnh tab đầu tiên"],
                    [Link2, "2. Link Google Sheet"],
                    [MessageSquareText, "3. Nội dung nhắc"],
                  ].map(([Icon, label]) => {
                    const StepIcon = Icon as typeof FileImage;
                    return <div key={String(label)} className="flex items-center gap-2 rounded-lg bg-white/80 px-3 py-2 text-xs font-medium text-slate-700"><StepIcon className="h-4 w-4 text-accent" />{String(label)}</div>;
                  })}
                </div>
                <p className="mt-3">
                  {repeatEnabled
                    ? `Sau đó bot tiếp tục gửi lại mỗi ${repeatIntervalDays || "—"} ngày cho đến khi khách hàng được chuyển sang “Đã thanh toán”. `
                    : "Bot không gửi các lượt lặp xen giữa. "}
                  Mốc ngày hàng tháng vẫn luôn hoạt động. Nếu lịch rơi vào mùng 1
                  hoặc ngày rằm âm lịch, lượt nhắc sẽ lùi sang ngày hôm sau. Dịp
                  Tết, bot tạm dừng từ 28 tháng Chạp đến hết mùng 1 tháng Hai và
                  bắt đầu gửi lại từ mùng 2 tháng Hai. Ngày Giỗ Tổ Hùng Vương
                  (10/03 âm lịch) và các ngày 01/01, 30/04, 01/05, 02/09 dương
                  lịch cũng không gửi.
                </p>
              </div>
            )}
          </div>

          {!hasDebtFile && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Khách hàng chưa có file công nợ. Hãy thêm link Google Sheet trước khi lưu.
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-3">
            <label>
              <span className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <CalendarClock className="h-4 w-4 text-accent" />Ngày gửi hàng tháng
              </span>
              <input
                className="field"
                type="number"
                min={1}
                max={31}
                value={dayOfMonth}
                onChange={(event) => {
                  setDayOfMonth(event.target.value === "" ? "" : Number(event.target.value));
                  setFormError(null);
                }}
              />
              <span className="mt-2 block text-xs text-muted-foreground">
                Tháng ngắn sẽ dùng ngày cuối cùng của tháng.
              </span>
            </label>
            <div>
              <span className="mb-2 flex items-center justify-between gap-2 text-sm font-semibold">
                <span className="flex items-center gap-2">
                  <Repeat2 className="h-4 w-4 text-accent" />Lặp lại sau
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={repeatEnabled}
                  aria-label="Bật hoặc tắt nhắc lặp"
                  className={`relative h-6 w-11 rounded-full transition ${repeatEnabled ? "bg-blue-600" : "bg-slate-300"}`}
                  onClick={() => {
                    setRepeatEnabled((current) => !current);
                    setFormError(null);
                  }}
                >
                  <span className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition ${repeatEnabled ? "translate-x-5" : ""}`} />
                </button>
              </span>
              <div className="relative">
                <input
                  className="field pr-14 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
                  type="number"
                  min={1}
                  max={31}
                  disabled={!repeatEnabled}
                  value={repeatIntervalDays}
                  onChange={(event) => {
                    setRepeatIntervalDays(event.target.value === "" ? "" : Number(event.target.value));
                    setFormError(null);
                  }}
                />
                <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
                  ngày
                </span>
              </div>
              <span className="mt-2 block text-xs text-muted-foreground">
                {repeatEnabled ? "Lặp đến khi đã thanh toán." : "Đã tắt các lượt nhắc lặp."}
              </span>
            </div>
            <label>
              <span className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <Clock3 className="h-4 w-4 text-accent" />Giờ gửi
              </span>
              <input
                className="field"
                type="time"
                value={sendTime}
                onChange={(event) => {
                  setSendTime(event.target.value);
                  setFormError(null);
                }}
              />
              <span className="mt-2 block text-xs text-muted-foreground">
                Theo giờ Việt Nam (UTC+7).
              </span>
            </label>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between gap-4">
              <label htmlFor="debt-reminder-message" className="text-sm font-semibold">
                Nội dung nhắc cuối cùng
              </label>
              <span className="text-xs text-muted-foreground">Gõ @ để tag thành viên</span>
            </div>
            <div className="relative">
              <textarea
                ref={textareaRef}
                id="debt-reminder-message"
                className="field app-scrollbar relative z-10 min-h-32 resize-y bg-transparent py-3 leading-relaxed text-transparent caret-slate-900 selection:text-white"
                maxLength={5000}
                value={text}
                onChange={(event) => {
                  const nextText = event.target.value;
                  setMentions((current) => updateMentionRanges(text, nextText, current));
                  setText(nextText);
                  setCursor(event.target.selectionStart);
                  setPickerSuppressed(false);
                  setFormError(null);
                }}
                onSelect={(event) => {
                  setCursor(event.currentTarget.selectionStart);
                  setPickerSuppressed(false);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") setPickerSuppressed(true);
                }}
                onScroll={(event) => {
                  if (!highlightRef.current) return;
                  highlightRef.current.scrollTop = event.currentTarget.scrollTop;
                  highlightRef.current.scrollLeft = event.currentTarget.scrollLeft;
                }}
              />
              <div
                ref={highlightRef}
                aria-hidden="true"
                className="pointer-events-none absolute inset-0 z-0 overflow-hidden whitespace-pre-wrap break-words rounded-xl border border-transparent px-4 py-3 text-sm leading-relaxed text-foreground"
              >
                {highlightedContent(text, mentions)}
                {text.endsWith("\n") ? "\u00a0" : null}
              </div>
              {activeQuery && (
                <div className="app-scrollbar absolute z-20 mt-2 max-h-56 w-full overflow-auto rounded-xl border border-border bg-white p-1.5 shadow-xl">
                  {members.isLoading && (
                    <div className="p-5 text-center text-sm text-muted-foreground">
                      Đang lấy thành viên...
                    </div>
                  )}
                  {members.isError && (
                    <div className="p-5 text-center text-sm text-red-600">
                      Không thể lấy danh sách thành viên.
                    </div>
                  )}
                  {!members.isLoading && !members.isError && suggestions.length === 0 && (
                    <div className="p-5 text-center text-sm text-muted-foreground">
                      Không tìm thấy thành viên phù hợp.
                    </div>
                  )}
                  {suggestions.map((member) => (
                    <button
                      key={member.user_id}
                      type="button"
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-muted"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => selectMember(member)}
                    >
                      <MemberAvatar member={member} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{member.display_name}</span>
                        <span className="block truncate font-mono text-[10px] text-muted-foreground">{member.user_id}</span>
                      </span>
                      <Check className="h-4 w-4 text-slate-300" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {reminder.data?.last_run_status && (
            <div className="rounded-xl border border-border bg-muted/30 p-4 text-xs leading-relaxed">
              <p><strong>Lần chạy gần nhất:</strong> {runLabels[reminder.data.last_run_status] ?? reminder.data.last_run_status}{reminder.data.last_run_at ? ` · ${formatDate(reminder.data.last_run_at)}` : ""}</p>
              {reminder.data.last_error && <p className="mt-2 text-red-700">{reminder.data.last_error}</p>}
            </div>
          )}

          {formError && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              {formError}
            </div>
          )}

          {!canEdit && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              Vai trò của bạn chỉ được xem cấu hình nhắc công nợ.
            </div>
          )}

          <div className="flex justify-end gap-3 border-t border-border pt-5">
            <Button variant="ghost" onClick={onClose}>Đóng</Button>
            <Button loading={save.isPending} disabled={!canEdit} onClick={() => save.mutate()}>Lưu cấu hình</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
