import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  ScrollText,
  ShieldCheck,
  UsersRound,
  Wrench,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ChangePasswordModal } from "../features/account/ChangePasswordModal";
import { cn } from "../lib/cn";
import { initials } from "../lib/format";
import { PERMISSIONS, type PermissionCode } from "../lib/permissions";
import { usePermissions, useSession } from "../lib/session";
import { ThemeToggle } from "./ThemeToggle";
import { Button } from "./ui/Button";

type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  /** Any one of these is enough to show the tab. */
  permission: PermissionCode | PermissionCode[];
};

const navItems: NavItem[] = [
  {
    to: "/",
    label: "Tổng quan",
    icon: LayoutDashboard,
    end: true,
    permission: PERMISSIONS.dashboardRead,
  },
  {
    to: "/customers",
    label: "Khách hàng",
    icon: UsersRound,
    permission: PERMISSIONS.customerRead,
  },
  {
    to: "/activity",
    label: "Nhật ký",
    icon: ScrollText,
    permission: [PERMISSIONS.activityRead, PERMISSIONS.modelActivityRead],
  },
  { to: "/bot", label: "Zalo Bot", icon: Bot, permission: PERMISSIONS.botRead },
  {
    to: "/tools",
    label: "Công cụ",
    icon: Wrench,
    permission: PERMISSIONS.toolsRead,
  },
  {
    to: "/users",
    label: "Người dùng",
    icon: ShieldCheck,
    permission: PERMISSIONS.userRead,
  },
];

export function AppShell() {
  const [open, setOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useSession();
  const { can } = usePermissions();
  const links = navItems.filter((item) =>
    (Array.isArray(item.permission) ? item.permission : [item.permission]).some(
      (code) => can(code),
    ),
  );
  const logout = useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSuccess: () => {
      queryClient.clear();
      navigate("/login", { replace: true });
    },
  });

  useEffect(() => {
    if (!accountOpen) return;
    const close = (event: MouseEvent) => {
      if (!accountRef.current?.contains(event.target as Node))
        setAccountOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [accountOpen]);

  const displayName = user.full_name || user.email;

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border/80 bg-background/90 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1680px] items-center gap-6 px-4 sm:px-6 xl:px-8">
          <Link
            to="/"
            aria-label="Về trang chủ"
            className="group flex shrink-0 items-center gap-2.5"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-secondary shadow-sm transition group-hover:shadow-accent">
              <Zap className="h-[18px] w-[18px] fill-white text-white" />
            </span>
            <span className="font-display text-xl leading-none text-foreground">
              ZBridge
            </span>
          </Link>

          <nav
            className="hidden items-center gap-1 md:flex"
            aria-label="Điều hướng chính"
          >
            {links.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "flex h-10 items-center gap-2 rounded-xl px-3.5 text-sm font-medium transition",
                    isActive
                      ? "bg-accent-soft text-accent"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )
                }
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            <ThemeToggle />
            <div ref={accountRef} className="relative hidden md:block">
              <button
                type="button"
                aria-expanded={accountOpen}
                aria-haspopup="menu"
                onClick={() => setAccountOpen((value) => !value)}
                className="flex h-11 items-center gap-2.5 rounded-xl border border-border bg-card pl-2 pr-3 text-left transition hover:border-accent/30 hover:bg-muted/50"
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent-soft to-accent/20 text-[10px] font-bold text-accent">
                  {initials(displayName)}
                </span>
                <span className="min-w-0">
                  <span className="block max-w-36 truncate text-xs font-semibold leading-tight">
                    {displayName}
                  </span>
                  <span className="block max-w-36 truncate text-[10px] leading-tight text-muted-foreground">
                    {user.role.name}
                  </span>
                </span>
              </button>
              {accountOpen && (
                <div
                  role="menu"
                  className="absolute right-0 top-14 z-30 w-72 rounded-2xl border border-border bg-card p-2 shadow-2xl"
                >
                  <div className="border-b border-border px-3 pb-3 pt-2">
                    <p className="truncate text-sm font-semibold">
                      {displayName}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {user.email}
                    </p>
                    <span className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-1 text-[10px] font-semibold text-accent">
                      <ShieldCheck className="h-3 w-3" />
                      {user.role.name}
                    </span>
                  </div>
                  <button
                    type="button"
                    role="menuitem"
                    className="mt-1 flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-sm font-medium text-foreground transition hover:bg-muted"
                    onClick={() => {
                      setAccountOpen(false);
                      setPasswordOpen(true);
                    }}
                  >
                    <KeyRound className="h-4 w-4 text-accent" />
                    Đổi mật khẩu
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-sm font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:opacity-50"
                    disabled={logout.isPending}
                    onClick={() => logout.mutate()}
                  >
                    <LogOut className="h-4 w-4" />
                    Đăng xuất
                  </button>
                </div>
              )}
            </div>

            <button
              onClick={() => setOpen((value) => !value)}
              className="rounded-xl border border-border bg-card p-2.5 text-foreground md:hidden"
              aria-label={open ? "Đóng menu" : "Mở menu"}
            >
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>

        {open && (
          <div className="border-t border-border bg-card p-3 shadow-xl md:hidden">
            <div className="mb-2 rounded-xl bg-muted/60 px-3 py-2.5">
              <p className="truncate text-sm font-semibold">{displayName}</p>
              <p className="truncate text-xs text-muted-foreground">
                {user.role.name}
              </p>
            </div>
            <nav className="space-y-1" aria-label="Điều hướng di động">
              {links.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      "flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-medium",
                      isActive
                        ? "bg-accent-soft text-accent"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )
                  }
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </NavLink>
              ))}
            </nav>
            <Button
              variant="ghost"
              className="mt-2 w-full justify-start text-muted-foreground"
              onClick={() => {
                setOpen(false);
                setPasswordOpen(true);
              }}
            >
              <KeyRound className="h-4 w-4" />
              Đổi mật khẩu
            </Button>
            <Button
              variant="ghost"
              className="w-full justify-start text-muted-foreground"
              loading={logout.isPending}
              onClick={() => logout.mutate()}
            >
              <LogOut className="h-4 w-4" />
              Đăng xuất
            </Button>
          </div>
        )}
      </header>
      <main className="min-h-[calc(100vh-4rem)] p-4 sm:p-6 xl:p-8">
        <Outlet />
      </main>
      <ChangePasswordModal
        open={passwordOpen}
        onClose={() => setPasswordOpen(false)}
      />
    </div>
  );
}
