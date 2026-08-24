import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronDown,
  Search,
  StopCircle,
  Users,
} from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "../../api/client";
import type {
  ActiveMentionCompanyList,
  ActiveMentionTask,
} from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { formatDate } from "../../lib/format";

const statusLabels: Record<string, string> = {
  CLASSIFYING: "Đang phân loại",
  PENDING: "Chờ chạy",
  PROCESSING: "Đang xử lý",
};

export function ActiveMentionTasksPanel({ canCancel }: { canCancel: boolean }) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("next_due");
  const [direction, setDirection] = useState("asc");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [stopping, setStopping] = useState<ActiveMentionTask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["active-mention-followups", search, sort, direction],
    queryFn: () =>
      api<ActiveMentionCompanyList>(
        `/tools/mention-followups?search=${encodeURIComponent(search)}&sort=${sort}&direction=${direction}&limit=100`,
      ),
    refetchInterval: 15_000,
  });
  const cancel = useMutation({
    mutationFn: (id: string) =>
      api(`/tools/mention-followups/${id}/cancel`, { method: "POST" }),
    onSuccess: () => {
      setStopping(null);
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["active-mention-followups"] });
    },
    onError: (err) =>
      setError(
        err instanceof ApiError ? err.message : "Không dừng được vòng tag.",
      ),
  });

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Summary
          label="Task đang hoạt động"
          value={query.data?.total_tasks ?? 0}
        />
        <Summary
          label="Công ty có task"
          value={query.data?.total_companies ?? 0}
        />
      </div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <label className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-muted-foreground" />
          <input
            className="field pl-10"
            placeholder="Tìm công ty hoặc người đang được tag..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <select
          className="field sm:w-48"
          value={sort}
          onChange={(event) => setSort(event.target.value)}
        >
          <option value="next_due">Sắp chạy trước</option>
          <option value="newest">Mới nhất</option>
          <option value="name">Tên công ty</option>
          <option value="count">Số task</option>
        </select>
        <button
          type="button"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border bg-white text-muted-foreground transition hover:bg-muted/40 hover:text-foreground"
          aria-label={direction === "asc" ? "Sắp xếp giảm dần" : "Sắp xếp tăng dần"}
          title={direction === "asc" ? "Đang tăng dần · bấm để giảm dần" : "Đang giảm dần · bấm để tăng dần"}
          onClick={() =>
            setDirection((value) => (value === "asc" ? "desc" : "asc"))
          }
        >
          {direction === "asc" ? (
            <ArrowUp className="h-4 w-4" />
          ) : (
            <ArrowDown className="h-4 w-4" />
          )}
        </button>
      </div>
      {error && (
        <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </p>
      )}
      {query.isLoading ? (
        <Empty text="Đang tải các vòng tag..." />
      ) : query.isError ? (
        <Empty text="Không tải được các vòng tag." danger />
      ) : !query.data?.items.length ? (
        <Empty text="Hiện không có vòng tag nào đang hoạt động." />
      ) : (
        <div className="divide-y divide-border overflow-hidden rounded-xl border border-border">
          {query.data.items.map((company) => {
            const open = expanded.has(company.customer_id);
            return (
              <div key={company.customer_id} className="bg-white">
                <button
                  type="button"
                  className="flex min-h-16 w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/40"
                  onClick={() =>
                    setExpanded((current) => {
                      const next = new Set(current);
                      if (open) next.delete(company.customer_id);
                      else next.add(company.customer_id);
                      return next;
                    })
                  }
                >
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-accent">
                    <Users className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">
                      {company.customer_name}
                    </span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      Gần nhất {formatDate(company.next_due_at)}
                    </span>
                  </span>
                  <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700">
                    {company.task_count} task
                  </span>
                  <ChevronDown
                    className={`h-4 w-4 text-muted-foreground transition ${open ? "rotate-180" : ""}`}
                  />
                </button>
                {open && (
                  <div className="space-y-2 border-t border-border bg-muted/20 p-3 sm:p-4">
                    {company.tasks.map((task) => (
                      <div
                        key={task.id}
                        className="rounded-xl border border-border bg-white p-4"
                      >
                        <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="rounded-full bg-blue-50 px-2.5 py-1 text-xs font-semibold text-accent">
                                {task.trigger === "MENTION"
                                  ? "Tag tên"
                                  : "Báo giá"}
                              </span>
                              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                                {statusLabels[task.status] ?? task.status}
                              </span>
                            </div>
                            <p className="mt-3 text-sm">
                              <strong>Đang chờ:</strong>{" "}
                              {task.target_display_names.join(", ")}
                            </p>
                            <div className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                              <span>
                                Bắt đầu: {formatDate(task.created_at)}
                              </span>
                              <span>Chạy tiếp: {formatDate(task.due_at)}</span>
                              <span>Đã gửi: {task.send_count} lần</span>
                              <span className="font-mono">
                                #{task.id.slice(0, 8)}
                              </span>
                            </div>
                            {task.error_message && (
                              <p className="mt-2 text-xs text-red-700">
                                {task.error_message}
                              </p>
                            )}
                          </div>
                          {canCancel && (
                            <Button
                              variant="danger"
                              className="shrink-0"
                              onClick={() => setStopping(task)}
                            >
                              <StopCircle className="h-4 w-4" />
                              Dừng task
                            </Button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <Modal
        open={Boolean(stopping)}
        onClose={() => !cancel.isPending && setStopping(null)}
        className="max-w-md"
        title="Dừng vòng tag?"
        description="Vòng tag sẽ ngừng ngay và không tự khởi động lại."
      >
        <div className="space-y-4">
          <div className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
            <AlertTriangle className="h-5 w-5 shrink-0" />
            <span>
              Đang chờ {stopping?.target_display_names.join(", ")}. Bạn chắc
              chắn muốn dừng task này?
            </span>
          </div>
          <div className="flex justify-end gap-3">
            <Button variant="ghost" onClick={() => setStopping(null)}>
              Không
            </Button>
            <Button
              variant="danger"
              loading={cancel.isPending}
              onClick={() => stopping && cancel.mutate(stopping.id)}
            >
              Dừng task
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-border bg-muted/30 p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-display text-2xl">{value}</p>
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
