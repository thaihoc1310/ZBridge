import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Minus, Plus, Search, Trash2, UserRound } from "lucide-react";
import { useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { GroupMember, StaffMember } from "../../api/types";
import { initials } from "../../lib/format";

/**
 * The people who get tagged, kept once for the whole company.
 *
 * Candidates come from every customer group in a single gateway call, so the
 * list is the union of who is actually reachable rather than a directory.
 */
export function StaffRosterSection({ canEdit }: { canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [picking, setPicking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const roster = useQuery({
    queryKey: ["staff"],
    queryFn: () => api<StaffMember[]>("/staff"),
  });
  const candidates = useQuery({
    queryKey: ["staff-candidates"],
    queryFn: () => api<GroupMember[]>("/staff/candidates"),
    enabled: picking,
    staleTime: 5 * 60_000,
    retry: false,
  });

  const save = useMutation({
    mutationFn: (members: StaffMember[]) =>
      api<StaffMember[]>("/staff", {
        method: "PUT",
        body: JSON.stringify({
          members: members.map((member) => ({
            user_id: member.user_id,
            display_name: member.display_name,
            avatar_url: member.avatar_url,
            note: member.note,
          })),
        }),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["staff"], data);
      setError(null);
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : "Không lưu được nhân sự."),
  });

  const current = useMemo(() => roster.data ?? [], [roster.data]);
  const currentIds = useMemo(
    () => new Set(current.map((member) => member.user_id)),
    [current],
  );
  const normalized = search.trim().toLowerCase();
  const suggestions = (candidates.data ?? [])
    .filter((member) => !currentIds.has(member.user_id))
    .filter(
      (member) => !normalized || member.display_name.toLowerCase().includes(normalized),
    )
    .slice(0, 60);

  const add = (member: GroupMember) =>
    save.mutate([
      ...current,
      { ...member, note: null, mention_customer_count: 0, price_customer_count: 0 },
    ]);
  const remove = (userId: string) =>
    save.mutate(current.filter((member) => member.user_id !== userId));

  return (
    <div>
      <div className="flex items-center justify-between gap-4">
        <span className="text-sm font-semibold">Đang có {current.length} người</span>
        {canEdit && (
          <button
            type="button"
            onClick={() => setPicking((open) => !open)}
            className="inline-flex items-center gap-1.5 rounded-lg px-1 py-1 text-sm font-medium text-muted-foreground transition hover:text-accent"
          >
            {picking ? <Minus className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            {picking ? "Đóng danh sách" : "Thêm người"}
          </button>
        )}
      </div>

      {error && (
        <p className="mt-4 rounded-xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg">
          {error}
        </p>
      )}

      {picking && (
        <div className="mt-5 rounded-xl border border-border bg-muted/30 p-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              className="field pl-10"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Tìm trong thành viên của tất cả khách hàng..."
            />
          </div>
          {candidates.isLoading && (
            <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Đang lấy thành viên từ Zalo...
            </p>
          )}
          {candidates.isError && (
            <p className="mt-4 text-sm text-danger-fg">
              {candidates.error instanceof ApiError
                ? candidates.error.message
                : "Không lấy được danh sách thành viên. Kiểm tra kết nối bot."}
            </p>
          )}
          {!candidates.isLoading && !candidates.isError && (
            <div className="app-scrollbar mt-3 max-h-72 overflow-auto">
              {suggestions.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  Không còn ai để thêm.
                </p>
              ) : (
                suggestions.map((member) => (
                  <button
                    key={member.user_id}
                    type="button"
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-card"
                    onClick={() => add(member)}
                  >
                    <StaffAvatar name={member.display_name} url={member.avatar_url} />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">
                      {member.display_name}
                    </span>
                    <Plus className="h-4 w-4 text-muted-foreground" />
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      )}

      <div className="mt-6 divide-y divide-border rounded-xl border border-border">
        {roster.isLoading && (
          <p className="p-6 text-center text-sm text-muted-foreground">Đang tải...</p>
        )}
        {!roster.isLoading && current.length === 0 && (
          <p className="p-6 text-center text-sm text-muted-foreground">
            Chưa có ai. Bấm “Thêm người” để chọn từ thành viên các nhóm khách hàng.
          </p>
        )}
        {current.map((member) => (
          <div key={member.user_id} className="flex items-center gap-3 p-3.5">
            <StaffAvatar name={member.display_name} url={member.avatar_url} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">
                {member.display_name}
              </span>
              <span className="block text-xs text-muted-foreground">
                {member.mention_customer_count + member.price_customer_count === 0
                  ? "Chưa dùng ở khách hàng nào"
                  : `Nhắc việc: ${member.mention_customer_count} khách hàng · Báo giá: ${member.price_customer_count}`}
              </span>
            </span>
            {canEdit && (
              <button
                type="button"
                aria-label={`Xoá ${member.display_name}`}
                disabled={save.isPending}
                className="rounded-lg p-2 text-muted-foreground transition hover:bg-danger-bg hover:text-danger-fg disabled:opacity-40"
                onClick={() => remove(member.user_id)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function StaffAvatar({ name, url }: { name: string; url: string | null }) {
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-gradient-to-br from-emerald-100 to-teal-100 text-xs font-semibold text-success-fg">
      {url ? (
        <img src={url} alt="" className="h-full w-full object-cover" />
      ) : name ? (
        initials(name)
      ) : (
        <UserRound className="h-4 w-4" />
      )}
    </span>
  );
}
