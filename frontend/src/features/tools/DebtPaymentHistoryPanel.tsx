import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Search } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { DebtPaymentHistory, DebtPaymentHistoryItem, PaymentHistoryGroup } from "../../api/types";
import { formatDate, initials } from "../../lib/format";
import { PERMISSIONS } from "../../lib/permissions";
import { usePermissions } from "../../lib/session";

const groups: Array<[PaymentHistoryGroup | "all", string]> = [
  ["sent", "Đã báo"],
  ["skipped", "Không báo"],
  ["in_progress", "Đang xử lý"],
  ["failed", "Lỗi"],
  ["all", "Tất cả"],
];
const groupLabel: Record<PaymentHistoryGroup, string> = {
  sent: "Đã báo kế toán",
  skipped: "Không báo",
  in_progress: "Đang xử lý",
  failed: "Lỗi, cần xử lý tay",
};
const groupTone: Record<PaymentHistoryGroup, string> = {
  sent: "bg-success-bg text-success-fg",
  skipped: "bg-muted text-muted-foreground",
  in_progress: "bg-accent-soft text-accent",
  failed: "bg-danger-bg text-danger-fg",
};

/** Which customers the bot told the accountant about, and whether they caught up. */
export function DebtPaymentHistoryPanel() {
  const { can } = usePermissions();
  const canOpenCustomer = can(PERMISSIONS.customerRead);
  const [search, setSearch] = useState("");
  // Opens on what was announced: the list an accountant works through.
  const [group, setGroup] = useState<PaymentHistoryGroup | "all">("sent");
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["debt-payment-history", search, group, page],
    queryFn: () => {
      const params = new URLSearchParams({ search, page: String(page), limit: "50" });
      if (group !== "all") params.set("group", group);
      return api<DebtPaymentHistory>(`/tools/debt-payment-confirmation/history?${params}`);
    },
    refetchInterval: 20_000,
  });
  const counts = query.data?.group_counts ?? {};

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {groups.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              setGroup(key);
              setPage(1);
            }}
            className={`rounded-xl border p-3 text-left transition ${group === key ? "border-accent bg-accent-soft" : "border-border bg-card hover:bg-muted/40"}`}
          >
            <span className="block text-xs text-muted-foreground">{label}</span>
            <strong className="mt-1 block text-xl">{counts[key] ?? 0}</strong>
          </button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Trạng thái công nợ là trạng thái hiện tại của khách hàng; bot không tự chuyển, kế toán
        cập nhật trên trang khách hàng. Dữ liệu được lưu {query.data?.retention_days ?? 45} ngày.
      </p>
      <label className="relative block">
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

      {query.isLoading ? (
        <Empty text="Đang tải lịch sử..." />
      ) : query.isError ? (
        <Empty text="Không tải được lịch sử báo thanh toán." danger />
      ) : !query.data?.items.length ? (
        <Empty text="Không có lượt báo thanh toán phù hợp." />
      ) : (
        <div className="divide-y divide-border overflow-hidden rounded-xl border border-border">
          {query.data.items.map((item) =>
            canOpenCustomer ? (
              <Link
                key={item.id}
                to={`/customers/${item.customer_id}`}
                className="group flex items-start gap-3 bg-card p-4 transition hover:bg-muted/40"
              >
                <Row item={item} />
                <ChevronRight className="mt-3 h-4 w-4 shrink-0 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-accent" />
              </Link>
            ) : (
              <div key={item.id} className="flex items-start gap-3 bg-card p-4">
                <Row item={item} />
              </div>
            ),
          )}
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

function Row({ item }: { item: DebtPaymentHistoryItem }) {
  return (
    <>
      <span className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-accent-soft text-xs font-bold text-accent">
        {item.customer_avatar_url ? (
          <img src={item.customer_avatar_url} alt="" className="h-full w-full object-cover" />
        ) : (
          initials(item.customer_name)
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <strong className="text-sm">{item.customer_name}</strong>
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${groupTone[item.group]}`}>
            {groupLabel[item.group]}
          </span>
          <span
            className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${item.customer_has_debt ? "bg-warning-bg text-warning-fg" : "bg-success-bg text-success-fg"}`}
            title="Trạng thái công nợ hiện tại của khách hàng"
          >
            {item.customer_has_debt ? "Đang còn nợ" : "Đã thanh toán"}
          </span>
        </span>
        <span className="mt-1 block break-words text-sm text-foreground">“{item.content}”</span>
        <span className="mt-1 block text-xs text-muted-foreground">
          {item.sender_display_name || "Không rõ người gửi"} nhắn {formatDate(item.message_sent_at)}
          {item.notified_at ? ` · bot báo ${formatDate(item.notified_at)}` : ""}
          {item.customer_last_debt_paid_at
            ? ` · lần cuối chuyển đã thanh toán ${formatDate(item.customer_last_debt_paid_at)}`
            : item.customer_has_debt
              ? " · chưa từng chuyển đã thanh toán"
              : ""}
        </span>
        {item.group !== "sent" && item.reason && (
          <span className="mt-1 block text-xs text-muted-foreground">Lý do: {item.reason}</span>
        )}
      </span>
    </>
  );
}

function Empty({ text, danger = false }: { text: string; danger?: boolean }) {
  return (
    <div
      className={`rounded-xl border p-8 text-center text-sm ${danger ? "border-danger-border bg-danger-bg text-danger-fg" : "border-border text-muted-foreground"}`}
    >
      {text}
    </div>
  );
}
