import { Bot, CheckCircle2, ChevronLeft, ChevronRight, Clock3, MessageSquareOff, Send } from "lucide-react";
import { Link } from "react-router-dom";
import type { ModelCallLog, ModelCallLogList } from "../../api/types";
import { formatDate } from "../../lib/format";
import { Button } from "../../components/ui/Button";
import { StatusBadge } from "../../components/ui/StatusBadge";

type Props = {
  data?: ModelCallLogList;
  loading: boolean;
  page: number;
  onPageChange: (page: number) => void;
};

type ConversationMessage = {
  message_id?: string;
  sent_at?: string;
  sender?: string;
  text?: string;
};

type Decision = {
  target_display_name?: string;
  target_user_id?: string;
  classification?: string;
  confidence?: number;
  reason_code?: string;
  skipped?: boolean;
};

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    : [];
}

function conversation(entry: ModelCallLog): ConversationMessage[] {
  return records(entry.request_payload.conversation) as ConversationMessage[];
}

function decisions(entry: ModelCallLog): Decision[] {
  return records(entry.response_payload?.decisions) as Decision[];
}

function outcomeLabel(outcome: string | null) {
  const labels: Record<string, string> = {
    SCHEDULED: "Model yêu cầu tag",
    SKIPPED: "Model quyết định bỏ qua",
    REPOINTED: "Chuyển sang tin mới",
    CLAIM_LOST: "Đã phản hồi khi AI chạy",
    SAFE_FALLBACK_TAG: "Lỗi AI · vẫn tag an toàn",
    SAFE_FALLBACK_SKIP: "Lỗi AI · bỏ qua báo giá",
  };
  return outcome ? labels[outcome] ?? outcome : "Đang xử lý";
}

function SendOutcome({ entry }: { entry: ModelCallLog }) {
  if (entry.message_sent) return <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700"><Send className="h-3 w-3" />Đã gửi Zalo</span>;
  if (entry.scheduled_for_send) return <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700"><Clock3 className="h-3 w-3" />Chưa gửi Zalo</span>;
  return <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600"><MessageSquareOff className="h-3 w-3" />Không gửi</span>;
}

