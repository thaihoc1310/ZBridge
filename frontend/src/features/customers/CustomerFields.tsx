import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Clock3, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { Customer } from "../../api/types";
import { cn } from "../../lib/cn";
import { formatDate, fromDatetimeLocalValue, nowDatetimeLocalValue, toDatetimeLocalValue } from "../../lib/format";
import { PERMISSIONS } from "../../lib/permissions";
import { usePermissions } from "../../lib/session";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

export type DebtConfirmation = { customer: Customer; nextValue: boolean };

/** Server-side is authoritative; this keeps the UI from offering dead buttons. */
function useCanUpdateCustomer() {
  const { can } = usePermissions();
  return can(PERMISSIONS.customerUpdate);
}

function ReadOnlyHint() {
  return <p className="mt-4 rounded-xl border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-fg">Vai trò của bạn không có quyền sửa thông tin khách hàng.</p>;
}

export function DebtStatusOptions({ value, onChange, disabled = false }: { value: boolean; onChange: (nextValue: boolean) => void; disabled?: boolean }) {
  return <div role="radiogroup" aria-label="Trạng thái công nợ" className="flex items-center gap-2">
    <button type="button" role="radio" aria-checked={!value} disabled={disabled || !value} onClick={() => onChange(false)} className={cn("whitespace-nowrap rounded-full border px-3 py-2 text-xs font-semibold transition disabled:cursor-default", !value ? "border-emerald-600 bg-emerald-600 text-white shadow-sm" : "border-success-border bg-success-bg text-success-fg hover:border-success-fg/50")}>
      Đã thanh toán
    </button>
    <button type="button" role="radio" aria-checked={value} disabled={disabled || value} onClick={() => onChange(true)} className={cn("whitespace-nowrap rounded-full border px-3 py-2 text-xs font-semibold transition disabled:cursor-default", value ? "border-amber-500 bg-amber-500 text-white shadow-sm" : "border-warning-border bg-warning-bg text-warning-fg hover:border-warning-fg/50")}>
      Còn nợ
    </button>
  </div>;
}

