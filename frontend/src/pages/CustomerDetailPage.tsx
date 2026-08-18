import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, AtSign, CalendarDays, CheckCircle2, Clock3, Copy, ExternalLink, FolderOpen, IdCard, MessageSquareText, Pencil, ReceiptText, Send, UsersRound, WalletCards, XCircle, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { Customer, DeliveryLog } from "../api/types";
import { Button } from "../components/ui/Button";
import { LoadingOverlay } from "../components/ui/LoadingOverlay";
import { Modal } from "../components/ui/Modal";
import { StatusBadge } from "../components/ui/StatusBadge";
import { DebtConfirmModal, DebtStatusOptions, FolderEditorModal, NoteEditorModal, type DebtConfirmation } from "../features/customers/CustomerFields";
import { DebtReminderModal } from "../features/debt-reminders/DebtReminderModal";
import { MentionAutomationModal } from "../features/mentions/MentionAutomationModal";
import { formatDate, initials } from "../lib/format";

export function CustomerDetailPage() {
  const { id = "" } = useParams();
  const [composerOpen, setComposerOpen] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [debtReminderOpen, setDebtReminderOpen] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [folderOpen, setFolderOpen] = useState(false);
  const [debtConfirmation, setDebtConfirmation] = useState<DebtConfirmation | null>(null);
  const [content, setContent] = useState("");
  const [result, setResult] = useState<DeliveryLog | ApiError | null>(null);
  const queryClient = useQueryClient();
  const customer = useQuery({ queryKey: ["customer", id], queryFn: () => api<Customer>(`/customers/${id}`), enabled: Boolean(id) });
  const sendMessage = useMutation({
    mutationFn: () => api<DeliveryLog>(`/customers/${id}/messages`, { method: "POST", body: JSON.stringify({ type: "TEXT", content }) }),
    onSuccess: (delivery) => {
      setComposerOpen(false); setResult(delivery); setContent("");
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["activity"] });
    },
    onError: (error) => { setComposerOpen(false); setResult(error instanceof ApiError ? error : new ApiError("UNKNOWN_ERROR", "Không thể gửi tin nhắn.", 500)); },
  });

  if (customer.isLoading) return <div className="mx-auto max-w-7xl"><div className="h-9 w-48 animate-pulse rounded-xl bg-muted" /><div className="mt-8 space-y-6"><div className="h-72 animate-pulse rounded-2xl bg-muted" /><div className="h-48 animate-pulse rounded-2xl bg-muted" /></div></div>;
  if (!customer.data) return <div className="mx-auto max-w-3xl py-24 text-center"><XCircle className="mx-auto h-12 w-12 text-red-500" /><h1 className="mt-5 font-display text-3xl">Không tìm thấy khách hàng</h1><Link to="/customers" className="mt-5 inline-block text-sm font-semibold text-accent">Quay lại danh sách</Link></div>;
  const item = customer.data;

  return <div className="mx-auto max-w-7xl">
    <Link to="/customers" className="mb-5 inline-flex items-center gap-2 text-sm font-medium text-muted-foreground transition hover:text-accent"><ArrowLeft className="h-4 w-4" />Danh sách khách hàng</Link>
    <header className="mb-7 flex items-center gap-4"><span className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-gradient-to-br from-blue-100 to-indigo-100 font-display text-xl text-accent">{item.avatar_url ? <img src={item.avatar_url} alt="" className="h-full w-full object-cover" /> : initials(item.name)}</span><div><div className="mb-2"><StatusBadge status={item.is_available ? "available" : "unavailable"} /></div><h1 className="font-display text-3xl sm:text-4xl">{item.name}</h1></div></header>

    <div className="space-y-6">
      <section className="card p-6 sm:p-8">
        <SectionTitle title="Hồ sơ khách hàng" description="Thông tin nghiệp vụ phục vụ theo dõi và chăm sóc khách hàng." />
        <div className="mt-6 grid gap-5 md:grid-cols-3">
          <div className="group/field relative rounded-xl border border-border bg-muted/30 p-4">
            <p className="flex items-center gap-2 text-xs text-muted-foreground"><FolderOpen className="h-4 w-4 text-accent" />Thư mục</p>
            {item.folder_url ? <a href={item.folder_url} target="_blank" rel="noreferrer" className="mt-3 inline-flex max-w-[calc(100%-2rem)] items-center gap-1.5 font-medium text-accent underline decoration-blue-200 underline-offset-4 hover:decoration-accent"><span className="truncate">Mở thư mục</span><ExternalLink className="h-3.5 w-3.5 shrink-0" /></a> : <button className="mt-3 text-sm italic text-muted-foreground/70 hover:text-accent" onClick={() => setFolderOpen(true)}>+ Thêm thư mục</button>}
            <EditButton label="Sửa thư mục" onClick={() => setFolderOpen(true)} />
          </div>
          <div className="rounded-xl border border-border bg-muted/30 p-4"><p className="mb-3 flex items-center gap-2 text-xs text-muted-foreground"><WalletCards className="h-4 w-4 text-accent" />Công nợ</p><DebtStatusOptions value={item.has_debt} onChange={(nextValue) => setDebtConfirmation({ customer: item, nextValue })} /></div>
          <div className="rounded-xl border border-border bg-muted/30 p-4"><p className="flex items-center gap-2 text-xs text-muted-foreground"><Clock3 className="h-4 w-4 text-accent" />Ngày trả nợ gần nhất</p><p className="mt-3 text-sm font-semibold">{item.last_debt_paid_at ? formatDate(item.last_debt_paid_at) : <span className="font-normal text-muted-foreground">Chưa có</span>}</p></div>
        </div>
        <div className="group/field relative mt-5 border-t border-border pt-5">
          <div className="flex items-center gap-1.5"><p className="text-xs text-muted-foreground">Ghi chú</p><button type="button" onClick={() => setNoteOpen(true)} title="Sửa ghi chú" aria-label="Sửa ghi chú" className="rounded-md p-1 text-slate-300 opacity-0 transition hover:bg-muted hover:text-accent group-hover/field:opacity-100 focus:opacity-100"><Pencil className="h-3 w-3" /></button></div>
          <p className={`mt-2 whitespace-pre-wrap break-words text-sm leading-7 ${item.note ? "text-foreground" : "italic text-muted-foreground/70"}`}>{item.note || "+ Thêm ghi chú cho khách hàng"}</p>
        </div>
      </section>

      <section className="card p-6 sm:p-8">
        <SectionTitle title="Chức năng" description="Các công cụ và tự động hóa dành riêng cho khách hàng này." />
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <CustomerAction icon={MessageSquareText} title="Gửi tin nhắn" description="Soạn và gửi tin nhắn văn bản vào nhóm" onClick={() => setComposerOpen(true)} disabled={!item.is_available} primary />
          <CustomerAction icon={AtSign} title="Tag tên tự động" description="Tag lại người được chọn sau một khoảng chờ" onClick={() => setMentionOpen(true)} disabled={!item.is_available} />
          <CustomerAction icon={ReceiptText} title="Nhắc thanh toán công nợ" description="Gửi ảnh Google Sheet, link và nội dung nhắc hàng tháng" onClick={() => setDebtReminderOpen(true)} disabled={!item.is_available} />
        </div>
        <div className="mt-5 rounded-xl border border-dashed border-border bg-muted/40 px-4 py-3 text-center text-xs text-muted-foreground">Các chức năng mới sẽ được bổ sung tại đây.</div>
      </section>

      <section className="card p-6 sm:p-8">
        <SectionTitle title="Thông tin nhóm" description="Dữ liệu kỹ thuật được cập nhật từ lần đồng bộ Zalo gần nhất." />
        <dl className="mt-6 grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
          <Detail icon={IdCard} label="Zalo Group ID"><div className="flex items-center gap-2"><span className="min-w-0 truncate font-mono text-xs">{item.zalo_group_id}</span><button className="shrink-0 rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-accent" onClick={() => void navigator.clipboard.writeText(item.zalo_group_id)} title="Sao chép"><Copy className="h-3.5 w-3.5" /></button></div></Detail>
          <Detail icon={UsersRound} label="Thành viên"><span className="text-sm font-semibold">{item.member_count.toLocaleString("vi-VN")}</span></Detail>
          <Detail icon={Clock3} label="Đồng bộ gần nhất"><span className="text-sm font-semibold">{formatDate(item.last_synced_at)}</span></Detail>
          <Detail icon={CalendarDays} label="Ngày phát hiện"><span className="text-sm font-semibold">{formatDate(item.created_at)}</span></Detail>
        </dl>
        {!item.is_available && <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-relaxed text-amber-800">Bot hiện không còn ở trong nhóm Zalo này. Thông tin khách hàng vẫn được giữ nguyên.</div>}
      </section>
    </div>

    <Modal open={composerOpen} onClose={() => setComposerOpen(false)} title="Soạn tin nhắn" description={`Gửi tin nhắn văn bản tới ${item.name}.`}>
      <label className="block"><span className="mb-2 block text-sm font-semibold">Nội dung</span><textarea autoFocus className="field min-h-44 resize-y py-4 leading-relaxed" maxLength={5000} placeholder="Nhập nội dung tin nhắn..." value={content} onChange={(event) => setContent(event.target.value)} /></label>
      <div className="mt-2 flex justify-end text-xs text-muted-foreground"><span>{content.length}/5000</span></div>
      <div className="mt-6 flex justify-end gap-3"><Button variant="ghost" onClick={() => setComposerOpen(false)}>Hủy</Button><Button disabled={!content.trim()} onClick={() => sendMessage.mutate()}><Send className="h-4 w-4" />Gửi tin nhắn</Button></div>
    </Modal>

    <ResultModal result={result} onClose={() => setResult(null)} />
    <MentionAutomationModal open={mentionOpen} onClose={() => setMentionOpen(false)} customerId={id} customerName={item.name} />
    <DebtReminderModal open={debtReminderOpen} onClose={() => setDebtReminderOpen(false)} customerId={id} customerName={item.name} hasFolder={Boolean(item.folder_url)} hasDebt={item.has_debt} />
    <NoteEditorModal customer={noteOpen ? item : null} onClose={() => setNoteOpen(false)} />
    <FolderEditorModal customer={folderOpen ? item : null} onClose={() => setFolderOpen(false)} />
    <DebtConfirmModal confirmation={debtConfirmation} onClose={() => setDebtConfirmation(null)} />
    <LoadingOverlay show={sendMessage.isPending} label="Đang gửi tin nhắn tới Zalo..." />
  </div>;
}

