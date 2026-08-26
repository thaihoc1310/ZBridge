import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, ChevronDown, ChevronLeft, ChevronRight, RefreshCw, Search, ScrollText, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, queryString } from "../api/client";
import type { DeliveryLogList, DeliveryStatus, ModelCallLogList, ModelCallStatus } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/Button";
import { StatusBadge } from "../components/ui/StatusBadge";
import { ModelCallLogTable } from "../features/activity/ModelCallLogTable";
import { formatDate } from "../lib/format";
import { PERMISSIONS } from "../lib/permissions";
import { usePermissions } from "../lib/session";

type ActivityView = "delivery" | "model";

function ActivityTitle({ view }: { view: ActivityView }) {
  return <h1 className="font-display text-3xl leading-tight text-foreground sm:text-4xl">Nhật ký <span className="gradient-text">{view === "model" ? "gọi model" : "vận hành"}</span></h1>;
}

function ActivityHeading({ view, views, onChange }: { view: ActivityView; views: ActivityView[]; onChange: (view: ActivityView) => void }) {
  const picker = useRef<HTMLDetailsElement>(null);
  const choose = (next: ActivityView) => {
    onChange(next);
    picker.current?.removeAttribute("open");
  };
  if (views.length === 1) return <div className="mt-4"><ActivityTitle view={view} /></div>;
  return <details ref={picker} className="group relative mt-4 w-fit">
    <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
      <ActivityTitle view={view} />
      <ChevronDown className="mt-1 h-5 w-5 text-muted-foreground transition group-open:rotate-180 group-hover:text-accent" />
    </summary>
    <div className="absolute left-0 top-full z-30 mt-3 w-72 overflow-hidden rounded-2xl border border-border bg-card p-2 shadow-2xl">
      {views.includes("delivery") && <button type="button" onClick={() => choose("delivery")} className="flex min-h-12 w-full items-center justify-between rounded-xl px-3 text-left text-sm transition hover:bg-muted"><span><strong className="block">Nhật ký vận hành</strong><span className="mt-0.5 block text-[11px] text-muted-foreground">Các lượt bot gửi Zalo</span></span>{view === "delivery" && <Check className="h-4 w-4 text-accent" />}</button>}
      {views.includes("model") && <button type="button" onClick={() => choose("model")} className="flex min-h-12 w-full items-center justify-between rounded-xl px-3 text-left text-sm transition hover:bg-muted"><span><strong className="block">Nhật ký gọi model</strong><span className="mt-0.5 block text-[11px] text-muted-foreground">Request, response và kết quả gửi</span></span>{view === "model" && <Check className="h-4 w-4 text-accent" />}</button>}
    </div>
  </details>;
}

export function ActivityPage() {
  const { can } = usePermissions();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(1);
  const canReadDelivery = can(PERMISSIONS.activityRead);
  const canReadModel = can(PERMISSIONS.modelActivityRead);
  const views: ActivityView[] = [
    ...(canReadDelivery ? ["delivery" as const] : []),
    ...(canReadModel ? ["model" as const] : []),
  ];
  const requestedView: ActivityView = params.get("view") === "model" ? "model" : "delivery";
  const view: ActivityView = views.includes(requestedView) ? requestedView : views[0];
  const rawStatus = params.get("status") ?? "";
  const deliveryStatus = (["SENT", "FAILED"] as string[]).includes(rawStatus) ? rawStatus as DeliveryStatus : "";
  const modelStatus = (["PROCESSING", "SUCCEEDED", "FAILED"] as string[]).includes(rawStatus) ? rawStatus as ModelCallStatus : "";
  const today = view === "delivery" && params.get("date") === "today";

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => setPage(1), [debouncedSearch, rawStatus, today, view]);

  const delivery = useQuery({
    queryKey: ["activity", debouncedSearch, deliveryStatus, today, page],
    queryFn: () => api<DeliveryLogList>(`/activity${queryString({ search: debouncedSearch, status: deliveryStatus, today: today ? 1 : undefined, page, limit: 25 })}`),
    placeholderData: (previousData) => previousData,
    enabled: view === "delivery" && canReadDelivery,
  });
  const modelCalls = useQuery({
    queryKey: ["model-call-activity", debouncedSearch, modelStatus, page],
    queryFn: () => api<ModelCallLogList>(`/activity/model-calls${queryString({ search: debouncedSearch, status: modelStatus, page, limit: 25 })}`),
    placeholderData: (previousData) => previousData,
    refetchInterval: 30_000,
    enabled: view === "model" && canReadModel,
  });

  const changeView = (next: ActivityView) => {
    setSearch("");
    setParams(next === "model" ? { view: "model" } : {});
  };
  const setDeliveryFilter = (status: string, nextToday: boolean) => {
    const next = new URLSearchParams();
    if (status) next.set("status", status);
    if (nextToday) next.set("date", "today");
    setParams(next);
  };
  const setModelFilter = (status: string) => {
    const next = new URLSearchParams({ view: "model" });
    if (status) next.set("status", status);
    setParams(next);
  };

  return <div className="mx-auto max-w-[1500px]">
    <Link to="/" className="mb-5 inline-flex items-center gap-2 text-sm font-medium text-muted-foreground transition hover:text-accent"><ArrowLeft className="h-4 w-4" />Về tổng quan</Link>
    <PageHeader eyebrow="Operations log" heading={<ActivityHeading view={view} views={views} onChange={changeView} />} description={view === "model" ? "Theo dõi context gửi tới AI, response phân loại, token và độ trễ của từng lượt gọi. Dữ liệu được giữ 7 ngày." : "Theo dõi lượt bot gửi thành công hoặc thất bại mà không lưu nội dung tin nhắn. Dữ liệu được giữ 7 ngày."} />
    <section className="card overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-border p-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative w-full max-w-xl"><Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><input className="field pl-11" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={view === "model" ? "Tìm khách hàng, model hoặc lỗi..." : "Tìm khách hàng hoặc nguyên nhân lỗi..."} />{search && <button className="absolute right-3 top-1/2 -translate-y-1/2 rounded-lg p-1 text-muted-foreground hover:bg-muted" onClick={() => setSearch("")}><X className="h-4 w-4" /></button>}</div>
        {view === "delivery" ? <div className="flex flex-wrap gap-2"><select className="field min-h-11 w-auto" value={deliveryStatus} onChange={(event) => setDeliveryFilter(event.target.value, today)}><option value="">Mọi trạng thái</option><option value="SENT">Thành công</option><option value="FAILED">Thất bại</option></select><label className="flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-border bg-card px-4 text-sm"><input type="checkbox" checked={today} onChange={(event) => setDeliveryFilter(deliveryStatus, event.target.checked)} className="h-4 w-4 accent-accent" />Chỉ hôm nay</label></div> : <select className="field min-h-11 w-auto" value={modelStatus} onChange={(event) => setModelFilter(event.target.value)}><option value="">Mọi trạng thái</option><option value="SUCCEEDED">Thành công</option><option value="FAILED">Lỗi model</option><option value="PROCESSING">Đang gọi</option></select>}
      </div>
      {view === "model" ? <ModelCallLogTable data={modelCalls.data} loading={modelCalls.isLoading} page={page} onPageChange={setPage} /> : <DeliveryLogTable data={delivery.data} loading={delivery.isLoading} page={page} onPageChange={setPage} />}
    </section>
  </div>;
}

