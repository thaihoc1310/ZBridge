import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, LayoutDashboard, LogOut, Menu, UsersRound, X, Zap } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { cn } from "../lib/cn";
import { Button } from "./ui/Button";

const links = [
  { to: "/", label: "Tổng quan", icon: LayoutDashboard, end: true },
  { to: "/customers", label: "Khách hàng", icon: UsersRound },
  { to: "/bot", label: "Zalo Bot", icon: Bot },
];

export function AppShell() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const logout = useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSuccess: () => { queryClient.clear(); navigate("/login", { replace: true }); },
  });

  return <div className="min-h-screen bg-background">
    <header className="sticky top-0 z-40 border-b border-border/80 bg-background/90 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1680px] items-center gap-6 px-4 sm:px-6 xl:px-8">
        <Link to="/" aria-label="Về trang tổng quan" className="group flex shrink-0 items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-secondary shadow-sm transition group-hover:shadow-accent"><Zap className="h-[18px] w-[18px] fill-white text-white" /></span>
          <span className="font-display text-xl leading-none text-foreground">ZBridge</span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex" aria-label="Điều hướng chính">
          {links.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} className={({ isActive }) => cn("flex h-10 items-center gap-2 rounded-xl px-3.5 text-sm font-medium transition", isActive ? "bg-blue-50 text-accent" : "text-muted-foreground hover:bg-muted hover:text-foreground")}><Icon className="h-4 w-4" />{label}</NavLink>)}
        </nav>

        <div className="ml-auto hidden md:block"><Button variant="ghost" className="h-10 min-h-10 px-3 text-muted-foreground" loading={logout.isPending} onClick={() => logout.mutate()}><LogOut className="h-4 w-4" />Đăng xuất</Button></div>
        <button onClick={() => setOpen((value) => !value)} className="ml-auto rounded-xl border border-border bg-white p-2.5 text-foreground md:hidden" aria-label={open ? "Đóng menu" : "Mở menu"}>{open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}</button>
      </div>

      {open && <div className="border-t border-border bg-white p-3 shadow-xl md:hidden">
        <nav className="space-y-1" aria-label="Điều hướng di động">{links.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)} className={({ isActive }) => cn("flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium", isActive ? "bg-blue-50 text-accent" : "text-muted-foreground hover:bg-muted hover:text-foreground")}><Icon className="h-4 w-4" />{label}</NavLink>)}</nav>
        <Button variant="ghost" className="mt-2 w-full justify-start text-muted-foreground" loading={logout.isPending} onClick={() => logout.mutate()}><LogOut className="h-4 w-4" />Đăng xuất</Button>
      </div>}
    </header>
    <main className="min-h-[calc(100vh-4rem)] p-4 sm:p-6 xl:p-8"><Outlet /></main>
  </div>;
}
