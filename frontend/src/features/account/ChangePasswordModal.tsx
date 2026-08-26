import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { User } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

const MIN_LENGTH = 8;

export function ChangePasswordModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!open) return;
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setError(null);
    setDone(false);
  }, [open]);

  const save = useMutation({
    mutationFn: () => {
      if (newPassword.length < MIN_LENGTH) {
        throw new Error(`Mật khẩu mới phải có ít nhất ${MIN_LENGTH} ký tự.`);
      }
      if (newPassword !== confirmPassword) {
        throw new Error("Mật khẩu nhập lại không khớp.");
      }
      if (newPassword === currentPassword) {
        throw new Error("Mật khẩu mới phải khác mật khẩu hiện tại.");
      }
      return api<User>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
    },
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
      setDone(true);
    },
    onError: (mutationError) => {
      setError(
        mutationError instanceof ApiError || mutationError instanceof Error
          ? mutationError.message
          : "Không thể đổi mật khẩu.",
      );
    },
  });

  const disabled = !currentPassword || !newPassword || !confirmPassword;

  return (
    <Modal
      open={open}
      onClose={onClose}
      className="max-w-md"
      title="Đổi mật khẩu"
      description="Các phiên đăng nhập khác của bạn sẽ bị đăng xuất sau khi đổi mật khẩu."
    >
      {done ? (
        <div className="text-center">
          <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-success-bg text-success-fg">
            <CheckCircle2 className="h-10 w-10" />
          </div>
          <p className="mt-5 text-sm leading-relaxed text-muted-foreground">
            Đã đổi mật khẩu thành công. Phiên hiện tại của bạn vẫn được giữ nguyên.
          </p>
          <Button className="mt-7 w-full" onClick={onClose}>Đóng</Button>
        </div>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            setError(null);
            save.mutate();
          }}
        >
          <label className="block">
            <span className="mb-2 block text-sm font-semibold">Mật khẩu hiện tại</span>
            <input
              autoFocus
              className="field"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => { setCurrentPassword(event.target.value); setError(null); }}
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-semibold">Mật khẩu mới</span>
            <input
              className="field"
              type="password"
              autoComplete="new-password"
              placeholder={`Tối thiểu ${MIN_LENGTH} ký tự`}
              value={newPassword}
              onChange={(event) => { setNewPassword(event.target.value); setError(null); }}
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-semibold">Nhập lại mật khẩu mới</span>
            <input
              className="field"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => { setConfirmPassword(event.target.value); setError(null); }}
            />
          </label>
          {error && (
            <p className="rounded-xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg" role="alert">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-3 border-t border-border pt-5">
            <Button type="button" variant="ghost" onClick={onClose}>Hủy</Button>
            <Button type="submit" loading={save.isPending} disabled={disabled}>
              <KeyRound className="h-4 w-4" />Đổi mật khẩu
            </Button>
          </div>
        </form>
      )}
    </Modal>
  );
}
