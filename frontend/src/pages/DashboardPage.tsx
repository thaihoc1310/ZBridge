import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowUpRight, Bot, CheckCircle2, Clock3, MessageSquareText, UsersRound, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Dashboard } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/ui/StatusBadge";
import { formatDate } from "../lib/format";
import { PERMISSIONS } from "../lib/permissions";
import { usePermissions } from "../lib/session";

export function DashboardPage() {
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard"), refetchInterval: 30_000 });
  const { can } = usePermissions();
  // Only link where the role can actually follow.
  const customersLink = can(PERMISSIONS.customerRead);
  const activityLink = can(PERMISSIONS.activityRead);
  const cards = [
    { label: "Bot", value: data?.bot_status ?? "—", icon: Bot, status: true },
    { label: "Tổng khách hàng", value: data?.customer_count ?? "—", sub: `${data?.customers_with_debt ?? 0} đang còn nợ`, icon: UsersRound, to: customersLink ? "/customers" : undefined },
    { label: "Tin nhắn hôm nay", value: data?.messages_today ?? "—", sub: "Mọi lượt bot gửi", icon: MessageSquareText, to: activityLink ? "/activity?date=today" : undefined },
    { label: "Thất bại hôm nay", value: data?.failed_today ?? "—", sub: activityLink ? "Bấm để kiểm tra" : "Trong hôm nay", icon: XCircle, to: activityLink ? "/activity?status=FAILED&date=today" : undefined },
  ];
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader eyebrow="Small business automation" title="Zalo Bot" highlight="Dashboard" description="Trung tâm quản trị giúp doanh nghiệp nhỏ tự động hóa công việc lặp lại trong các nhóm Zalo." />
      <motion.div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" initial="hidden" animate="visible" variants={{ hidden: {}, visible: { transition: { staggerChildren: .08 } } }}>
        {cards.map(({ label, value, sub, icon: Icon, status, to }) => (
          <motion.article key={label} variants={{ hidden: { opacity: 0, y: 18 }, visible: { opacity: 1, y: 0 } }} className={`card group relative overflow-hidden p-6 transition-all duration-300 hover:-translate-y-1 hover:shadow-card-hover ${to ? "cursor-pointer" : ""}`}>
            {to && <Link to={to} className="absolute inset-0 z-10" aria-label={`Mở ${label}`} />}
            <div className="absolute inset-0 bg-gradient-to-br from-accent/[.035] to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
            <div className="relative flex items-start justify-between"><p className="text-sm font-medium text-muted-foreground">{label}</p><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-secondary text-white shadow-sm"><Icon className="h-5 w-5" /></span></div>
            <div className="relative mt-7">{status && data ? <StatusBadge status={String(value)} /> : <p className="font-display text-4xl">{isLoading ? "···" : value}</p>}{sub && <p className="mt-2 text-xs text-muted-foreground">{sub}</p>}</div>
          </motion.article>
        ))}
      </motion.div>

      <section className="dot-grid relative mt-6 overflow-hidden rounded-3xl bg-foreground p-7 text-white shadow-xl sm:p-9">
        <div className="absolute -right-20 -top-24 h-72 w-72 rounded-full bg-accent/25 blur-[100px]" />
        <div className="relative grid gap-8 lg:grid-cols-[1fr_1.2fr] lg:items-center">
          <div><span className="inline-flex items-center gap-2 rounded-full border border-blue-400/30 bg-blue-400/10 px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-blue-300"><span className="h-2 w-2 animate-pulse-soft rounded-full bg-blue-400" />System pulse</span><h2 className="mt-5 font-display text-3xl sm:text-4xl">Nền tảng đang <span className="text-blue-400">sẵn sàng.</span></h2><p className="mt-3 max-w-md text-sm leading-relaxed text-slate-300">Theo dõi vận hành và để ZBridge xử lý các việc lặp lại như tag tên, nhắc hẹn và thanh toán.</p></div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/[.07] p-5 backdrop-blur"><Clock3 className="h-5 w-5 text-blue-400" /><p className="mt-5 text-xs text-slate-400">Đồng bộ gần nhất</p><p className="mt-1 text-sm font-semibold">{formatDate(data?.last_sync_at)}</p></div>
            <div className="rounded-2xl border border-white/10 bg-white/[.07] p-5 backdrop-blur"><CheckCircle2 className="h-5 w-5 text-emerald-400" /><p className="mt-5 text-xs text-slate-400">Gửi thành công gần nhất</p><p className="mt-1 text-sm font-semibold">{formatDate(data?.last_successful_message_at)}</p></div>
          </div>
        </div>
      </section>
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {can(PERMISSIONS.botRead) && <Link to="/bot" className="card group flex items-center justify-between p-5 transition hover:border-accent/30 hover:shadow-card-hover"><span><span className="text-sm font-semibold">Quản lý kết nối</span><span className="mt-1 block text-xs text-muted-foreground">Session, QR và sức khỏe bot</span></span><ArrowUpRight className="text-muted-foreground transition group-hover:-translate-y-1 group-hover:translate-x-1 group-hover:text-accent" /></Link>}
        {customersLink && <Link to="/customers" className="card group flex items-center justify-between p-5 transition hover:border-accent/30 hover:shadow-card-hover"><span><span className="text-sm font-semibold">Mở danh sách khách hàng</span><span className="mt-1 block text-xs text-muted-foreground">Công nợ, hồ sơ và cấu hình tự động hóa</span></span><ArrowUpRight className="text-muted-foreground transition group-hover:-translate-y-1 group-hover:translate-x-1 group-hover:text-accent" /></Link>}
      </div>
    </div>
  );
}
