import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AtSign, BrainCircuit, Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { MentionClassifierSettings } from "../../api/types";
import { Button } from "../../components/ui/Button";

/** System-wide rules the classifier applies before and after the model runs. */
export function ClassifierPolicySection({ canUpdate }: { canUpdate: boolean }) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["mention-classifier-settings"],
    queryFn: () => api<MentionClassifierSettings>("/mention-settings"),
  });
  const [aiEnabled, setAiEnabled] = useState(true);
  const [bareMention, setBareMention] = useState(true);
  const [phrases, setPhrases] = useState("");

  useEffect(() => {
    if (!query.data) return;
    setAiEnabled(query.data.ai_classifier_enabled);
    setBareMention(query.data.bare_mention_requires_response);
    setPhrases(query.data.skip_phrases.join("\n"));
  }, [query.data]);

  const save = useMutation({
    mutationFn: () => api<MentionClassifierSettings>("/mention-settings", {
      method: "PUT",
      body: JSON.stringify({
        ai_classifier_enabled: aiEnabled,
        bare_mention_requires_response: bareMention,
        skip_phrases: phrases.split("\n").map((value) => value.trim()).filter(Boolean),
      }),
    }),
    onSuccess: (data) => queryClient.setQueryData(["mention-classifier-settings"], data),
  });

  const error = query.error ?? save.error;
  return <div className="space-y-5">
    {error && <div className="rounded-xl border border-danger-border bg-danger-bg p-4 text-sm text-danger-fg">{error instanceof ApiError ? error.message : "Không tải được cấu hình."}</div>}
    {save.isSuccess && <div className="flex items-center gap-2 rounded-xl border border-success-border bg-success-bg p-4 text-sm text-success-fg"><ShieldCheck className="h-4 w-4" />Đã cập nhật chính sách cho toàn hệ thống.</div>}

    <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
      <section>
        <div className="flex items-start gap-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-soft"><BrainCircuit className="h-5 w-5 text-accent" /></span>
          <div className="min-w-0 flex-1">
            <h2 className="font-display text-2xl">Bộ phân loại AI</h2>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">AI đọc tối đa 15 tin liên quan gần nhất và đọc lại trước mỗi lượt gửi. Chỉ NEED_RESPONSE từ 65% mới giữ vòng tag; ACKNOWLEDGEMENT, FYI và UNCERTAIN đều dừng. Nếu API lỗi, lượt gửi được hoãn để thử phân loại lại và không tag khi chưa có kết luận.</p>
          </div>
          <Toggle checked={aiEnabled} onChange={setAiEnabled} disabled={!canUpdate || query.isLoading} label="Bật bộ phân loại AI" />
        </div>

        <div className="my-7 border-t border-border" />
        <div className="flex items-start gap-4">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-violet-50 dark:bg-violet-500/15"><AtSign className="h-5 w-5 text-violet-600 dark:text-violet-300" /></span>
          <div className="min-w-0 flex-1">
            <h3 className="font-semibold">Bare mention luôn cần phản hồi</h3>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">Tin chỉ có <code className="rounded bg-muted px-1.5 py-0.5">@Tên</code> sẽ lên lịch ngay, phù hợp trường hợp câu hỏi nằm ở tin trước.</p>
          </div>
          <Toggle checked={bareMention} onChange={setBareMention} disabled={!canUpdate || query.isLoading} label="Bare mention cần phản hồi" />
        </div>
      </section>

      <section>
        <h2 className="font-display text-2xl">Câu bỏ qua nhanh</h2>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">Mỗi dòng một câu. Sau khi bỏ phần tag tên, nếu nội dung khớp chính xác thì hệ thống skip bằng rule, không gọi AI.</p>
        <textarea
          className="mt-5 min-h-72 w-full resize-y rounded-2xl border border-border bg-muted/30 p-4 text-sm leading-7 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/15 disabled:opacity-60"
          value={phrases}
          onChange={(event) => setPhrases(event.target.value)}
          disabled={!canUpdate || query.isLoading}
          placeholder={"ok\noke\ncảm ơn\nnhận được rồi"}
          aria-label="Các câu bỏ qua nhanh"
        />
        <p className="mt-3 text-xs text-muted-foreground">Không phân biệt chữ hoa/thường và khoảng trắng. Câu có thêm yêu cầu, ví dụ “ok, kiểm tra lại giúp anh”, không khớp rule và sẽ chuyển qua AI.</p>
      </section>
    </div>

    {canUpdate && <div className="flex justify-end border-t border-border pt-5">
      <Button onClick={() => save.mutate()} loading={save.isPending} disabled={query.isLoading}><Save className="h-4 w-4" />Lưu cấu hình</Button>
    </div>}
  </div>;
}

function Toggle({ checked, onChange, disabled, label }: { checked: boolean; onChange: (value: boolean) => void; disabled: boolean; label: string }) {
  return <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-label={label}
    disabled={disabled}
    onClick={() => onChange(!checked)}
    className={`relative mt-1 h-7 w-12 shrink-0 rounded-full transition disabled:opacity-50 ${checked ? "bg-accent" : "bg-muted-foreground/40"}`}
  >
    <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition ${checked ? "left-6" : "left-1"}`} />
  </button>;
}
