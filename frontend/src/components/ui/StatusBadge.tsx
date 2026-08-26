import { cn } from "../../lib/cn";

const labels: Record<string, string> = {
  CONNECTED: "Đã kết nối", DISCONNECTED: "Mất kết nối", CONNECTING: "Đang kết nối",
  AUTH_REQUIRED: "Cần xác thực", ERROR: "Có lỗi", SENT: "Đã gửi", FAILED: "Thất bại",
  SUCCEEDED: "Thành công", PROCESSING: "Đang gọi", SENDING: "Đang gửi", available: "Khả dụng", unavailable: "Không khả dụng",
};

export function StatusBadge({ status }: { status: string }) {
  const positive = ["CONNECTED", "SENT", "SUCCEEDED", "available"].includes(status);
  const pending = ["CONNECTING", "PROCESSING", "SENDING"].includes(status);
  return (
    <span className={cn(
      "inline-flex items-center gap-2 rounded-full px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider",
      positive && "bg-success-bg text-success-fg", pending && "bg-info-bg text-info-fg",
      !positive && !pending && "bg-danger-bg text-danger-fg",
    )}>
      <span className={cn("h-2 w-2 rounded-full", positive ? "bg-emerald-500" : pending ? "animate-pulse-soft bg-sky-500" : "bg-red-500")} />
      {labels[status] ?? status}
    </span>
  );
}