export function ModelCallLogTable({ data, loading, page, onPageChange }: Props) {
  return <>
    <div className="app-scrollbar overflow-x-auto">
      <table className="w-full min-w-[1180px] border-collapse text-left">
        <thead><tr className="border-b border-border bg-muted/50 font-mono text-[10px] uppercase tracking-wider text-muted-foreground"><th className="px-5 py-4 font-medium">Thời gian</th><th className="px-5 py-4 font-medium">Khách hàng</th><th className="px-5 py-4 font-medium">Model</th><th className="px-5 py-4 font-medium">Text / context gửi đi</th><th className="px-5 py-4 font-medium">Response</th><th className="px-5 py-4 font-medium">Kết quả</th></tr></thead>
        <tbody>
          {loading && <tr><td colSpan={6} className="px-6 py-14 text-center text-sm text-muted-foreground"><Bot className="mx-auto mb-3 h-5 w-5 animate-pulse text-accent" />Đang tải nhật ký model...</td></tr>}
          {data?.items.map((entry) => {
            const messages = conversation(entry);
            const modelDecisions = decisions(entry);
            const currentText = messages[messages.length - 1]?.text || "Không có text";
            return <tr key={entry.id} className="border-b border-border align-top last:border-0 hover:bg-blue-50/30">
              <td className="whitespace-nowrap px-5 py-4 text-xs text-muted-foreground">{formatDate(entry.created_at)}<span className="mt-1 block font-mono text-[10px]">{entry.latency_ms == null ? "—" : `${entry.latency_ms} ms`}</span></td>
              <td className="max-w-48 px-5 py-4">{entry.customer_id ? <Link to={`/customers/${entry.customer_id}`} className="text-sm font-semibold hover:text-accent">{entry.customer_name}</Link> : <span className="text-sm font-semibold">{entry.customer_name}</span>}<span className="mt-1 block text-[10px] uppercase tracking-wide text-muted-foreground">{entry.trigger === "PRICE_INQUIRY" ? "Hỏi báo giá" : "Tag tên"}</span></td>
              <td className="max-w-48 px-5 py-4"><p className="truncate text-xs font-semibold" title={entry.model}>{entry.model}</p><p className="mt-1 font-mono text-[10px] text-muted-foreground">{entry.provider}</p><p className="mt-2 text-[10px] text-muted-foreground">{entry.input_tokens ?? "—"} in · {entry.output_tokens ?? "—"} out</p></td>
              <td className="max-w-md px-5 py-4">
                <details className="group"><summary className="cursor-pointer list-none text-xs font-medium leading-relaxed text-foreground hover:text-accent"><span className="line-clamp-2">{currentText}</span><span className="mt-1 block text-[10px] text-muted-foreground group-open:hidden">Mở {messages.length} tin context</span></summary><div className="mt-3 max-h-72 space-y-2 overflow-y-auto rounded-xl bg-slate-950 p-3 text-[11px] text-slate-200">{messages.map((message, index) => <div key={`${message.message_id}-${index}`} className="border-b border-white/10 pb-2 last:border-0 last:pb-0"><span className="font-mono text-blue-300">{message.sender || "P?"}</span><p className="mt-1 whitespace-pre-wrap break-words leading-relaxed">{message.text || "(nội dung rỗng)"}</p></div>)}</div></details>
              </td>
              <td className="max-w-sm px-5 py-4">
                {entry.status === "FAILED" ? <div className="text-xs leading-relaxed text-red-700"><strong>{entry.error_type || "MODEL_ERROR"}</strong>{entry.error_message && <p className="mt-1 line-clamp-3">{entry.error_message}</p>}</div> : modelDecisions.length ? <details className="group"><summary className="cursor-pointer list-none text-xs font-medium hover:text-accent">{modelDecisions.map((decision) => decision.classification).join(", ")}<span className="mt-1 block text-[10px] text-muted-foreground group-open:hidden">Mở chi tiết response</span></summary><div className="mt-2 space-y-2">{modelDecisions.map((decision, index) => <div key={`${decision.target_user_id}-${index}`} className="rounded-lg bg-muted/70 p-2 text-[10px]"><div className="flex items-center justify-between gap-2"><strong>{decision.target_display_name || `Target ${index + 1}`}</strong><span className={decision.skipped ? "text-slate-500" : "text-emerald-700"}>{decision.skipped ? "Bỏ qua" : "Giữ tag"}</span></div><p className="mt-1 font-mono text-muted-foreground">{decision.classification} · {typeof decision.confidence === "number" ? `${Math.round(decision.confidence * 100)}%` : "—"} · {decision.reason_code}</p></div>)}</div></details> : <span className="text-xs text-muted-foreground">{entry.status === "PROCESSING" ? "Đang chờ model phản hồi..." : "Không có response"}</span>}
              </td>
              <td className="px-5 py-4"><StatusBadge status={entry.status} /><p className="mt-2 max-w-48 text-[11px] leading-relaxed text-muted-foreground">{outcomeLabel(entry.outcome)}</p><div className="mt-2"><SendOutcome entry={entry} /></div>{entry.message_sent_at && <p className="mt-1 text-[10px] text-muted-foreground">{formatDate(entry.message_sent_at)}</p>}</td>
            </tr>;
          })}
        </tbody>
      </table>
      {!loading && data?.items.length === 0 && <div className="flex flex-col items-center px-6 py-16 text-center"><span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted"><CheckCircle2 className="h-7 w-7 text-muted-foreground" /></span><h3 className="mt-5 font-semibold">Chưa có lượt gọi model phù hợp</h3><p className="mt-1 text-sm text-muted-foreground">Nhật ký xuất hiện khi AI phân loại tin tag tên hoặc câu hỏi báo giá.</p></div>}
    </div>
    <footer className="flex flex-col gap-3 border-t border-border px-5 py-4 text-sm sm:flex-row sm:items-center sm:justify-between"><p className="text-muted-foreground"><strong className="text-foreground">{data?.total ?? 0}</strong> lượt gọi model · giữ 7 ngày</p><div className="flex items-center gap-2"><Button variant="secondary" className="h-10 min-h-10 w-10 p-0" disabled={page <= 1} onClick={() => onPageChange(page - 1)}><ChevronLeft className="h-4 w-4" /></Button><span className="min-w-24 text-center text-xs">Trang {page} / {data?.pages ?? 1}</span><Button variant="secondary" className="h-10 min-h-10 w-10 p-0" disabled={page >= (data?.pages ?? 1)} onClick={() => onPageChange(page + 1)}><ChevronRight className="h-4 w-4" /></Button></div></footer>
  </>;
}
