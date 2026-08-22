import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bot, Link2, LogOut, QrCode, RefreshCw, ShieldCheck, UserRound, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../api/client";
import type { Bot as BotType, QRState } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { StatusBadge } from "../components/ui/StatusBadge";
import { formatDate, initials } from "../lib/format";
import { PERMISSIONS } from "../lib/permissions";
import { usePermissions } from "../lib/session";

export function BotPage() {
  const [qrOpen, setQrOpen] = useState(false);
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const canConnect = can(PERMISSIONS.botConnect);
  const canDisconnect = can(PERMISSIONS.botDisconnect);
  const status = useQuery({ queryKey: ["bot"], queryFn: () => api<BotType>("/bot/status"), refetchInterval: 10_000 });
  const qr = useQuery({ queryKey: ["bot-qr"], queryFn: () => api<QRState>("/bot/qr"), enabled: qrOpen && canConnect, refetchInterval: qrOpen ? 2_000 : false });
  const action = useMutation({
    mutationFn: (name: "connect" | "reconnect" | "disconnect") => api<QRState | BotType>(`/bot/${name}`, { method: "POST" }),
    onSuccess: (_data, name) => { if (name !== "disconnect") setQrOpen(true); void queryClient.invalidateQueries({ queryKey: ["bot"] }); void queryClient.invalidateQueries({ queryKey: ["bot-qr"] }); },
  });
  useEffect(() => { if (qr.data?.status === "CONNECTED") { const timer = setTimeout(() => setQrOpen(false), 900); void queryClient.invalidateQueries({ queryKey: ["bot"] }); return () => clearTimeout(timer); } }, [qr.data?.status, queryClient]);
  const bot = status.data;
  const qrSrc = qr.data?.qr ? (qr.data.qr.startsWith("data:") ? qr.data.qr : `data:image/png;base64,${qr.data.qr}`) : null;

  return <div className="mx-auto max-w-6xl">
    <PageHeader eyebrow="Connection center" title="Zalo" highlight="Bot" description="Quản lý phiên đăng nhập riêng tư, kết nối và danh tính tài khoản Zalo." action={canConnect ? (bot?.status === "CONNECTED" ? <Button variant="secondary" onClick={() => action.mutate("reconnect")} loading={action.isPending}><RefreshCw className="h-4 w-4" />Kết nối lại</Button> : <Button onClick={() => action.mutate("connect")} loading={action.isPending}><QrCode className="h-4 w-4" />Kết nối Zalo</Button>) : undefined} />
    {action.isError && <div className="mb-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{action.error instanceof ApiError ? action.error.message : "Không thể thực hiện yêu cầu."}</div>}
    {bot?.status === "CONNECTED" && !bot.events_healthy && <div className="mb-5 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800" role="alert">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>Bot vẫn gửi được tin nhắn nhưng đang <strong>mất kênh nhận sự kiện</strong> từ Zalo{bot.listener_status ? ` (${bot.listener_status})` : ""}. Gateway đang tự kết nối lại; trong lúc đó tag tên tự động được tạm dừng để không nhắc lại người đã phản hồi.</span>
    </div>}
    <div className="grid gap-6 lg:grid-cols-[1.15fr_.85fr]">
      <section className="card relative overflow-hidden p-7 sm:p-9">
        <div className="absolute right-0 top-0 h-36 w-36 rounded-bl-[80px] bg-gradient-to-br from-blue-50 to-blue-100/50" />
        <div className="relative flex flex-col gap-6 sm:flex-row sm:items-center">
          {bot?.avatar_url ? <img src={bot.avatar_url} className="h-24 w-24 rounded-3xl object-cover ring-4 ring-blue-50" alt="Zalo Bot" /> : <div className="flex h-24 w-24 items-center justify-center rounded-3xl bg-gradient-to-br from-accent to-accent-secondary font-display text-3xl text-white shadow-accent">{initials(bot?.account_name)}</div>}
          <div><StatusBadge status={bot?.status ?? "ERROR"} /><h2 className="mt-4 font-display text-3xl">{bot?.account_name ?? "Chưa có tài khoản"}</h2><p className="mt-1 font-mono text-xs text-muted-foreground">{bot?.zalo_user_id ?? "Đăng nhập để nhận Zalo User ID"}</p></div>
        </div>
        <div className="mt-9 grid gap-3 border-t border-border pt-6 sm:grid-cols-2">
          <Info icon={Link2} label="Phiên đăng nhập" value={bot?.session_active ? "Đang hoạt động" : "Chưa có"} />
          <Info icon={UsersRound} label="Khách hàng đã đồng bộ" value={String(bot?.group_count ?? 0)} />
          <Info icon={ShieldCheck} label="Kết nối gần nhất" value={formatDate(bot?.last_connected_at)} />
          <Info icon={RefreshCw} label="Health check" value={formatDate(bot?.last_health_check_at)} />
        </div>
        {bot?.last_error && <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"><strong>Lỗi gần nhất:</strong> {bot.last_error}</div>}
      </section>
      <aside className="dot-grid relative overflow-hidden rounded-3xl bg-foreground p-7 text-white shadow-xl sm:p-9">
        <div className="absolute -right-16 -top-16 h-52 w-52 rounded-full bg-accent/25 blur-[85px]" />
        <Bot className="relative h-9 w-9 text-blue-400" /><h3 className="relative mt-8 font-display text-3xl">Session an toàn, vận hành liền mạch.</h3><p className="relative mt-4 text-sm leading-relaxed text-slate-300">Credential Zalo được mã hóa trong persistent volume và không bao giờ được gửi về trình duyệt.</p>
        <div className="relative mt-8 space-y-3 text-sm"><p className="flex items-center gap-3"><ShieldCheck className="h-4 w-4 text-emerald-400" />AES-256-GCM encrypted at rest</p><p className="flex items-center gap-3"><UserRound className="h-4 w-4 text-blue-400" />Một account trong Phase 1</p></div>
        {canDisconnect && <Button variant="ghost" className="relative mt-10 w-full border border-white/10 text-slate-300 hover:bg-white/10 hover:text-white" disabled={!bot?.session_active} onClick={() => { if (confirm("Đăng xuất bot sẽ xóa session đã lưu. Tiếp tục?")) action.mutate("disconnect"); }}><LogOut className="h-4 w-4" />Đăng xuất bot</Button>}
      </aside>
    </div>
    <Modal open={qrOpen} onClose={() => setQrOpen(false)} title="Quét mã QR bằng Zalo" description="Mở Zalo trên điện thoại → biểu tượng QR → quét mã để xác thực bot.">
      <div className="flex min-h-72 flex-col items-center justify-center rounded-2xl border border-dashed border-blue-200 bg-blue-50/50 p-6">
        {qrSrc ? <img src={qrSrc} alt="Mã QR đăng nhập Zalo" className="h-64 w-64 rounded-xl bg-white p-3 shadow-lg" /> : qr.data?.status === "CONNECTED" ? <div className="text-center"><ShieldCheck className="mx-auto h-16 w-16 text-emerald-500" /><p className="mt-4 font-semibold text-emerald-700">Đã kết nối thành công</p></div> : <div className="text-center"><div className="mx-auto h-12 w-12 animate-spin rounded-full border-2 border-blue-200 border-t-accent" /><p className="mt-4 text-sm text-muted-foreground">Đang tạo mã QR...</p></div>}
      </div>
      <p className="mt-4 text-center font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{qr.data?.status?.replace(/_/g, " ") ?? "PREPARING QR"}</p>
    </Modal>
  </div>;
}

function Info({ icon: Icon, label, value }: { icon: typeof Link2; label: string; value: string }) {
  return <div className="rounded-xl bg-muted/70 p-4"><Icon className="h-4 w-4 text-accent" /><p className="mt-3 text-xs text-muted-foreground">{label}</p><p className="mt-1 truncate text-sm font-semibold">{value}</p></div>;
}