function useCustomerUpdate(customer: Customer | null, onClose: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api<Customer>(`/customers/${customer?.id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["customer", updated.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["customers"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      onClose();
    },
  });
}

function ErrorMessage({ error }: { error: Error | null }) {
  if (!error) return null;
  return <p className="mt-4 rounded-xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg">{error instanceof ApiError ? error.message : "Không thể lưu thay đổi."}</p>;
}

export function NoteEditorModal({ customer, onClose }: { customer: Customer | null; onClose: () => void }) {
  const [note, setNote] = useState("");
  const mutation = useCustomerUpdate(customer, onClose);
  const canEdit = useCanUpdateCustomer();
  useEffect(() => setNote(customer?.note ?? ""), [customer]);
  const initial = customer?.note ?? "";
  const changed = note.trim() !== initial.trim();

  return <Modal open={Boolean(customer)} onClose={onClose} title="Ghi chú khách hàng" description={customer ? `Cập nhật ghi chú dành cho ${customer.name}.` : undefined}>
    <label className="block"><span className="mb-2 block text-sm font-semibold">Nội dung ghi chú</span><textarea autoFocus className="field min-h-56 resize-y py-4 leading-relaxed" maxLength={10000} disabled={!canEdit} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Thêm thông tin cần lưu ý về khách hàng..." /></label>
    <div className="mt-2 flex justify-end text-xs text-muted-foreground"><span>{note.length}/10000</span></div>
    {!canEdit && <ReadOnlyHint />}
    <ErrorMessage error={mutation.error} />
    <div className="mt-6 flex justify-end gap-3"><Button variant="ghost" onClick={onClose}>Đóng</Button><Button loading={mutation.isPending} disabled={!changed || !canEdit} onClick={() => mutation.mutate({ note: note.trim() || null })}><Save className="h-4 w-4" />Lưu ghi chú</Button></div>
  </Modal>;
}

export function DebtFileEditorModal({ customer, onClose }: { customer: Customer | null; onClose: () => void }) {
  const [fileUrl, setFileUrl] = useState("");
  const mutation = useCustomerUpdate(customer, onClose);
  const canEdit = useCanUpdateCustomer();
  useEffect(() => setFileUrl(customer?.debt_file_url ?? ""), [customer]);
  const initialUrl = customer?.debt_file_url ?? "";
  const changed = fileUrl.trim() !== initialUrl;
  // Shape only. Saving asks Google whether it can actually read the sheet, so
  // the button spins while that happens and the server owns the real verdict.
  const looksLikeSheet = /^https:\/\/docs\.google\.com\/spreadsheets\/d\/[A-Za-z0-9_-]+/i.test(
    fileUrl.trim(),
  );
  const empty = fileUrl.trim() === "";

  return <Modal open={Boolean(customer)} onClose={onClose} title="File công nợ" description="Dán link Google Sheet công nợ của khách hàng. Ảnh nhắc nợ lấy từ tab đầu tiên của file này.">
    <label className="block"><span className="mb-2 block text-sm font-semibold">Link Google Sheet</span><input autoFocus className="field" type="url" disabled={!canEdit || mutation.isPending} value={fileUrl} onChange={(event) => setFileUrl(event.target.value)} maxLength={2000} placeholder="https://docs.google.com/spreadsheets/d/..." /></label>
    {!empty && !looksLikeSheet && <p className="mt-3 text-xs text-danger-fg">Phải là link Google Sheet, dạng https://docs.google.com/spreadsheets/d/...</p>}
    {mutation.isPending && !empty && <p className="mt-3 text-xs text-muted-foreground">Đang kiểm tra file trên Google...</p>}
    <p className="mt-3 text-xs text-muted-foreground">Nhớ chia sẻ quyền xem file cho Service Account, nếu không hệ thống sẽ không đọc được.</p>
    {!canEdit && <ReadOnlyHint />}
    <ErrorMessage error={mutation.error} />
    <div className="mt-6 flex justify-end gap-3"><Button variant="ghost" onClick={onClose}>Đóng</Button><Button loading={mutation.isPending} disabled={!changed || !canEdit || (!empty && !looksLikeSheet)} onClick={() => mutation.mutate({ debt_file_url: fileUrl.trim() })}><Save className="h-4 w-4" />{empty ? "Xoá link" : "Kiểm tra và lưu"}</Button></div>
  </Modal>;
}

export function LastPaidEditorModal({ customer, onClose }: { customer: Customer | null; onClose: () => void }) {
  const [value, setValue] = useState("");
  const mutation = useCustomerUpdate(customer, onClose);
  const canEdit = useCanUpdateCustomer();
  useEffect(() => setValue(toDatetimeLocalValue(customer?.last_debt_paid_at)), [customer]);
  const initial = toDatetimeLocalValue(customer?.last_debt_paid_at);
  const changed = value !== initial;
  const previewIso = fromDatetimeLocalValue(value);

  return (
    <Modal
      open={Boolean(customer)}
      onClose={onClose}
      className="max-w-md"
      title="Trả nợ gần nhất"
      description={customer ? `Cập nhật thời điểm thanh toán gần nhất của ${customer.name}.` : undefined}
    >
      <label className="block">
        <span className="mb-2 block text-sm font-semibold">Thời điểm</span>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <input
            autoFocus
            className="field min-h-11 flex-1"
            type="datetime-local"
            step={60}
            disabled={!canEdit || mutation.isPending}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
          <Button
            type="button"
            variant="secondary"
            className="shrink-0"
            disabled={!canEdit || mutation.isPending}
            onClick={() => setValue(nowDatetimeLocalValue())}
          >
            <Clock3 className="h-4 w-4" />
            Bây giờ
          </Button>
        </div>
      </label>
      <p className="mt-3 text-sm text-muted-foreground">
        {previewIso ? <span className="font-medium text-foreground">{formatDate(previewIso)}</span> : "Để trống rồi lưu nếu muốn xóa ngày."}
      </p>
      {!canEdit && <ReadOnlyHint />}
      <ErrorMessage error={mutation.error} />
      <div className="mt-6 flex justify-end gap-3">
        <Button variant="ghost" onClick={onClose}>Hủy</Button>
        <Button
          loading={mutation.isPending}
          disabled={!changed || !canEdit}
          onClick={() => mutation.mutate({ last_debt_paid_at: fromDatetimeLocalValue(value) })}
        >
          <Save className="h-4 w-4" />
          Lưu
        </Button>
      </div>
    </Modal>
  );
}

export function DebtConfirmModal({ confirmation, onClose }: { confirmation: DebtConfirmation | null; onClose: () => void }) {
  const customer = confirmation?.customer ?? null;
  const mutation = useCustomerUpdate(customer, onClose);
  const canEdit = useCanUpdateCustomer();
  const markingAsPaid = confirmation?.nextValue === false;
  return <Modal open={Boolean(confirmation)} onClose={onClose} className="max-w-md" title={markingAsPaid ? "Xác nhận đã thanh toán" : "Xác nhận còn nợ"} description={markingAsPaid ? "Thời điểm xác nhận sẽ được lưu làm ngày trả nợ gần nhất." : "Khách hàng sẽ được đánh dấu là đang còn nợ."}>
    <p className="text-sm leading-relaxed text-muted-foreground">Áp dụng thay đổi cho <strong className="text-foreground">{customer?.name}</strong>?</p>
    {!canEdit && <ReadOnlyHint />}
    <ErrorMessage error={mutation.error} />
    <div className="mt-7 flex justify-center gap-3"><Button variant="ghost" onClick={onClose}>Hủy</Button><Button loading={mutation.isPending} disabled={!canEdit} onClick={() => confirmation && mutation.mutate({ has_debt: confirmation.nextValue })}>Xác nhận</Button></div>
  </Modal>;
}
