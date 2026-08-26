import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AtSign, ChevronDown, Tag } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import type {
  GroupMember,
  MentionAutomation,
  MentionTimeWindow,
  MentionTarget,
} from "../../api/types";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import { PERMISSIONS } from "../../lib/permissions";
import { usePermissions } from "../../lib/session";
import {
  DelayField,
  FeatureSection,
  TargetPicker,
  TimeWindowsField,
  defaultTimeWindows,
  mergeTimeWindows,
  splitDelay,
  toDelayMinutes,
  type DelayUnit,
} from "./MentionConfigForm";

type Props = {
  customerId: string;
  customerName: string;
  open: boolean;
  onClose: () => void;
};

export function MentionAutomationModal({
  customerId,
  customerName,
  open,
  onClose,
}: Props) {
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const canEdit = can(PERMISSIONS.mentionUpdate);
  const [selected, setSelected] = useState<MentionTarget[]>([]);
  const [priceSelected, setPriceSelected] = useState<MentionTarget[]>([]);
  const [mentionTagEnabled, setMentionTagEnabled] = useState(false);
  const [priceInquiryEnabled, setPriceInquiryEnabled] = useState(false);
  const [delayValue, setDelayValue] = useState<number | "">(2);
  const [delayUnit, setDelayUnit] = useState<DelayUnit>("hours");
  const [activeWindows, setActiveWindows] = useState<MentionTimeWindow[]>(
    defaultTimeWindows,
  );
  const [explanationOpen, setExplanationOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const automation = useQuery({
    queryKey: ["mention-automation", customerId],
    queryFn: () => api<MentionAutomation>(`/customers/${customerId}/mention-automation`),
    enabled: open,
    refetchOnWindowFocus: false,
  });
  const members = useQuery({
    queryKey: ["customer-members", customerId],
    queryFn: () => api<GroupMember[]>(`/customers/${customerId}/members`),
    enabled: open,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (!open || !automation.data) return;
    const delay = splitDelay(automation.data.delay_minutes);
    setSelected(automation.data.targets);
    setPriceSelected(automation.data.price_targets);
    setDelayValue(delay.value);
    setDelayUnit(delay.unit);
    setActiveWindows(automation.data.active_windows);
    setMentionTagEnabled(automation.data.mention_tag_enabled);
    setPriceInquiryEnabled(automation.data.price_inquiry_enabled);
    setFormError(null);
  }, [automation.data, open]);

  const delayMinutes = toDelayMinutes(delayValue, delayUnit);

  const save = useMutation({
    mutationFn: () => {
      if (!Number.isFinite(delayMinutes) || delayMinutes < 1 || delayMinutes > 10_080) {
        throw new Error("Thời gian chờ phải từ 1 phút đến 7 ngày.");
      }
      const normalizedWindows = mergeTimeWindows(activeWindows);
      if (!normalizedWindows) {
        throw new Error(
          "Hãy nhập đầy đủ khung giờ và đảm bảo giờ bắt đầu sớm hơn giờ kết thúc.",
        );
      }
      return api<MentionAutomation>(`/customers/${customerId}/mention-automation`, {
        method: "PUT",
        body: JSON.stringify({
          mention_tag_enabled: mentionTagEnabled,
          price_inquiry_enabled: priceInquiryEnabled,
          delay_minutes: delayMinutes,
          active_windows: normalizedWindows,
          targets: mentionTagEnabled ? selected : [],
          price_targets: priceInquiryEnabled ? priceSelected : [],
        }),
      });
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["mention-automation", customerId], data);
      onClose();
    },
    onError: (error) => {
      setFormError(
        error instanceof ApiError || error instanceof Error
          ? error.message
          : "Không thể lưu cấu hình.",
      );
    },
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      className="max-w-4xl"
      title="Tag tên tự động"
      description={`Thiết lập nhắc lại tên thành viên trong ${customerName}.`}
    >
      {automation.isLoading ? (
        <div className="flex min-h-72 items-center justify-center text-sm text-muted-foreground">
          Đang tải cấu hình...
        </div>
      ) : automation.isError ? (
        <div className="rounded-xl border border-danger-border bg-danger-bg p-6 text-center">
          <p className="text-sm text-danger-fg">Không thể tải cấu hình tag tên.</p>
          <Button
            variant="secondary"
            className="mt-4"
            onClick={() => void automation.refetch()}
          >
            Thử lại
          </Button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="rounded-xl border border-info-border bg-info-bg p-4">
            <button
              type="button"
              className="flex w-full items-center gap-3 text-left"
              aria-expanded={explanationOpen}
              onClick={() => setExplanationOpen((current) => !current)}
            >
              <AtSign className="h-5 w-5 shrink-0 text-accent" />
              <span className="flex-1 text-sm font-semibold text-foreground">
                Giải thích cách hoạt động
              </span>
              <ChevronDown
                className={`h-4 w-4 text-muted-foreground transition ${explanationOpen ? "rotate-180" : ""}`}
              />
            </button>
            {explanationOpen && (
              <p className="mt-3 border-t border-info-border pt-3 text-sm leading-relaxed text-foreground">
                <strong>Tag lại khi có người tag:</strong> ai đó tag một thành viên đã
                chọn thì bot đợi theo thời gian bên dưới rồi tag lại đúng người đó, lặp
                lại cho tới khi chính người đó gửi bất kỳ tin nhắn nào hoặc thả tim/like
                vào bất kỳ tin nhắn nào trong nhóm. Câu chỉ có “ok”, “cảm ơn”… được bỏ
                qua bằng luật; phần còn lại do AI đọc context rồi quyết định. AI lỗi thì
                vẫn tag như bình thường.
                <br />
                <br />
                <strong>Tag khi khách hỏi giá:</strong> khách — người không nằm trong
                danh sách tag — nhắn câu có “giá”, “bgia”, “baogia” hoặc “bao gia” thì AI đọc
                xem có phải đang hỏi giá thật không. “Đánh giá”, “giá trị”, “giá đỡ”…
                sẽ bị loại. Chỉ khi AI đủ chắc mới tag người phụ trách báo giá. Ngược
                lại với trên: AI lỗi thì <strong>không tag ai</strong>, vì không có ai
                tag trước cả.
                <br />
                <br />
                Tin nhắn do bot gửi không tạo vòng tag mới. Khung giờ và thời gian chờ
                dùng chung cho cả hai.
              </p>
            )}
          </div>

          <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
          <div className="divide-y divide-border rounded-xl border border-border">
            <FeatureSection
              icon={AtSign}
              title="Tag lại khi có người tag"
              hint="Bot nhắc lại đến khi người được tag nhắn hoặc thả tim/like trong nhóm."
              enabled={mentionTagEnabled}
              onToggle={() => { setMentionTagEnabled((on) => !on); setFormError(null); }}
              disabled={!canEdit}
            >
              <TargetPicker
                label="Người cần tag lại"
                selected={selected}
                onChange={setSelected}
                members={members.data ?? []}
                loading={members.isLoading}
                errorMessage={
                  members.isError
                    ? "Không thể lấy thành viên. Hãy kiểm tra kết nối bot rồi thử lại."
                    : null
                }
                disabled={!canEdit}
                onDirty={() => setFormError(null)}
              />
            </FeatureSection>

            <FeatureSection
              icon={Tag}
              title="Tag khi khách hỏi giá"
              hint="Khách nhắn có “giá”, “bgia”, “baogia” hoặc “bao gia” thì AI đọc xem có phải hỏi giá thật không, đúng mới tag. AI lỗi thì bỏ qua, không tag."
              enabled={priceInquiryEnabled}
              onToggle={() => { setPriceInquiryEnabled((on) => !on); setFormError(null); }}
              disabled={!canEdit}
            >
              <TargetPicker
                label="Người phụ trách báo giá"
                selected={priceSelected}
                onChange={setPriceSelected}
                members={members.data ?? []}
                loading={members.isLoading}
                errorMessage={
                  members.isError
                    ? "Không thể lấy thành viên. Hãy kiểm tra kết nối bot rồi thử lại."
                    : null
                }
                disabled={!canEdit}
                onDirty={() => setFormError(null)}
              />
            </FeatureSection>
          </div>

          <div className="space-y-6">
            <TimeWindowsField
              windows={activeWindows}
              onChange={setActiveWindows}
              disabled={!canEdit}
              onDirty={() => setFormError(null)}
            />

            <DelayField
              value={delayValue}
              unit={delayUnit}
              onChange={(value, unit) => {
                setDelayValue(value);
                setDelayUnit(unit);
              }}
              disabled={!canEdit}
              onDirty={() => setFormError(null)}
            />
          </div>
          </div>

          {automation.data && automation.data.pending_followups > 0 && (
            <p className="rounded-xl border border-warning-border bg-warning-bg px-4 py-3 text-xs text-warning-fg">
              Có {automation.data.pending_followups} vòng nhắc đang hoạt động. Chỉ những
              vòng nhắc dành cho người bị bỏ khỏi danh sách mới bị hủy; đổi khung giờ,
              thời gian chờ hay thêm người thì các vòng còn lại vẫn chạy tiếp.
            </p>
          )}
          {formError && (
            <p className="rounded-xl border border-danger-border bg-danger-bg px-4 py-3 text-sm text-danger-fg">
              {formError}
            </p>
          )}

          {!canEdit && (
            <p className="rounded-xl border border-warning-border bg-warning-bg px-4 py-3 text-sm text-warning-fg">
              Vai trò của bạn chỉ được xem cấu hình tag tên tự động.
            </p>
          )}
          <div className="flex justify-end gap-3 border-t border-border pt-5">
            <Button variant="ghost" onClick={onClose}>Đóng</Button>
            <Button loading={save.isPending} disabled={!canEdit} onClick={() => save.mutate()}>
              Lưu cấu hình
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}


/** One row per automation, collapsing its target list away while switched off. */
