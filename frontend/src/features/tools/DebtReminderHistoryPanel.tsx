import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ExternalLink,
  FileImage,
  Link2,
  MessageSquareText,
  Search,
} from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import type { DebtReminderRunList } from "../../api/types";
import { formatDate } from "../../lib/format";

const labels: Record<string, string> = {
  PENDING: "Chờ chạy",
  PROCESSING: "Đang chạy",
  SENT: "Thành công",
  FAILED: "Thất bại",
  SKIPPED: "Bỏ qua",
  CANCELLED: "Đã hủy",
};
const tones: Record<string, string> = {
  PENDING: "bg-amber-50 text-amber-700",
  PROCESSING: "bg-blue-50 text-accent",
  SENT: "bg-emerald-50 text-emerald-700",
  FAILED: "bg-red-50 text-red-700",
  SKIPPED: "bg-slate-100 text-slate-600",
  CANCELLED: "bg-slate-100 text-slate-600",
};
const stepIcons = { IMAGE: FileImage, LINK: Link2, MESSAGE: MessageSquareText };
const stepNames = {
  IMAGE: "Ảnh công nợ",
  LINK: "Link Google Sheet",
  MESSAGE: "Nội dung nhắc",
};

export function DebtReminderHistoryPanel() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("scheduled");
  const [direction, setDirection] = useState("desc");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const now = new Date();
  const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const query = useQuery({
    queryKey: [
      "debt-reminder-history",
      search,
      status,
      sort,
      direction,
      page,
    ],
    queryFn: () => {
      const params = new URLSearchParams({
        month,
        search,
        sort,
        direction,
        page: String(page),
        limit: "50",
      });
      if (status) params.set("status", status);
      return api<DebtReminderRunList>(
        `/tools/debt-reminders/history?${params.toString()}`,
      );
    },
    refetchInterval: 20_000,
  });
  const counts = query.data?.status_counts ?? {};
  const cards = [
    ["ALL", "Tổng"],
    ["SENT", "Thành công"],
    ["PROCESSING", "Đang chạy"],
    ["PENDING", "Chờ chạy"],
    ["FAILED", "Thất bại"],
  ];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {cards.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              setStatus(key === "ALL" ? "" : key);
              setPage(1);
            }}
            className={`rounded-xl border p-3 text-left transition ${status === (key === "ALL" ? "" : key) ? "border-accent bg-blue-50" : "border-border bg-white hover:bg-muted/40"}`}
          >
            <span className="block text-xs text-muted-foreground">{label}</span>
            <strong className="mt-1 block text-xl">{counts[key] ?? 0}</strong>
          </button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Hiển thị lượt trong tháng hiện tại còn tồn tại. Dữ liệu được lưu 45 ngày.
      </p>
      <div className="flex flex-col gap-3 sm:flex-row">
        <label className="relative flex-1">
          <Search className="absolute left-3 top-3.5 h-4 w-4 text-muted-foreground" />
          <input
            className="field pl-10"
            placeholder="Tìm công ty..."
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
        </label>
        <select
          className="field sm:w-44"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setPage(1);
          }}
        >
          <option value="">Tất cả trạng thái</option>
          <option value="PENDING">Chờ chạy</option>
          <option value="PROCESSING">Đang chạy</option>
          <option value="SENT">Thành công</option>
          <option value="FAILED">Thất bại</option>
          <option value="SKIPPED">Bỏ qua</option>
          <option value="CANCELLED">Đã hủy</option>
        </select>
        <select
          className="field sm:w-44"
          value={sort}
          onChange={(event) => {
            setSort(event.target.value);
            setPage(1);
          }}
        >
          <option value="scheduled">Theo thời gian</option>
          <option value="company">Theo công ty</option>
          <option value="status">Theo trạng thái</option>
        </select>
        <button
          type="button"
          className="min-h-11 rounded-xl border border-border bg-white px-4 text-sm font-medium"
          onClick={() => {
            setDirection((value) => (value === "desc" ? "asc" : "desc"));
            setPage(1);
          }}
        >
          {direction === "desc" ? "Giảm dần" : "Tăng dần"}
        </button>
      </div>
      {query.isLoading ? (
        <Empty text="Đang tải lịch sử..." />
      ) : query.isError ? (
        <Empty text="Không tải được lịch sử nhắc công nợ." danger />
      ) : !query.data?.items.length ? (
        <Empty text="Không có lượt nhắc phù hợp." />
      ) : (
        <div className="divide-y divide-border overflow-hidden rounded-xl border border-border">
          {query.data.items.map((run) => {
            const open = expanded.has(run.id);
            return (
              <div key={run.id} className="bg-white">
                <button
                  type="button"
                  className="flex w-full items-center gap-3 p-4 text-left hover:bg-muted/40"
                  onClick={() =>
                    setExpanded((current) => {
                      const next = new Set(current);
                      if (open) next.delete(run.id);
                      else next.add(run.id);
                      return next;
                    })
                  }
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">
                      {run.customer_name}
                    </span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      Lịch chạy {formatDate(run.scheduled_for)} · thử{" "}
                      {run.attempt_count} lần
                    </span>
                  </span>
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs font-semibold ${tones[run.status]}`}
                  >
                    {labels[run.status]}
                  </span>
                  <ChevronDown
                    className={`h-4 w-4 transition ${open ? "rotate-180" : ""}`}
                  />
                </button>
                {open && (
                  <div className="border-t border-border bg-muted/20 p-4">
                    <div className="grid gap-2 sm:grid-cols-3">
                      {run.steps.map((step) => {
                        const Icon = stepIcons[step.type];
                        return (
                          <div
                            key={step.type}
                            className="rounded-xl border border-border bg-white p-3"
                          >
                            <div className="flex items-center gap-2">
                              <Icon className="h-4 w-4 text-accent" />
                              <strong className="text-xs">
                                {stepNames[step.type]}
                              </strong>
                            </div>
                            <span
                              className={`mt-2 inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${tones[step.status]}`}
                            >
                              {labels[step.status]}
                            </span>
                            {step.error_message && (
                              <p className="mt-2 text-xs text-red-700">
                                {step.error_message}
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                      <span>Tạo: {formatDate(run.created_at)}</span>
                      {run.processed_at && (
                        <span>Xong: {formatDate(run.processed_at)}</span>
                      )}
                      {run.sheet_url && (
                        <a
                          className="inline-flex items-center gap-1 font-medium text-accent hover:underline"
                          href={run.sheet_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Mở Google Sheet <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </div>
                    {run.error_message && (
                      <p className="mt-3 rounded-lg bg-red-50 p-2 text-xs text-red-700">
                        {run.error_code ? `${run.error_code}: ` : ""}
                        {run.error_message}
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {(query.data?.pages ?? 1) > 1 && (
        <div className="flex items-center justify-end gap-3 text-sm">
          <button
            type="button"
            className="min-h-10 rounded-xl border border-border px-3 disabled:opacity-40"
            disabled={page <= 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
          >
            Trang trước
          </button>
          <span className="text-xs text-muted-foreground">
            Trang {page}/{query.data?.pages}
          </span>
          <button
            type="button"
            className="min-h-10 rounded-xl border border-border px-3 disabled:opacity-40"
            disabled={page >= (query.data?.pages ?? 1)}
            onClick={() => setPage((value) => value + 1)}
          >
            Trang sau
          </button>
        </div>
      )}
    </div>
  );
}

function Empty({ text, danger = false }: { text: string; danger?: boolean }) {
  return (
    <div
      className={`rounded-xl border p-8 text-center text-sm ${danger ? "border-red-200 bg-red-50 text-red-700" : "border-border text-muted-foreground"}`}
    >
      {text}
    </div>
  );
}
