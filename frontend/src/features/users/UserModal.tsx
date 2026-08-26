import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { Role, User } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

type Props = {
  /** null means "create a new account". */
  user: User | null;
  roles: Role[];
  open: boolean;
  isSelf: boolean;
  onClose: () => void;
};

const MIN_PASSWORD = 8;

export function UserModal({ user, roles, open, isSelf, onClose }: Props) {
  const queryClient = useQueryClient();
  const editing = user !== null;
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [roleId, setRoleId] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setEmail(user?.email ?? "");
    setFullName(user?.full_name ?? "");
    setPassword("");
    setRoleId(user?.role.id ?? roles[0]?.id ?? "");
    setIsActive(user?.is_active ?? true);
    setError(null);
  }, [open, user, roles]);

  const save = useMutation({
    mutationFn: () => {
      if (!roleId) throw new Error("Hãy chọn vai trò cho người dùng.");
      if (!editing) {
        if (!email.trim()) throw new Error("Email không được để trống.");
        if (password.length < MIN_PASSWORD) {
          throw new Error(`Mật khẩu phải có ít nhất ${MIN_PASSWORD} ký tự.`);
        }
        return api<User>("/users", {
          method: "POST",
          body: JSON.stringify({
            email: email.trim(),
            full_name: fullName.trim() || null,
            password,
            role_id: roleId,
            is_active: isActive,
          }),
        });
      }
      if (password && password.length < MIN_PASSWORD) {
        throw new Error(`Mật khẩu mới phải có ít nhất ${MIN_PASSWORD} ký tự.`);
      }
      const body: Record<string, unknown> = { full_name: fullName.trim() || null };
      if (password) body.password = password;
      if (!isSelf) {
        body.role_id = roleId;
        body.is_active = isActive;
      }
      return api<User>(`/users/${user.id}`, { method: "PATCH", body: JSON.stringify(body) });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
      if (isSelf) void queryClient.invalidateQueries({ queryKey: ["me"] });
      onClose();
    },
    onError: (mutationError) => {
      setError(
        mutationError instanceof ApiError || mutationError instanceof Error
          ? mutationError.message
          : "Không thể lưu người dùng.",
      );
    },
  });

  const selectedRole = roles.find((role) => role.id === roleId);

  return (
    <Modal
      open={open}
      onClose={onClose}
      className="max-w-lg"
      title={editing ? "Sửa người dùng" : "Thêm người dùng"}
      description={
        editing
          ? "Cập nhật thông tin, vai trò hoặc đặt lại mật khẩu cho tài khoản này."
          : "Tạo tài khoản mới và gán vai trò để quyết định phạm vi truy cập."
      }
    >
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        <label className="block">
          <span className="mb-2 block text-sm font-semibold">Email</span>
          <input
            className="field disabled:bg-muted/60 disabled:text-muted-foreground"
            type="email"
            autoComplete="off"
            disabled={editing}
            value={email}
            onChange={(event) => { setEmail(event.target.value); setError(null); }}
          />
          {editing && <span className="mt-2 block text-xs text-muted-foreground">Email dùng để đăng nhập nên không thể thay đổi.</span>}
        </label>

        <label className="block">
          <span className="mb-2 block text-sm font-semibold">Tên hiển thị</span>
          <input
            className="field"
            maxLength={255}
            placeholder="Ví dụ: Nguyễn Văn A"
            value={fullName}
            onChange={(event) => { setFullName(event.target.value); setError(null); }}
          />
        </label>

        <label className="block">
          <span className="mb-2 block text-sm font-semibold">
            {editing ? "Đặt lại mật khẩu" : "Mật khẩu"}
          </span>
          <input
            className="field"
            type="password"
            autoComplete="new-password"
            placeholder={editing ? "Để trống nếu không đổi" : `Tối thiểu ${MIN_PASSWORD} ký tự`}
            value={password}
            onChange={(event) => { setPassword(event.target.value); setError(null); }}
          />
          {editing && <span className="mt-2 block text-xs text-muted-foreground">Đặt lại mật khẩu sẽ đăng xuất tất cả phiên của người dùng này.</span>}
        </label>

        <label className="block">
          <span className="mb-2 block text-sm font-semibold">Vai trò</span>
          <select
            className="field cursor-pointer disabled:cursor-not-allowed disabled:bg-muted/60"
            disabled={isSelf}
            value={roleId}
            onChange={(event) => { setRoleId(event.target.value); setError(null); }}
          >
            {roles.map((role) => (
              <option key={role.id} value={role.id}>{role.name}</option>
            ))}
          </select>
          {isSelf ? (
            <span className="mt-2 block text-xs text-muted-foreground">Bạn không thể tự thay đổi vai trò của mình.</span>
          ) : (
            selectedRole && <span className="mt-2 block text-xs text-muted-foreground">{selectedRole.description ?? `${selectedRole.permissions.length} quyền.`}</span>
          )}
        </label>

        <div>
          <span className="mb-2 block text-sm font-semibold">Trạng thái</span>
          <button
            type="button"
            role="switch"
            aria-checked={isActive}
            disabled={isSelf}
            onClick={() => { setIsActive((value) => !value); setError(null); }}
            className="flex min-h-11 w-full items-center justify-between rounded-xl border border-border bg-card px-4 disabled:cursor-not-allowed disabled:bg-muted/60"
          >
            <span className="text-sm">{isActive ? "Đang hoạt động" : "Đã vô hiệu hóa"}</span>
            <span className={`relative h-6 w-11 rounded-full transition ${isActive ? "bg-accent" : "bg-muted-foreground/40"}`}>
              <span className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition ${isActive ? "left-6" : "left-1"}`} />
            </span>
          </button>
          {isSelf && <span className="mt-2 block text-xs text-muted-foreground">Bạn không thể tự vô hiệu hóa tài khoản của mình.</span>}
        </div>

        {error && (
          <p className="rounded-xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-3 border-t border-border pt-5">
          <Button type="button" variant="ghost" onClick={onClose}>Hủy</Button>
          <Button type="submit" loading={save.isPending}>
            <Save className="h-4 w-4" />{editing ? "Lưu thay đổi" : "Tạo người dùng"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
