import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { ShieldOff } from "lucide-react";
import { api } from "./api/client";
import type { User } from "./api/types";
import { AppShell } from "./components/AppShell";
import { PERMISSIONS, type PermissionCode } from "./lib/permissions";
import { SessionProvider, usePermissions } from "./lib/session";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { BotPage } from "./pages/BotPage";
import { CustomersPage } from "./pages/CustomersPage";
import { CustomerDetailPage } from "./pages/CustomerDetailPage";
import { ActivityPage } from "./pages/ActivityPage";
import { UsersPage } from "./pages/UsersPage";
import { MentionSettingsPage } from "./pages/MentionSettingsPage";
import "./index.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: false } } });

/** Where to send someone whose role does not include the dashboard. */
const LANDING_FALLBACKS: Array<[PermissionCode, string]> = [
  [PERMISSIONS.customerRead, "/customers"],
  [PERMISSIONS.activityRead, "/activity"],
  [PERMISSIONS.botRead, "/bot"],
  [PERMISSIONS.mentionPolicyManage, "/mention-settings"],
  [PERMISSIONS.staffManage, "/mention-settings"],
  [PERMISSIONS.userRead, "/users"],
];

function Protected() {
  const location = useLocation();
  const { data, isLoading, isError } = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me") });
  if (isLoading) return <div className="flex min-h-screen items-center justify-center bg-foreground text-white"><div className="h-10 w-10 animate-spin rounded-full border-2 border-white/20 border-t-blue-400" /></div>;
  if (isError || !data) return <Navigate to="/login" state={{ from: location }} replace />;
  return <SessionProvider user={data}><AppShell /></SessionProvider>;
}

function NoAccess() {
  return <div className="mx-auto max-w-lg py-24 text-center">
    <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-amber-50"><ShieldOff className="h-7 w-7 text-amber-600" /></span>
    <h1 className="mt-5 font-display text-3xl">Không có quyền truy cập</h1>
    <p className="mt-3 text-sm leading-relaxed text-muted-foreground">Vai trò hiện tại của bạn không được phép xem nội dung này. Hãy liên hệ quản trị viên nếu bạn cần thêm quyền.</p>
  </div>;
}

/** Any one of the listed permissions opens the route. */
function Guard({ code, children }: { code: PermissionCode | PermissionCode[]; children: ReactNode }) {
  const { can } = usePermissions();
  const codes = Array.isArray(code) ? code : [code];
  return codes.some((item) => can(item)) ? <>{children}</> : <NoAccess />;
}

function Landing() {
  const { can } = usePermissions();
  if (can(PERMISSIONS.dashboardRead)) return <DashboardPage />;
  const fallback = LANDING_FALLBACKS.find(([code]) => can(code));
  return fallback ? <Navigate to={fallback[1]} replace /> : <NoAccess />;
}

function App() {
  return <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<Protected />}>
      <Route path="/" element={<Landing />} />
      <Route path="/bot" element={<Guard code={PERMISSIONS.botRead}><BotPage /></Guard>} />
      <Route path="/customers" element={<Guard code={PERMISSIONS.customerRead}><CustomersPage /></Guard>} />
      <Route path="/customers/:id" element={<Guard code={PERMISSIONS.customerRead}><CustomerDetailPage /></Guard>} />
      <Route path="/activity" element={<Guard code={PERMISSIONS.activityRead}><ActivityPage /></Guard>} />
      <Route path="/users" element={<Guard code={PERMISSIONS.userRead}><UsersPage /></Guard>} />
      <Route path="/mention-settings" element={<Guard code={[PERMISSIONS.mentionPolicyManage, PERMISSIONS.staffManage, PERMISSIONS.mentionBulkApply]}><MentionSettingsPage /></Guard>} />
      <Route path="/groups" element={<Navigate to="/customers" replace />} />
      <Route path="/groups/:id" element={<LegacyGroupRedirect />} />
    </Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>;
}

function LegacyGroupRedirect() {
  const { id = "" } = useParams();
  return <Navigate to={`/customers/${id}`} replace />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><QueryClientProvider client={queryClient}><BrowserRouter><App /></BrowserRouter></QueryClientProvider></StrictMode>,
);
