import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Pencil, Plus, RefreshCw, ShieldCheck, Trash2, UserPlus, UsersRound } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { Role, User } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { RoleModal } from "../features/users/RoleModal";
import { UserModal } from "../features/users/UserModal";
import { formatDate, initials } from "../lib/format";
import { PERMISSIONS } from "../lib/permissions";
import { usePermissions, useSession } from "../lib/session";

export function UsersPage() {
  const session = useSession();
  const { can } = usePermissions();
  const queryClient = useQueryClient();
  const [userModal, setUserModal] = useState<{ user: User | null } | null>(null);
  const [roleModal, setRoleModal] = useState<{ role: Role | null } | null>(null);
  const [pendingDelete, setPendingDelete] = useState<User | null>(null);
  const [pendingRoleDelete, setPendingRoleDelete] = useState<Role | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const users = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
  const roles = useQuery({
    queryKey: ["roles"],
    queryFn: () => api<Role[]>("/roles"),
    enabled: can(PERMISSIONS.roleRead),
  });

  const removeUser = useMutation({
    mutationFn: (user: User) => api<void>(`/users/${user.id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
      setPendingDelete(null);
    },
    onError: (error) => setActionError(error instanceof ApiError ? error.message : "Không thể xóa người dùng."),
  });

  const removeRole = useMutation({
    mutationFn: (role: Role) => api<void>(`/roles/${role.id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
      setPendingRoleDelete(null);
    },
    onError: (error) => setActionError(error instanceof ApiError ? error.message : "Không thể xóa vai trò."),
  });

  const roleOptions = roles.data ?? [];

  return <div className="mx-auto max-w-[1400px]">
    <PageHeader
      eyebrow="Access control"
      title="Người"
      highlight="dùng"
      description="Quản lý tài khoản đăng nhập và phân quyền theo từng chức năng của hệ thống."
      action={can(PERMISSIONS.userCreate) ? <Button disabled={roleOptions.length === 0} onClick={() => { setActionError(null); setUserModal({ user: null }); }}><UserPlus className="h-4 w-4" />Thêm người dùng</Button> : undefined}
    />

    {actionError && <div className="mb-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700" role="alert">{actionError}</div>}

    <section className="card mb-6">
      <div className="border-b border-border p-4">
        <h2 className="text-base font-semibold">Tài khoản</h2>
        <p className="mt-1 text-xs text-muted-foreground">Mỗi tài khoản nhận quyền thông qua vai trò được gán.</p>
      </div>
      <div className="app-scrollbar overflow-x-auto">
        <table className="w-full min-w-[860px] table-fixed border-collapse text-left">
          <thead>
            <tr className="border-b border-border bg-muted/50 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              <th className="w-[30%] px-6 py-4 font-medium">Người dùng</th>
              <th className="w-[22%] px-5 py-4 font-medium">Vai trò</th>
              <th className="w-[16%] px-5 py-4 font-medium">Trạng thái</th>
              <th className="w-[20%] px-5 py-4 font-medium">Tạo lúc</th>
              <th className="w-[12%] px-5 py-4 font-medium">Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {users.isLoading && <tr><td colSpan={5} className="px-6 py-14 text-center text-sm text-muted-foreground"><RefreshCw className="mx-auto mb-3 h-5 w-5 animate-spin text-accent" />Đang tải danh sách người dùng...</td></tr>}
            {users.isError && <tr><td colSpan={5} className="px-6 py-14 text-center text-sm text-red-600">Không thể tải danh sách người dùng.</td></tr>}
            {users.data?.map((user) => {
              const isSelf = user.id === session.id;
              return <tr key={user.id} className="border-b border-border transition-colors last:border-0 hover:bg-blue-50/40">
                <td className="px-6 py-4">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-100 to-indigo-100 text-xs font-bold text-accent">{initials(user.full_name || user.email)}</span>
                    <span className="min-w-0">
                      <span className="block truncate font-semibold">{user.full_name || "—"}{isSelf && <span className="ml-2 rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-accent">Bạn</span>}</span>
                      <span className="block truncate text-xs text-muted-foreground">{user.email}</span>
                    </span>
                  </div>
                </td>
                <td className="px-5 py-4">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                    <ShieldCheck className="h-3 w-3 text-accent" />{user.role.name}
                  </span>
                </td>
                <td className="px-5 py-4">
                  <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${user.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-200 text-slate-600"}`}>
                    {user.is_active ? "Đang hoạt động" : "Đã vô hiệu hóa"}
                  </span>
                </td>
                <td className="whitespace-nowrap px-5 py-4 text-sm text-muted-foreground">{formatDate(user.created_at, false)}</td>
                <td className="px-5 py-4">
                  <div className="flex items-center gap-1">
                    {can(PERMISSIONS.userUpdate) && <button type="button" title="Sửa người dùng" aria-label={`Sửa ${user.email}`} className="rounded-lg p-2 text-muted-foreground transition hover:bg-muted hover:text-accent" onClick={() => { setActionError(null); setUserModal({ user }); }}><Pencil className="h-4 w-4" /></button>}
                    {can(PERMISSIONS.userDelete) && <button type="button" title={isSelf ? "Không thể tự xóa" : "Xóa người dùng"} aria-label={`Xóa ${user.email}`} disabled={isSelf} className="rounded-lg p-2 text-muted-foreground transition hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-30" onClick={() => { setActionError(null); setPendingDelete(user); }}><Trash2 className="h-4 w-4" /></button>}
                  </div>
                </td>
              </tr>;
            })}
            {!users.isLoading && users.data?.length === 0 && <tr><td colSpan={5} className="px-6 py-14 text-center text-sm text-muted-foreground">Chưa có người dùng nào.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>

    {can(PERMISSIONS.roleRead) && <section className="card">
      <div className="flex flex-col gap-3 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-semibold">Vai trò</h2>
          <p className="mt-1 text-xs text-muted-foreground">Vai trò hệ thống được khóa để bảo đảm quyền luôn khớp với API.</p>
        </div>
        {can(PERMISSIONS.roleManage) && <Button variant="secondary" className="shrink-0" onClick={() => { setActionError(null); setRoleModal({ role: null }); }}><Plus className="h-4 w-4" />Tạo vai trò</Button>}
      </div>
      <div className="grid gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
        {roles.isLoading && <p className="p-6 text-sm text-muted-foreground">Đang tải vai trò...</p>}
        {roles.data?.map((role) => <article key={role.id} className="flex flex-col rounded-xl border border-border bg-muted/20 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="flex items-center gap-2 truncate font-semibold">{role.name}{role.is_system && <Lock className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}</h3>
              <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">{role.code}</p>
            </div>
            {can(PERMISSIONS.roleManage) && !role.is_system && <div className="flex shrink-0 items-center gap-1">
              <button type="button" title="Sửa vai trò" aria-label={`Sửa vai trò ${role.name}`} className="rounded-lg p-1.5 text-muted-foreground transition hover:bg-white hover:text-accent" onClick={() => { setActionError(null); setRoleModal({ role }); }}><Pencil className="h-3.5 w-3.5" /></button>
              <button type="button" title="Xóa vai trò" aria-label={`Xóa vai trò ${role.name}`} className="rounded-lg p-1.5 text-muted-foreground transition hover:bg-red-50 hover:text-red-600" onClick={() => { setActionError(null); setPendingRoleDelete(role); }}><Trash2 className="h-3.5 w-3.5" /></button>
            </div>}
          </div>
          <p className="mt-3 flex-1 text-xs leading-relaxed text-muted-foreground">{role.description || "Không có mô tả."}</p>
          <div className="mt-4 flex items-center gap-4 border-t border-border pt-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5 text-accent" />{role.permissions.length} quyền</span>
            <span className="flex items-center gap-1.5"><UsersRound className="h-3.5 w-3.5 text-accent" />{role.user_count} người</span>
          </div>
        </article>)}
      </div>
    </section>}

    <UserModal
      open={userModal !== null}
      user={userModal?.user ?? null}
      roles={roleOptions}
      isSelf={userModal?.user?.id === session.id}
      onClose={() => setUserModal(null)}
    />
    <RoleModal open={roleModal !== null} role={roleModal?.role ?? null} onClose={() => setRoleModal(null)} />

    <Modal open={pendingDelete !== null} onClose={() => setPendingDelete(null)} className="max-w-md" title="Xóa người dùng" description="Tài khoản sẽ bị xóa vĩnh viễn và không thể đăng nhập lại.">
      <p className="text-sm leading-relaxed text-muted-foreground">Xóa tài khoản <strong className="text-foreground">{pendingDelete?.email}</strong>?</p>
      <div className="mt-7 flex justify-end gap-3">
        <Button variant="ghost" onClick={() => setPendingDelete(null)}>Hủy</Button>
        <Button variant="danger" loading={removeUser.isPending} onClick={() => pendingDelete && removeUser.mutate(pendingDelete)}>Xóa</Button>
      </div>
    </Modal>

    <Modal open={pendingRoleDelete !== null} onClose={() => setPendingRoleDelete(null)} className="max-w-md" title="Xóa vai trò" description="Chỉ có thể xóa vai trò chưa được gán cho người dùng nào.">
      <p className="text-sm leading-relaxed text-muted-foreground">Xóa vai trò <strong className="text-foreground">{pendingRoleDelete?.name}</strong>?</p>
      <div className="mt-7 flex justify-end gap-3">
        <Button variant="ghost" onClick={() => setPendingRoleDelete(null)}>Hủy</Button>
        <Button variant="danger" loading={removeRole.isPending} onClick={() => pendingRoleDelete && removeRole.mutate(pendingRoleDelete)}>Xóa</Button>
      </div>
    </Modal>
  </div>;
}
