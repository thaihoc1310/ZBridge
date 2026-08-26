import { useState, type ReactNode, type ToggleEvent } from "react";
import { Bot, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
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

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "";
  }
}

const JSON_TOKEN =
  /("(?:\\u[0-9a-fA-F]{4}|\\[^u]|[^"\\])*")(\s*:)?|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\b(?:true|false|null)\b|[{}[\],]/g;

function highlightJson(source: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let index = 0;
  for (const match of source.matchAll(JSON_TOKEN)) {
    const start = match.index ?? 0;
    if (start > last) nodes.push(source.slice(last, start));
    const [token, stringLiteral, keyColon] = match;
    if (stringLiteral !== undefined) {
      nodes.push(
        <span key={index++} className={keyColon !== undefined ? "text-sky-300" : "text-emerald-300"}>
          {stringLiteral}
        </span>,
      );
      if (keyColon) {
        nodes.push(
          <span key={index++} className="text-slate-500">
            {keyColon}
          </span>,
        );
      }
    } else if (token === "true" || token === "false") {
      nodes.push(
        <span key={index++} className="text-violet-300">
          {token}
        </span>,
      );
    } else if (token === "null" || token === "{" || token === "}" || token === "[" || token === "]" || token === ",") {
      nodes.push(
        <span key={index++} className="text-slate-500">
          {token}
        </span>,
      );
    } else {
      nodes.push(
        <span key={index++} className="text-amber-300">
          {token}
        </span>,
      );
    }
    last = start + token.length;
  }
  if (last < source.length) nodes.push(source.slice(last));
  return nodes;
}

function RequestPayloadCell({
  payload,
  preview,
  messageCount,
}: {
  payload: Record<string, unknown>;
  preview: string;
  messageCount: number;
}) {
  const [open, setOpen] = useState(false);
  const source = open ? prettyJson(payload) : "";
  return (
    <td className="min-w-0 px-5 py-4">
      <details className="group min-w-0 w-full" onToggle={(event: ToggleEvent<HTMLDetailsElement>) => setOpen(event.currentTarget.open)}>
        <summary className="flex cursor-pointer list-none items-start gap-1.5 text-xs font-medium leading-relaxed text-foreground hover:text-accent [&::-webkit-details-marker]:hidden">
          <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground transition group-open:rotate-180" />
          <span className="min-w-0 flex-1">
            <span className="line-clamp-2 break-words">{preview}</span>
            <span className="mt-1 block text-[10px] font-normal text-muted-foreground group-open:hidden">
              Mở JSON · {messageCount} tin context
            </span>
          </span>
        </summary>
        {open && (
          <pre className="app-scrollbar app-scrollbar-dark mt-3 box-border max-h-72 w-full min-w-0 overflow-y-auto overflow-x-hidden whitespace-pre-wrap break-all rounded-xl border border-white/10 bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-slate-300">
            {source ? highlightJson(source) : "Không có JSON"}
          </pre>
        )}
      </details>
    </td>
  );
}

function FinalTagDecision({ decision, showTarget }: { decision: Decision; showTarget: boolean }) {
  if (typeof decision.skipped !== "boolean") return null;
  const label = decision.target_display_name || "Target";
  return <span className={`inline-flex max-w-full items-center rounded-full px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wide ${decision.skipped ? "bg-slate-100 text-slate-600" : "bg-emerald-50 text-emerald-700"}`} title={showTarget ? label : undefined}>
    <span className="truncate">{showTarget ? `${label} · ` : ""}{decision.skipped ? "Không giữ tag" : "Giữ tag"}</span>
  </span>;
}

function FinalTagDecisions({ entry, decisions: items }: { entry: ModelCallLog; decisions: Decision[] }) {
  const decided = items.filter((decision) => typeof decision.skipped === "boolean");
  if (decided.length) return <div className="mt-2 flex max-w-56 flex-col items-start gap-1.5">{decided.map((decision, index) => <FinalTagDecision key={`${decision.target_user_id}-${index}`} decision={decision} showTarget={decided.length > 1} />)}</div>;
  if (entry.outcome === "SAFE_FALLBACK_TAG" || entry.outcome === "SAFE_FALLBACK_SKIP") {
    return <div className="mt-2"><FinalTagDecision decision={{ skipped: entry.outcome === "SAFE_FALLBACK_SKIP" }} showTarget={false} /></div>;
  }
  return null;
}

