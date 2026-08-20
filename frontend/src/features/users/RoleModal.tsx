import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { Permission, Role } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

type Props = {
  /** null means "create a new role". */
  role: Role | null;
  open: boolean;
  onClose: () => void;
};

export function RoleModal({ role, open, onClose }: Props) {
  const queryClient = useQueryClient();
  const editing = role !== null;
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const catalog = useQuery({
    queryKey: ["permissions"],
    queryFn: () => api<Permission[]>("/roles/permissions"),
    enabled: open,
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    if (!open) return;
    setName(role?.name ?? "");
    setDescription(role?.description ?? "");
    setSelected(role?.permissions ?? []);
    setError(null);
  }, [open, role]);

  const grouped = useMemo(() => {
    const groups = new Map<string, Permission[]>();
    for (const permission of catalog.data ?? []) {
      const bucket = groups.get(permission.category) ?? [];
      bucket.push(permission);
      groups.set(permission.category, bucket);
    }
    return [...groups.entries()];
  }, [catalog.data]);

  const chosen = useMemo(() => new Set(selected), [selected]);

  const toggle = (code: string) => {
    setSelected((current) =>
      current.includes(code) ? current.filter((item) => item !== code) : [...current, code],
    );
    setError(null);
  };

  const save = useMutation({
    mutationFn: () => {
      if (!name.trim()) throw new Error("Tên vai trò không được để trống.");
      if (selected.length === 0) throw new Error("Vai trò phải có ít nhất một quyền.");
      const body = {
        name: name.trim(),
        description: description.trim() || null,
        permissions: selected,
      };
      return editing
        ? api<Role>(`/roles/${role.id}`, { method: "PATCH", body: JSON.stringify(body) })
        : api<Role>("/roles", { method: "POST", body: JSON.stringify(body) });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      void queryClient.invalidateQueries({ queryKey: ["me"] });
      onClose();
    },
    onError: (mutationError) => {
      setError(
        mutationError instanceof ApiError || mutationError instanceof Error
          ? mutationError.message
          : "Không thể lưu vai trò.",
      );
    },
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      className="max-w-2xl"
      title={editing ? "Sửa vai trò" : "Tạo vai trò"}
      description="Chọn đúng những quyền mà vai trò này được phép thực hiện."
    >
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          save.mutate();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-2 block text-sm font-semibold">Tên vai trò</span>
            <input
              autoFocus
              className="field"
              maxLength={255}
              placeholder="Ví dụ: Kế toán công nợ"
              value={name}
              onChange={(event) => { setName(event.target.value); setError(null); }}
            />
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-semibold">Mô tả</span>
            <input
              className="field"
              maxLength={1000}
              placeholder="Vai trò này dùng để làm gì?"
              value={description}
              onChange={(event) => { setDescription(event.target.value); setError(null); }}
            />
          </label>
        </div>

        <div>
          <div className="mb-3 flex items-center justify-between gap-4">
            <span className="text-sm font-semibold">Quyền truy cập</span>
            <span className="text-xs text-muted-foreground">Đã chọn {selected.length}</span>
          </div>
          {catalog.isLoading && (
            <p className="rounded-xl border border-border bg-muted/30 p-6 text-center text-sm text-muted-foreground">
              Đang tải danh sách quyền...
            </p>
          )}
          {catalog.isError && (
            <p className="rounded-xl border border-red-200 bg-red-50 p-6 text-center text-sm text-red-700">
              Không thể tải danh sách quyền.
            </p>
          )}
          <div className="app-scrollbar max-h-80 space-y-4 overflow-auto pr-1">
            {grouped.map(([category, permissions]) => {
              const codes = permissions.map((permission) => permission.code);
              const allChosen = codes.every((code) => chosen.has(code));
              return (
                <fieldset key={category} className="rounded-xl border border-border p-4">
                  <legend className="flex items-center gap-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <ShieldCheck className="h-3.5 w-3.5 text-accent" />{category}
                  </legend>
                  <button
                    type="button"
                    className="mb-2 text-xs font-medium text-accent hover:underline"
                    onClick={() => {
                      setSelected((current) =>
                        allChosen
                          ? current.filter((code) => !codes.includes(code))
                          : [...new Set([...current, ...codes])],
                      );
                      setError(null);
                    }}
                  >
                    {allChosen ? "Bỏ chọn tất cả" : "Chọn tất cả"}
                  </button>
                  <div className="space-y-1">
                    {permissions.map((permission) => (
                      <label
                        key={permission.code}
                        className="flex min-h-10 cursor-pointer items-center gap-3 rounded-lg px-2 text-sm hover:bg-muted"
                      >
                        <input
                          type="checkbox"
                          className="h-4 w-4 shrink-0 accent-blue-600"
                          checked={chosen.has(permission.code)}
                          onChange={() => toggle(permission.code)}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate">{permission.name}</span>
                          <span className="block truncate font-mono text-[10px] text-muted-foreground">{permission.code}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              );
            })}
          </div>
        </div>

        {error && (
          <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-3 border-t border-border pt-5">
          <Button type="button" variant="ghost" onClick={onClose}>Hủy</Button>
          <Button type="submit" loading={save.isPending}>
            <Save className="h-4 w-4" />{editing ? "Lưu vai trò" : "Tạo vai trò"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