function SectionTitle({ title, description }: { title: string; description: string }) {
  return <div className="border-b border-border pb-5"><h2 className="text-base font-semibold">{title}</h2><p className="mt-1 text-xs text-muted-foreground">{description}</p></div>;
}

function EditButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} title={label} aria-label={label} className="absolute right-2 top-2 rounded-lg p-2 text-slate-300 opacity-0 transition hover:bg-white hover:text-accent hover:shadow-sm group-hover/field:opacity-100 focus:opacity-100"><Pencil className="h-3.5 w-3.5" /></button>;
}

function CustomerAction({ icon: Icon, title, description, onClick, disabled, primary = false }: { icon: LucideIcon; title: string; description: string; onClick: () => void; disabled?: boolean; primary?: boolean }) {
  return <button disabled={disabled} onClick={onClick} className={`group flex min-h-20 w-full items-center gap-4 rounded-xl border p-4 text-left transition-all disabled:cursor-not-allowed disabled:opacity-50 ${primary ? "border-blue-100 bg-blue-50/60 hover:border-accent/30 hover:bg-blue-50" : "border-border bg-white hover:border-accent/30 hover:bg-muted/50"}`}><span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${primary ? "bg-gradient-to-br from-accent to-accent-secondary text-white shadow-sm" : "bg-muted text-foreground"}`}><Icon className="h-5 w-5" /></span><span className="min-w-0 flex-1"><span className="block text-sm font-semibold">{title}</span><span className="mt-1 block text-xs leading-relaxed text-muted-foreground">{description}</span></span><ArrowUpRight className="h-4 w-4 shrink-0 text-slate-300 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-accent" /></button>;
}

function Detail({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: React.ReactNode }) {
  return <div className="flex gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-accent"><Icon className="h-4 w-4" /></span><div className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 min-w-0">{children}</dd></div></div>;
}

function ResultModal({ result, onClose }: { result: DeliveryLog | ApiError | null; onClose: () => void }) {
  const success = result && !(result instanceof ApiError) && result.status === "SENT";
  const errorCode = result instanceof ApiError ? result.code : result?.error_code;
  const errorMessage = result instanceof ApiError ? result.message : result?.error_message;
  return <Modal open={Boolean(result)} onClose={onClose} className="max-w-md" title={success ? "Đã gửi thành công" : "Không thể gửi tin nhắn"} description={success ? "Zalo đã xác nhận lượt gửi thành công." : "Lỗi đã được ghi vào nhật ký vận hành để kiểm tra."}>
    <div className={`mx-auto flex h-20 w-20 items-center justify-center rounded-full ${success ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-600"}`}>{success ? <CheckCircle2 className="h-10 w-10" /> : <XCircle className="h-10 w-10" />}</div>
    {!success && <div className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"><p className="font-mono text-xs font-semibold">{errorCode ?? "SEND_FAILED"}</p><p className="mt-2 leading-relaxed">{errorMessage ?? "Zalo không thể gửi tin nhắn."}</p></div>}
    <Button className="mt-7 w-full" variant={success ? "primary" : "secondary"} onClick={onClose}>Đóng</Button>
  </Modal>;
}
