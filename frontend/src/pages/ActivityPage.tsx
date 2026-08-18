import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, RefreshCw, Search, ScrollText, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, queryString } from "../api/client";
import type { DeliveryLogList, DeliveryStatus } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/Button";
import { StatusBadge } from "../components/ui/StatusBadge";
import { formatDate } from "../lib/format";

export function ActivityPage() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(1);
  const status = (params.get("status") as DeliveryStatus | null) ?? "";
  const today = params.get("date") === "today";
  useEffect(() => { const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250); return () => window.clearTimeout(timer); }, [search]);
  useEffect(() => setPage(1), [debouncedSearch, status, today]);
  const activity = useQuery({
    queryKey: ["activity", debouncedSearch, status, today, page],
    queryFn: () => api<DeliveryLogList>(`/activity${queryString({ search: debouncedSearch, status, today: today ? 1 : undefined, page, limit: 25 })}`),
    placeholderData: (previousData) => previousData,
  });
  const setFilter = (nextStatus: string, nextToday: boolean) => {
    const next = new URLSearchParams();
    if (nextStatus) next.set("status", nextStatus);
    if (nextToday) next.set("date", "today");
    setParams(next);
  };

  return <div className="mx-auto max-w-[1500px]">
    <Link to="/" className="mb-5 inline-flex items-center gap-2 text-sm font-medium text-muted-foreground transition hover:text-accent"><ArrowLeft className="h-4 w-4" />Về tổng quan</Link>
    <PageHeader eyebrow="Operations log" title="Nhật ký" highlight="vận hành" description="Theo dõi lượt bot gửi thành công hoặc thất bại mà không lưu nội dung tin nhắn." />
    <section className="card overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-border p-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative w-full max-w-xl"><Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><input className="field pl-11" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tìm khách hàng hoặc nguyên nhân lỗi..." />{search && <button className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1 text-muted-foreground hover:bg-muted" onClick={() => setSearch("")}><X className="h-4 w-4" /></button>}</div>
        <div className="flex flex-wrap gap-2"><select className="field min-h-11 w-auto" value={status} onChange={(event) => setFilter(event.target.value, today)}><option value="">Mọi trạng thái</option><option value="SENT">Thành công</option><option value="FAILED">Thất bại</option></select><label className="flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-border bg-white px-4 text-sm"><input type="checkbox" checked={today} onChange={(event) => setFilter(status, event.target.checked)} className="h-4 w-4 accent-blue-600" />Chỉ hôm nay</label></div>
      </div>
      <div className="app-scrollbar overflow-x-auto">
        <table className="w-full min-w-[900px] border-collapse text-left">
          <thead><tr className="border-b border-border bg-muted/50 font-mono text-[10px] uppercase tracking-wider text-muted-foreground"><th className="px-6 py-4 font-medium">Thời gian</th><th className="px-5 py-4 font-medium">Khách hàng</th><th className="px-5 py-4 font-medium">Tác vụ</th><th className="px-5 py-4 font-medium">Trạng thái</th><th className="px-5 py-4 font-medium">Chi tiết</th></tr></thead>
          <tbody>{activity.isLoading && <tr><td colSpan={5} className="px-6 py-14 text-center text-sm text-muted-foreground"><RefreshCw className="mx-auto mb-3 h-5 w-5 animate-spin text-accent" />Đang tải nhật ký...</td></tr>}{activity.data?.items.map((entry) => <tr key={entry.id} className="border-b border-border last:border-0 hover:bg-blue-50/30"><td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">{formatDate(entry.created_at)}</td><td className="px-5 py-4"><Link to={`/customers/${entry.customer_id}`} className="font-semibold hover:text-accent">{entry.customer_name}</Link></td><td className="px-5 py-4 text-sm">{deliveryTypeLabel(entry.type)}</td><td className="px-5 py-4"><StatusBadge status={entry.status} /></td><td className="max-w-md px-5 py-4 text-xs leading-relaxed text-muted-foreground">{entry.status === "SENT" ? <span className="text-emerald-700">Zalo đã xác nhận gửi thành công.</span> : <span className="text-red-700"><strong>{entry.error_code || "SEND_FAILED"}</strong>{entry.error_message ? ` · ${entry.error_message}` : ""}</span>}</td></tr>)}</tbody>
        </table>
        {!activity.isLoading && activity.data?.items.length === 0 && <div className="flex flex-col items-center px-6 py-16 text-center"><span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted"><ScrollText className="h-7 w-7 text-muted-foreground" /></span><h3 className="mt-5 font-semibold">Chưa có lượt gửi phù hợp</h3><p className="mt-1 text-sm text-muted-foreground">Nhật ký sẽ xuất hiện khi bot thực hiện gửi tin nhắn hoặc tag tên.</p></div>}
      </div>
      <footer className="flex flex-col gap-3 border-t border-border px-5 py-4 text-sm sm:flex-row sm:items-center sm:justify-between"><p className="text-muted-foreground"><strong className="text-foreground">{activity.data?.total ?? 0}</strong> lượt gửi</p><div className="flex items-center gap-2"><Button variant="secondary" className="h-10 min-h-10 w-10 p-0" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ChevronLeft className="h-4 w-4" /></Button><span className="min-w-24 text-center text-xs">Trang {page} / {activity.data?.pages ?? 1}</span><Button variant="secondary" className="h-10 min-h-10 w-10 p-0" disabled={page >= (activity.data?.pages ?? 1)} onClick={() => setPage((value) => value + 1)}><ChevronRight className="h-4 w-4" /></Button></div></footer>
    </section>
  </div>;
}

function deliveryTypeLabel(type: DeliveryLogList["items"][number]["type"]) {
  if (type === "MENTION_AUTOMATION") return "Tag tên tự động";
  if (type === "DEBT_REMINDER_IMAGE") return "Nhắc công nợ · Ảnh";
  if (type === "DEBT_REMINDER_LINK") return "Nhắc công nợ · Link";
  if (type === "DEBT_REMINDER_MESSAGE") return "Nhắc công nợ · Nội dung";
  return "Gửi tin nhắn";
}