export function ModelCallLogTable({ data, loading, page, onPageChange }: Props) {
  return <>
    <div className="app-scrollbar overflow-x-auto">
      <table className="w-full min-w-[1180px] table-fixed border-collapse text-left">
        <thead>
          <tr className="border-b border-border bg-muted/50 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            <th className="w-[9.5rem] px-5 py-4 font-medium">Thời gian</th>
            <th className="w-[10rem] px-5 py-4 font-medium">Khách hàng</th>
            <th className="w-[9.5rem] px-5 py-4 font-medium">Model</th>
            <th className="px-5 py-4 font-medium">Text / context gửi đi</th>
            <th className="w-[13rem] px-5 py-4 font-medium">Response</th>
            <th className="w-[8.5rem] px-5 py-4 font-medium">Kết quả</th>
          </tr>
        </thead>
        <tbody>
          {loading && <tr><td colSpan={6} className="px-6 py-14 text-center text-sm text-muted-foreground"><Bot className="mx-auto mb-3 h-5 w-5 animate-pulse text-accent" />Đang tải nhật ký model...</td></tr>}
          {data?.items.map((entry) => {
            const messages = conversation(entry);
            const modelDecisions = decisions(entry);
            const currentMessageId = entry.request_payload.current_message_id;
            const currentText = messages.find((message) => message.message_id === currentMessageId)?.text
              || messages[messages.length - 1]?.text
              || "Không có text";
            return <tr key={entry.id} className="border-b border-border align-top last:border-0 hover:bg-blue-50/30">
              <td className="px-5 py-4 text-xs text-muted-foreground">{formatDate(entry.created_at)}<span className="mt-1 block font-mono text-[10px]">{entry.latency_ms == null ? "—" : `${entry.latency_ms} ms`}</span></td>
              <td className="min-w-0 px-5 py-4">{entry.customer_id ? <Link to={`/customers/${entry.customer_id}`} className="break-words text-sm font-semibold hover:text-accent">{entry.customer_name}</Link> : <span className="break-words text-sm font-semibold">{entry.customer_name}</span>}<span className="mt-1 block text-[10px] uppercase tracking-wide text-muted-foreground">{entry.trigger === "PRICE_INQUIRY" ? "Hỏi báo giá" : "Tag tên"}</span></td>
              <td className="min-w-0 px-5 py-4"><p className="truncate text-xs font-semibold" title={entry.model}>{entry.model}</p><p className="mt-1 font-mono text-[10px] text-muted-foreground">{entry.provider}</p><p className="mt-2 text-[10px] text-muted-foreground">{entry.input_tokens ?? "—"} in · {entry.output_tokens ?? "—"} out</p></td>
              <RequestPayloadCell payload={entry.request_payload} preview={currentText} messageCount={messages.length} />
              <td className="min-w-0 px-5 py-4">
                {entry.status === "FAILED" ? <div className="text-xs leading-relaxed text-red-700"><strong>{entry.error_type || "MODEL_ERROR"}</strong>{entry.error_message && <p className="mt-1 line-clamp-3 break-words">{entry.error_message}</p>}</div> : modelDecisions.length ? <details className="group min-w-0 w-full"><summary className="cursor-pointer list-none text-xs font-medium hover:text-accent [&::-webkit-details-marker]:hidden">{modelDecisions.map((decision) => decision.classification).join(", ")}<span className="mt-1 block text-[10px] text-muted-foreground group-open:hidden">Mở chi tiết response</span></summary><div className="mt-2 min-w-0 space-y-2">{modelDecisions.map((decision, index) => <div key={`${decision.target_user_id}-${index}`} className="rounded-lg bg-muted/70 p-2 text-[10px]"><strong className="break-words">{decision.target_display_name || `Target ${index + 1}`}</strong><p className="mt-1 break-words font-mono text-muted-foreground">{decision.classification} · {typeof decision.confidence === "number" ? `${Math.round(decision.confidence * 100)}%` : "—"} · {decision.reason_code}</p></div>)}</div></details> : <span className="text-xs text-muted-foreground">{entry.status === "PROCESSING" ? "Đang chờ model phản hồi..." : "Không có response"}</span>}
              </td>
              <td className="px-5 py-4"><StatusBadge status={entry.status} /><FinalTagDecisions entry={entry} decisions={modelDecisions} /></td>
            </tr>;
          })}
        </tbody>
      </table>
      {!loading && data?.items.length === 0 && <div className="flex flex-col items-center px-6 py-16 text-center"><span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted"><CheckCircle2 className="h-7 w-7 text-muted-foreground" /></span><h3 className="mt-5 font-semibold">Chưa có lượt gọi model phù hợp</h3><p className="mt-1 text-sm text-muted-foreground">Nhật ký xuất hiện khi AI phân loại tin tag tên hoặc câu hỏi báo giá.</p></div>}
    </div>
    <footer className="flex flex-col gap-3 border-t border-border px-5 py-4 text-sm sm:flex-row sm:items-center sm:justify-between"><p className="text-muted-foreground"><strong className="text-foreground">{data?.total ?? 0}</strong> lượt gọi model · giữ 7 ngày</p><div className="flex items-center gap-2"><Button variant="secondary" className="h-10 min-h-10 w-10 p-0" disabled={page <= 1} onClick={() => onPageChange(page - 1)}><ChevronLeft className="h-4 w-4" /></Button><span className="min-w-24 text-center text-xs">Trang {page} / {data?.pages ?? 1}</span><Button variant="secondary" className="h-10 min-h-10 w-10 p-0" disabled={page >= (data?.pages ?? 1)} onClick={() => onPageChange(page + 1)}><ChevronRight className="h-4 w-4" /></Button></div></footer>
  </>;
}
