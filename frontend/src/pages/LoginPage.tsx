import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowRight, Bot, LockKeyhole, ShieldCheck, Sparkles, Zap } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { User } from "../api/types";
import { ThemeToggle } from "../components/ThemeToggle";
import { Button } from "../components/ui/Button";

export function LoginPage() {
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const login = useMutation({
    mutationFn: () => api<User>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
      const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? "/";
      navigate(from, { replace: true });
    },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); login.mutate(); };

  return (
    <main className="grid min-h-screen bg-background lg:grid-cols-[1.05fr_.95fr]">
      <section className="relative hidden overflow-hidden bg-inverse p-12 text-inverse-fg lg:flex lg:flex-col lg:justify-between xl:p-16">
        <div className="dot-grid absolute inset-0 opacity-40" />
        <div className="absolute -left-40 top-20 h-96 w-96 rounded-full bg-accent/20 blur-[130px]" />
        <div className="absolute -right-32 bottom-0 h-80 w-80 rounded-full bg-accent-secondary/15 blur-[120px]" />
        <div className="relative z-10 flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-secondary shadow-accent"><Zap className="h-5 w-5 fill-white" /></span>
          <div><div className="font-display text-2xl">ZBridge</div><div className="font-mono text-[9px] uppercase tracking-[.25em] text-inverse-fg/55">Zalo operations</div></div>
        </div>
        <div className="relative z-10 max-w-xl">
          <span className="inline-flex items-center gap-2 rounded-full border border-blue-400/30 bg-blue-400/10 px-4 py-2 font-mono text-[10px] uppercase tracking-[.15em] text-blue-300"><Sparkles className="h-3.5 w-3.5" />Small business automation</span>
          <h1 className="mt-7 font-display text-5xl leading-[1.08] xl:text-6xl">Chăm sóc khách hàng qua <span className="gradient-text">nhóm Zalo.</span></h1>
          <p className="mt-6 max-w-lg text-lg leading-relaxed text-inverse-fg/70">ZBridge giúp doanh nghiệp nhỏ quản lý khách hàng, công nợ và các luồng nhắc việc tự động trong một nơi rõ ràng, dễ vận hành.</p>
          <motion.div className="relative mt-12 h-52 max-w-lg" initial={{ opacity: 0, y: 25 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: .25 }}>
            <div className="absolute left-0 top-2 w-72 animate-float rounded-2xl border border-white/10 bg-white/10 p-5 shadow-2xl backdrop-blur-xl">
              <div className="flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-secondary"><Bot /></span><div><p className="text-sm font-semibold">Billing Bot</p><p className="mt-1 flex items-center gap-2 text-xs text-inverse-fg/70"><span className="h-2 w-2 animate-pulse-soft rounded-full bg-emerald-400" />Connected</p></div></div>
            </div>
            <div className="absolute bottom-0 right-0 w-64 animate-float rounded-2xl border border-white/10 bg-white/10 p-5 shadow-2xl backdrop-blur-xl [animation-delay:1s]">
              <div className="flex items-center justify-between"><span className="text-sm text-inverse-fg/70">Khách hàng</span><span className="font-display text-3xl">103</span></div>
              <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-white/10"><div className="h-full w-[88%] rounded-full bg-gradient-to-r from-accent to-accent-secondary" /></div>
            </div>
          </motion.div>
        </div>
        <p className="relative z-10 text-xs text-inverse-fg/45">Secure internal gateway · Credentials never reach the browser</p>
      </section>

      <section className="relative flex items-center justify-center p-6 sm:p-12">
        <div className="absolute right-4 top-4 sm:right-8 sm:top-8">
          <ThemeToggle />
        </div>
        <motion.div className="w-full max-w-md" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .6 }}>
          <div className="mb-10 flex items-center gap-3 lg:hidden"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-secondary"><Zap className="h-5 w-5 fill-white text-white" /></span><span className="font-display text-2xl">ZBridge</span></div>
          <span className="eyebrow"><LockKeyhole className="h-3.5 w-3.5" />Admin access</span>
          <h2 className="mt-5 font-display text-4xl leading-tight sm:text-5xl">Chào mừng <span className="gradient-text">trở lại.</span></h2>
          <p className="mt-3 text-muted-foreground">Đăng nhập để tiếp tục quản lý Zalo Bot.</p>
          <form onSubmit={submit} className="mt-9 space-y-5">
            <label className="block"><span className="mb-2 block text-sm font-semibold">Email</span><input className="field" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
            <label className="block"><span className="mb-2 block text-sm font-semibold">Mật khẩu</span><input className="field" type="password" autoComplete="current-password" placeholder="Tối thiểu 8 ký tự" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} /></label>
            {login.isError && <div className="rounded-xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg" role="alert">{login.error instanceof ApiError ? login.error.message : "Không thể đăng nhập."}</div>}
            <Button type="submit" loading={login.isPending} className="group h-13 w-full text-base">Đăng nhập <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" /></Button>
          </form>
          <div className="mt-8 flex items-center justify-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="h-4 w-4 text-success-fg" />Phiên đăng nhập được bảo vệ bằng HTTP-only cookie</div>
        </motion.div>
      </section>
    </main>
  );
}
