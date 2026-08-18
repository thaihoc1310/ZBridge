import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { api } from "./api/client";
import type { User } from "./api/types";
import { AppShell } from "./components/AppShell";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { BotPage } from "./pages/BotPage";
import { CustomersPage } from "./pages/CustomersPage";
import { CustomerDetailPage } from "./pages/CustomerDetailPage";
import { ActivityPage } from "./pages/ActivityPage";
import "./index.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: false } } });

function Protected() {
  const location = useLocation();
  const { data, isLoading, isError } = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me") });
  if (isLoading) return <div className="flex min-h-screen items-center justify-center bg-foreground text-white"><div className="h-10 w-10 animate-spin rounded-full border-2 border-white/20 border-t-blue-400" /></div>;
  if (isError || !data) return <Navigate to="/login" state={{ from: location }} replace />;
  return <AppShell />;
}

function App() {
  return <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<Protected />}>
      <Route path="/" element={<DashboardPage />} />
      <Route path="/bot" element={<BotPage />} />
      <Route path="/customers" element={<CustomersPage />} />
      <Route path="/customers/:id" element={<CustomerDetailPage />} />
      <Route path="/activity" element={<ActivityPage />} />
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