function DeliveryLogTable({ data, loading, page, onPageChange }: { data?: DeliveryLogList; loading: boolean; page: number; onPageChange: (page: number) => void }) {
  return <>
    <div className="app-scrollbar overflow-x-auto">
      <table className="w-full min-w-[900px] border-collapse text-left">
        <thead><tr className="border-b border-border bg-muted/50 font-mono text-[10px] uppercase tracking-wider text-muted-foreground"><th className="px-6 py-4 font-medium">Thời gian</th><th className="px-5 py-4 font-medium">Khách hàng</th><th className="px-5 py-4 font-medium">Tác vụ</th><th className="px-5 py-4 font-medium">Trạng thái</th><th className="px-5 py-4 font-medium">Chi tiết</th></tr></thead>
        <tbody>{loading && <tr><td colSpan={5} className="px-6 py-14 text-center text-sm text-muted-foreground"><RefreshCw className="mx-auto mb-3 h-5 w-5 animate-spin text-accent" />Đang tải nhật ký...</td></tr>}{data?.items.map((entry) => <tr key={entry.id} className="border-b border-border last:border-0 hover:bg-accent-soft/50"><td className="whitespace-nowrap px-6 py-4 text-sm text-muted-foreground">{formatDate(entry.created_at)}</td><td className="px-5 py-4"><Link to={`/customers/${entry.customer_id}`} className="font-semibold hover:text-accent">{entry.customer_name}</Link></td><td className="px-5 py-4 text-sm">{deliveryTypeLabel(entry.type)}</td><td className="px-5 py-4"><StatusBadge status={entry.status} /></td><td className="max-w-md px-5 py-4 text-xs leading-relaxed text-muted-foreground">{entry.status === "SENT" ? <span className="text-success-fg">Zalo đã xác nhận gửi thành công.</span> : <span className="text-danger-fg"><strong>{entry.error_code || "SEND_FAILED"}</strong>{entry.error_message ? ` · ${entry.error_message}` : ""}</span>}</td></tr>)}</tbody>
      </table>
      {!loading && data?.items.length === 0 && <div className="flex flex-col items-center px-6 py-16 text-center"><span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted"><ScrollText className="h-7 w-7 text-muted-foreground" /></span><h3 className="mt-5 font-semibold">Chưa có lượt gửi phù hợp</h3><p className="mt-1 text-sm text-muted-foreground">Nhật ký sẽ xuất hiện khi bot thực hiện gửi tin nhắn hoặc tag tên.</p></div>}
    </div>
    <footer className="flex flex-col gap-3 border-t border-border px-5 py-4 text-sm sm:flex-row sm:items-center sm:justify-between"><p className="text-muted-foreground"><strong className="text-foreground">{data?.total ?? 0}</strong> lượt gửi · giữ 7 ngày</p><div className="flex items-center gap-2"><Button variant="secondary" className="h-10 min-h-10 w-10 p-0" disabled={page <= 1} onClick={() => onPageChange(page - 1)}><ChevronLeft className="h-4 w-4" /></Button><span className="min-w-24 text-center text-xs">Trang {page} / {data?.pages ?? 1}</span><Button variant="secondary" className="h-10 min-h-10 w-10 p-0" disabled={page >= (data?.pages ?? 1)} onClick={() => onPageChange(page + 1)}><ChevronRight className="h-4 w-4" /></Button></div></footer>
  </>;
}

function deliveryTypeLabel(type: DeliveryLogList["items"][number]["type"]) {
  if (type === "MENTION_AUTOMATION") return "Tag tên tự động";
  if (type === "DEBT_REMINDER_IMAGE") return "Nhắc công nợ · Ảnh";
  if (type === "DEBT_REMINDER_LINK") return "Nhắc công nợ · Link";
  if (type === "DEBT_REMINDER_MESSAGE") return "Nhắc công nợ · Nội dung";
  return "Gửi tin nhắn";
}
