import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowUpRight, Bot, MessageSquareText, UsersRound, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Dashboard } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/ui/StatusBadge";
import { DashboardCharts } from "../features/dashboard/DashboardCharts";
import { HealthStrip } from "../features/dashboard/HealthStrip";
import { PERMISSIONS } from "../lib/permissions";
import { usePermissions } from "../lib/session";

export function DashboardPage() {
  const { data, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard"), refetchInterval: 30_000 });
  const { can } = usePermissions();
  // Only link where the role can actually follow.
  const customersLink = can(PERMISSIONS.customerRead);
  const activityLink = can(PERMISSIONS.activityRead);
  const toolsLink = can(PERMISSIONS.toolsRead);
  const botLink = can(PERMISSIONS.botRead);
  // A number on its own answers nothing: 40 sends is busy or quiet only next to
  // yesterday. Skipped when yesterday was zero, where a percentage is noise.
  const change =
    data && data.messages_yesterday > 0
      ? Math.round(((data.messages_today - data.messages_yesterday) / data.messages_yesterday) * 100)
      : null;
  const changeLabel =
    change === null
      ? "Mọi lượt bot gửi"
      : `${change > 0 ? "+" : ""}${change}% so với hôm qua (${data?.messages_yesterday})`;
  const cards = [
    // The state that most often needs a human is the one that used to have
    // nowhere to click through to.
    { label: "Bot", value: data?.bot_status ?? "—", icon: Bot, status: true, to: botLink ? "/bot" : undefined },
    { label: "Tổng khách hàng", value: data?.customer_count ?? "—", sub: `${data?.customers_with_debt ?? 0} đang còn nợ`, icon: UsersRound, to: customersLink ? "/customers" : undefined },
    { label: "Tin nhắn hôm nay", value: data?.messages_today ?? "—", sub: changeLabel, subTone: change === null ? undefined : change >= 0 ? "up" : "down", icon: MessageSquareText, to: activityLink ? "/activity?date=today" : undefined },
    { label: "Thất bại hôm nay", value: data?.failed_today ?? "—", sub: activityLink ? "Bấm để kiểm tra" : "Trong hôm nay", icon: XCircle, to: activityLink ? "/activity?status=FAILED&date=today" : undefined },
  ];
  return (
    <div className="mx-auto max-w-7xl">
      <PageHeader eyebrow="Small business automation" title="Zalo Bot" highlight="Dashboard" description="Trung tâm quản trị giúp doanh nghiệp nhỏ tự động hóa công việc lặp lại trong các nhóm Zalo." />
      <motion.div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" initial="hidden" animate="visible" variants={{ hidden: {}, visible: { transition: { staggerChildren: .08 } } }}>
        {cards.map(({ label, value, sub, subTone, icon: Icon, status, to }) => (
          <motion.article key={label} variants={{ hidden: { opacity: 0, y: 18 }, visible: { opacity: 1, y: 0 } }} className={`card group relative overflow-hidden px-4 py-3.5 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-card-hover ${to ? "cursor-pointer" : ""}`}>
            {to && <Link to={to} className="absolute inset-0 z-10" aria-label={`Mở ${label}`} />}
            <div className="absolute inset-0 bg-gradient-to-br from-accent/[.035] to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
            <div className="relative flex items-center justify-between gap-3"><p className="text-sm font-medium text-muted-foreground">{label}</p><span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-secondary text-white shadow-sm"><Icon className="h-3.5 w-3.5" /></span></div>
            <div className="relative mt-2.5">{status && data ? <StatusBadge status={String(value)} /> : <p className="font-display text-2xl leading-none">{isLoading ? "···" : value}</p>}{sub && <p className={`mt-1 text-[11px] ${subTone === "up" ? "text-success-fg" : subTone === "down" ? "text-danger-fg" : "text-muted-foreground"}`}>{sub}</p>}</div>
          </motion.article>
        ))}
      </motion.div>

      <HealthStrip data={data} />

      <DashboardCharts data={data} />

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {customersLink && <Link to="/customers" className="card group flex items-center justify-between px-4 py-3.5 transition hover:border-accent/30 hover:shadow-card-hover"><span><span className="text-sm font-semibold">Mở danh sách khách hàng</span><span className="mt-0.5 block text-xs text-muted-foreground">Công nợ, hồ sơ và cấu hình tự động hóa</span></span><ArrowUpRight className="text-muted-foreground transition group-hover:-translate-y-1 group-hover:translate-x-1 group-hover:text-accent" /></Link>}
        {toolsLink && <Link to="/tools" className="card group flex items-center justify-between px-4 py-3.5 transition hover:border-accent/30 hover:shadow-card-hover"><span><span className="text-sm font-semibold">Mở công cụ</span><span className="mt-0.5 block text-xs text-muted-foreground">Tag tự động, nhắc công nợ và tiện ích Google Drive</span></span><ArrowUpRight className="text-muted-foreground transition group-hover:-translate-y-1 group-hover:translate-x-1 group-hover:text-accent" /></Link>}
      </div>
    </div>
  );
}
