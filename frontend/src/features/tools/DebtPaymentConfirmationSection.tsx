import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Save, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { DebtPaymentSettings, GroupMember } from "../../api/types";
import { Button } from "../../components/ui/Button";
import { initials } from "../../lib/format";

export function DebtPaymentConfirmationSection() {
  const queryClient = useQueryClient();
  const [members, setMembers] = useState<GroupMember[]>([]);
  const [notificationTargets, setNotificationTargets] = useState<GroupMember[]>([]);
  const [phrases, setPhrases] = useState("");
  const [picking, setPicking] = useState<"tracked" | "notification" | null>(null);
  const [search, setSearch] = useState("");

  const settings = useQuery({
    queryKey: ["debt-payment-confirmation-settings"],
    queryFn: () =>
      api<DebtPaymentSettings>("/tools/debt-payment-confirmation"),
  });
  const candidates = useQuery({
    queryKey: ["debt-payment-confirmation-candidates"],
    queryFn: () =>
      api<GroupMember[]>("/tools/debt-payment-confirmation/candidates"),
    enabled: picking !== null,
    staleTime: 5 * 60_000,
    retry: false,
  });

  useEffect(() => {
    if (!settings.data) return;
    setMembers(settings.data.tracked_members);
    setNotificationTargets(settings.data.notification_targets);
    setPhrases(settings.data.phrases.join("\n"));
  }, [settings.data]);

  const selected = new Set(
    (picking === "notification" ? notificationTargets : members).map(
      (member) => member.user_id,
    ),
  );
  const needle = search.trim().toLocaleLowerCase("vi");
  const suggestions = (candidates.data ?? [])
    .filter((member) => !selected.has(member.user_id))
    .filter(
      (member) =>
        !needle || member.display_name.toLocaleLowerCase("vi").includes(needle),
    )
    .slice(0, 60);

  const save = useMutation({
    mutationFn: () =>
      api<DebtPaymentSettings>("/tools/debt-payment-confirmation", {
        method: "PUT",
        body: JSON.stringify({
          tracked_members: members,
          notification_targets: notificationTargets,
          phrases: phrases
            .split("\n")
            .map((phrase) => phrase.trim())
            .filter(Boolean),
        }),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["debt-payment-confirmation-settings"], data);
      setMembers(data.tracked_members);
      setNotificationTargets(data.notification_targets);
      setPhrases(data.phrases.join("\n"));
    },
  });

  const error = settings.error ?? candidates.error ?? save.error;
  const renderPicker = (kind: "tracked" | "notification") => {
    if (picking !== kind) return null;
    const add = kind === "tracked" ? setMembers : setNotificationTargets;
    return (
      <div className="mt-4 rounded-xl border border-border bg-muted/30 p-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            className="field pl-10"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Tìm trong thành viên của tất cả khách hàng..."
          />
        </div>
        {candidates.isLoading ? (
          <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Đang lấy thành viên từ
            Zalo...
          </p>
        ) : (
          <div className="app-scrollbar mt-3 max-h-64 overflow-auto">
            {suggestions.map((member) => (
              <button
                key={member.user_id}
                type="button"
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-card"
                onClick={() => add((current) => [...current, member])}
              >
                <Avatar member={member} />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {member.display_name}
                </span>
                <Plus className="h-4 w-4 text-muted-foreground" />
              </button>
            ))}
            {suggestions.length === 0 && (
              <p className="py-5 text-center text-sm text-muted-foreground">
                Không còn ai để thêm.
              </p>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {error && (
        <p className="rounded-xl border border-danger-border bg-danger-bg p-4 text-sm text-danger-fg">
          {error instanceof ApiError
            ? error.message
            : "Không tải hoặc lưu được cấu hình."}
        </p>
      )}
      {save.isSuccess && (
        <p className="rounded-xl border border-success-border bg-success-bg p-4 text-sm text-success-fg">
          Đã lưu cấu hình tự động ghi nhận thanh toán.
        </p>
      )}

      <section>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-display text-xl">Người được theo dõi</h3>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              Chỉ tin nhắn của những người này mới được phép tự động chuyển công
              nợ sang đã thanh toán.
            </p>
          </div>
          <button
            type="button"
            onClick={() =>
              setPicking((value) => (value === "tracked" ? null : "tracked"))
            }
            className="inline-flex shrink-0 items-center gap-1.5 text-sm font-medium text-accent"
          >
            <Plus className="h-4 w-4" />
            {picking === "tracked" ? "Đóng" : "Thêm người"}
          </button>
        </div>

        {renderPicker("tracked")}
        <SelectedMembers
          members={members}
          empty="Chưa chọn người nào nên tính năng chưa thể tự chuyển trạng thái."
          onChange={setMembers}
        />
      </section>

      <section className="border-t border-border pt-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-display text-xl">Người được tag cập nhật công nợ</h3>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              Sau khi xác nhận thanh toán, bot tag những người này và gửi kèm link
              công nợ của khách hàng.
            </p>
          </div>
          <button
            type="button"
            onClick={() =>
              setPicking((value) =>
                value === "notification" ? null : "notification",
              )
            }
            className="inline-flex shrink-0 items-center gap-1.5 text-sm font-medium text-accent"
          >
            <Plus className="h-4 w-4" />
            {picking === "notification" ? "Đóng" : "Thêm người"}
          </button>
        </div>
        {renderPicker("notification")}
        <SelectedMembers
          members={notificationTargets}
          empty="Chưa chọn người nhận nên bot sẽ không gửi thông báo sau khi xác nhận."
          onChange={setNotificationTargets}
        />
      </section>

      <section className="border-t border-border pt-6">
        <h3 className="font-display text-xl">Câu xác nhận thanh toán</h3>
        <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
          Mỗi dòng một câu. Hệ thống tìm câu này bên trong tin nhắn, không phân
          biệt chữ hoa/thường, dấu câu hoặc khoảng trắng; dấu tiếng Việt vẫn được
          phân biệt.
        </p>
        <textarea
          className="mt-4 min-h-52 w-full resize-y rounded-xl border border-border bg-muted/30 p-4 text-sm leading-7 outline-none focus:border-accent focus:ring-2 focus:ring-accent/15"
          value={phrases}
          onChange={(event) => setPhrases(event.target.value)}
          placeholder={"đã thanh toán\nđã tt\nda thanh toan"}
          aria-label="Các câu xác nhận thanh toán"
        />
      </section>

      <div className="flex justify-end border-t border-border pt-5">
        <Button
          onClick={() => save.mutate()}
          loading={save.isPending}
          disabled={settings.isLoading}
        >
          <Save className="h-4 w-4" /> Lưu cấu hình
        </Button>
      </div>
    </div>
  );
}

function SelectedMembers({
  members,
  empty,
  onChange,
}: {
  members: GroupMember[];
  empty: string;
  onChange: (members: GroupMember[]) => void;
}) {
  return (
    <div className="mt-4 divide-y divide-border rounded-xl border border-border">
      {members.length === 0 && (
        <p className="p-5 text-center text-sm text-muted-foreground">{empty}</p>
      )}
      {members.map((member) => (
        <div key={member.user_id} className="flex items-center gap-3 p-3.5">
          <Avatar member={member} />
          <span className="min-w-0 flex-1 truncate text-sm font-medium">
            {member.display_name}
          </span>
          <button
            type="button"
            onClick={() =>
              onChange(members.filter((item) => item.user_id !== member.user_id))
            }
            className="rounded-lg p-2 text-muted-foreground hover:bg-danger-bg hover:text-danger-fg"
            aria-label={`Bỏ ${member.display_name}`}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}

function Avatar({ member }: { member: GroupMember }) {
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-accent-soft text-xs font-bold text-accent">
      {member.avatar_url ? (
        <img
          src={member.avatar_url}
          alt=""
          className="h-full w-full object-cover"
        />
      ) : (
        initials(member.display_name)
      )}
    </span>
  );
}
