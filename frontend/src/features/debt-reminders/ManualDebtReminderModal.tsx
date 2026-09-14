import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ExternalLink,
  FileImage,
  Link2,
  MessageSquareText,
  Send,
} from "lucide-react";
import { useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { DebtReminder, DebtReminderTrigger } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

type Props = {
  customerId: string;
  customerName: string;
  debtFileUrl: string | null;
  open: boolean;
  onClose: () => void;
};

export function ManualDebtReminderModal({
  customerId,
  customerName,
  debtFileUrl,
  open,
  onClose,
}: Props) {
  const queryClient = useQueryClient();
  const [queued, setQueued] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const reminder = useQuery({
    queryKey: ["debt-reminder", customerId],
    queryFn: () => api<DebtReminder>(`/customers/${customerId}/debt-reminder`),
    enabled: open,
    refetchOnWindowFocus: false,
  });
  const message = useMemo(
    () =>
      (reminder.data?.message_parts ?? [])
        .map((part) =>
          part.type === "mention" ? `@${part.display_name}` : part.text,
        )
        .join(""),
    [reminder.data],
  );
  const sendNow = useMutation({
    mutationFn: () =>
      api<DebtReminderTrigger>(
        `/customers/${customerId}/debt-reminder/send-now`,
        { method: "POST", body: JSON.stringify({ request_id: requestId }) },
      ),
    onSuccess: () => {
      setQueued(true);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["debt-reminder", customerId] });
      void queryClient.invalidateQueries({ queryKey: ["debt-reminder-history"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["activity"] });
    },
    onError: (cause) => {
      setError(
        cause instanceof ApiError || cause instanceof Error
          ? cause.message
          : "Không thể bắt đầu gửi nhắc công nợ.",
      );
    },
  });

  const handleClose = () => {
    if (sendNow.isPending) return;
    setQueued(false);
    setError(null);
    sendNow.reset();
    setRequestId(crypto.randomUUID());
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Nhắc công nợ ngay"
      description={`Gửi ngay bộ nhắc công nợ đã cấu hình tới ${customerName}.`}
    >
      {queued ? (
        <div className="text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-success-bg text-success-fg">
            <CheckCircle2 className="h-7 w-7" />
          </span>
          <h3 className="mt-4 text-base font-semibold">Đã bắt đầu gửi</h3>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Bot đang gửi ảnh công nợ, link Google Sheet và nội dung nhắc. Lịch tự
            động tiếp theo vẫn được giữ nguyên.
          </p>
          <Button className="mt-6 w-full" onClick={handleClose}>
            Đóng
          </Button>
        </div>
      ) : reminder.isLoading ? (
        <div className="py-12 text-center text-sm text-muted-foreground">
          Đang tải nội dung nhắc công nợ...
        </div>
      ) : reminder.isError ? (
        <div className="rounded-xl border border-danger-border bg-danger-bg p-4 text-sm text-danger-fg">
          Không thể tải cấu hình nhắc công nợ.
        </div>
      ) : (
        <div className="space-y-5">
          <div className="rounded-xl border border-border bg-muted/30 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Sẽ gửi theo thứ tự
            </p>
            <ol className="mt-3 space-y-3 text-sm">
              <li className="flex items-center gap-3">
                <FileImage className="h-4 w-4 shrink-0 text-accent" />
                Ảnh tab đầu tiên của file công nợ
              </li>
              <li className="flex items-center gap-3">
                <Link2 className="h-4 w-4 shrink-0 text-accent" />
                <span className="min-w-0 flex-1">Link Google Sheet</span>
                {debtFileUrl && (
                  <a
                    href={debtFileUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-accent hover:underline"
                  >
                    Xem file <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </li>
              <li className="flex items-start gap-3">
                <MessageSquareText className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                <span className="min-w-0 whitespace-pre-wrap break-words leading-relaxed">
                  {message || "Chưa có nội dung nhắc."}
                </span>
              </li>
            </ol>
          </div>

          <div className="rounded-xl border border-warning-border bg-warning-bg px-4 py-3 text-sm leading-relaxed text-warning-fg">
            Lượt này gửi ngay cả khi hôm nay là ngày tạm ngừng nhắc theo lịch và
            không thay đổi lịch tự động tiếp theo.
          </div>

          {error && (
            <div className="rounded-xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-3">
            <Button variant="ghost" onClick={handleClose} disabled={sendNow.isPending}>
              Hủy
            </Button>
            <Button
              onClick={() => sendNow.mutate()}
              loading={sendNow.isPending}
              disabled={!message.trim()}
            >
              <Send className="h-4 w-4" />
              Gửi nhắc ngay
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
