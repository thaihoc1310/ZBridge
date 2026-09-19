import { ArrowUpRight, BadgeCheck } from "lucide-react";
import { Link } from "react-router-dom";
import type { DashboardDebtPaymentConfirmation } from "../../api/types";
import { formatDate, initials } from "../../lib/format";

export function DebtPaymentConfirmationsPanel({
  items,
  canOpenCustomer,
}: {
  items: DashboardDebtPaymentConfirmation[];
  canOpenCustomer: boolean;
}) {
  return (
    <section className="card mt-4 overflow-hidden">
      <header className="flex items-center justify-between gap-4 border-b border-border px-5 py-4">
        <span>
          <span className="flex items-center gap-2 font-semibold">
            <BadgeCheck className="h-5 w-5 text-success-fg" />
            Tự động ghi nhận thanh toán
          </span>
          <span className="mt-1 block text-xs text-muted-foreground">
            Các khách hàng được chuyển sang đã thanh toán trong 45 ngày gần đây.
          </span>
        </span>
        <span className="rounded-full bg-success-bg px-3 py-1 text-xs font-semibold text-success-fg">
          {items.length}
        </span>
      </header>

      <div className="app-scrollbar max-h-[60vh] overflow-y-auto sm:max-h-[28rem]">
        {items.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-muted-foreground">
            Chưa có khách hàng nào được tự động chuyển trạng thái.
          </p>
        ) : (
          <div className="divide-y divide-border">
            {items.map((item) => {
              const content = (
                <>
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-success-bg text-xs font-bold text-success-fg">
                    {item.customer_avatar_url ? (
                      <img
                        src={item.customer_avatar_url}
                        alt=""
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      initials(item.customer_name)
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <strong className="text-sm">{item.customer_name}</strong>
                      <span className="rounded-full bg-success-bg px-2 py-0.5 text-[11px] font-semibold text-success-fg">
                        Đã tự chuyển sang thanh toán
                      </span>
                    </span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {item.sender_display_name || "Không rõ người gửi"} · {formatDate(item.message_sent_at)}
                    </span>
                    <span className="mt-2 block whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground">
                      {item.content}
                    </span>
                    <span className="mt-1 block text-[11px] text-muted-foreground">
                      Khớp câu “{item.matched_phrase}”
                    </span>
                  </span>
                  {canOpenCustomer && (
                    <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground transition group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-accent" />
                  )}
                </>
              );
              return canOpenCustomer ? (
                <Link
                  key={item.id}
                  to={`/customers/${item.customer_id}`}
                  className="group flex w-full items-start gap-4 px-5 py-4 transition hover:bg-muted/40"
                >
                  {content}
                </Link>
              ) : (
                <div key={item.id} className="flex w-full items-start gap-4 px-5 py-4">
                  {content}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
