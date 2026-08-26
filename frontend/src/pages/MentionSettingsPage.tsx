import { useQuery } from "@tanstack/react-query";
import {
  BrainCircuit,
  ChevronRight,
  FileClock,
  FileSpreadsheet,
  Layers,
  ListTodo,
  ReceiptText,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import type { MentionClassifierSettings, StaffMember } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Modal } from "../components/ui/Modal";
import { BulkMentionSection } from "../features/mentions/BulkMentionSection";
import { ClassifierPolicySection } from "../features/mentions/ClassifierPolicySection";
import { StaffRosterSection } from "../features/mentions/StaffRosterSection";
import { ActiveMentionTasksPanel } from "../features/tools/ActiveMentionTasksPanel";
import { BulkDebtReminderSection } from "../features/tools/BulkDebtReminderSection";
import { DebtReminderHistoryPanel } from "../features/tools/DebtReminderHistoryPanel";
import { DriveConverterPanel } from "../features/tools/DriveConverterPanel";
import { PERMISSIONS } from "../lib/permissions";
import { usePermissions } from "../lib/session";

type Panel =
  | "staff"
  | "bulk"
  | "policy"
  | "tasks"
  | "debt-bulk"
  | "debt-history"
  | "drive";

export function MentionSettingsPage() {
  const { can } = usePermissions();
  // One grant per section: the roster is a list of names, one bulk apply
  // overwrites every customer, and the policy governs the classifier.
  const canPolicy = can(PERMISSIONS.mentionPolicyManage);
  const canStaff = can(PERMISSIONS.staffManage);
  const canBulk = can(PERMISSIONS.mentionBulkApply);
  const canTaskRead = can(PERMISSIONS.mentionFollowupRead);
  const canTaskCancel = can(PERMISSIONS.mentionFollowupCancel);
  const canDebtBulk = can(PERMISSIONS.debtReminderBulkApply);
  const canDebtHistory = can(PERMISSIONS.debtReminderHistoryRead);
  const canDrive = can(PERMISSIONS.driveConversionManage);
  const [panel, setPanel] = useState<Panel | null>(() => {
    const requested = new URLSearchParams(window.location.search).get("panel");
    return requested === "drive" && canDrive ? "drive" : null;
  });

  const roster = useQuery({
    queryKey: ["staff"],
    queryFn: () => api<StaffMember[]>("/staff"),
    enabled: canStaff || canBulk,
  });
  const policy = useQuery({
    queryKey: ["mention-classifier-settings"],
    queryFn: () => api<MentionClassifierSettings>("/mention-settings"),
    enabled: canPolicy,
  });

  const staffCount = roster.data?.length ?? 0;
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        eyebrow="Vận hành nâng cao"
        title="Công cụ"
        highlight="vận hành"
        description="Quản lý tag tự động, lịch nhắc công nợ và các tiện ích Google Drive của hệ thống."
      />

      <section>
        <h2 className="mb-3 text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
          Tag tên
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {canStaff && (
            <PanelCard
              icon={Users}
              tone="emerald"
              title="Nhân sự"
              description="Khai báo một lần những người có thể được tag, dùng lại ở mọi khách hàng."
              summary={roster.isLoading ? "Đang tải..." : `${staffCount} người`}
              onClick={() => setPanel("staff")}
            />
          )}
          {canBulk && (
            <PanelCard
              icon={Layers}
              tone="amber"
              title="Cấu hình chung tag"
              description="Áp một cấu hình tag cho nhiều khách hàng cùng lúc, ghi đè cấu hình cũ."
              summary="Ghi đè hàng loạt"
              onClick={() => setPanel("bulk")}
            />
          )}
          {canTaskRead && (
            <PanelCard
              icon={ListTodo}
              tone="purple"
              title="Vòng tag đang hoạt động"
              description="Xem các vòng đang chờ phản hồi và dừng thủ công khi cần."
              summary="Theo dõi trực tiếp"
              onClick={() => setPanel("tasks")}
            />
          )}
          {canPolicy && (
            <PanelCard
              icon={BrainCircuit}
              tone="blue"
              title="Chính sách phân loại"
              description="Bộ phân loại AI, bare mention và danh sách câu bỏ qua nhanh."
              summary={
                policy.isLoading
                  ? "Đang tải..."
                  : policy.data
                    ? `AI ${policy.data.ai_classifier_enabled ? "đang bật" : "đang tắt"} · ${policy.data.skip_phrases.length} câu bỏ qua`
                    : "Không tải được"
              }
              onClick={() => setPanel("policy")}
            />
          )}
        </div>
      </section>

      {(canDebtBulk || canDebtHistory) && (
        <section className="mt-8">
          <h2 className="mb-3 text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
            Công nợ
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {canDebtBulk && (
              <PanelCard
                icon={ReceiptText}
                tone="amber"
                title="Cấu hình chung công nợ"
                description="Áp ngày gửi, khoảng lặp và giờ gửi cho nhiều khách hàng."
                summary="Không ghi đè nội dung"
                onClick={() => setPanel("debt-bulk")}
              />
            )}
            {canDebtHistory && (
              <PanelCard
                icon={FileClock}
                tone="rose"
                title="Lịch sử nhắc công nợ"
                description="Theo dõi từng lượt gửi ảnh, link và nội dung nhắc."
                summary="Lưu 45 ngày"
                onClick={() => setPanel("debt-history")}
              />
            )}
          </div>
        </section>
      )}

      {canDrive && (
        <section className="mt-8">
          <h2 className="mb-3 text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">
            Google Drive
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <PanelCard
              icon={FileSpreadsheet}
              tone="emerald"
              title="Chuyển Excel sang Google Sheets"
              description="Quét XLSX trong folder và folder con, sau đó chuyển đổi hàng loạt."
              summary="Chạy nền an toàn"
              onClick={() => setPanel("drive")}
            />
          </div>
        </section>
      )}
      <Modal
        open={panel === "staff"}
        onClose={() => setPanel(null)}
        className="max-w-2xl"
        title="Nhân sự"
        description="Những người có thể được tag. Danh sách chọn lấy từ thành viên của tất cả khách hàng."
      >
        <StaffRosterSection canEdit={canStaff} />
      </Modal>

      <Modal
        open={panel === "bulk"}
        onClose={() => setPanel(null)}
        className="max-w-4xl"
        title="Cấu hình chung tag"
        description="Đặt một cấu hình rồi áp cho nhiều khách hàng. Cấu hình cũ của những khách hàng được chọn sẽ bị ghi đè."
      >
        <BulkMentionSection canEdit={canBulk} />
      </Modal>

      <Modal
        open={panel === "tasks"}
        onClose={() => setPanel(null)}
        className="max-w-6xl"
        title="Vòng tag đang hoạt động"
        description="Mỗi task là một vòng lặp và có thể đang chờ nhiều người cùng lúc."
      >
        <ActiveMentionTasksPanel canCancel={canTaskCancel} />
      </Modal>
      <Modal
        open={panel === "debt-bulk"}
        onClose={() => setPanel(null)}
        className="max-w-5xl"
        title="Cấu hình chung nhắc công nợ"
        description="Chỉ thay đổi lịch gửi; nội dung cuối của từng khách hàng luôn được giữ nguyên."
      >
        <BulkDebtReminderSection />
      </Modal>
      <Modal
        open={panel === "debt-history"}
        onClose={() => setPanel(null)}
        className="max-w-6xl"
        title="Lịch sử nhắc công nợ"
        description="Các lượt nhắc trong tháng hiện tại còn nằm trong thời hạn lưu 45 ngày."
      >
        <DebtReminderHistoryPanel />
      </Modal>
      <Modal
        open={panel === "drive"}
        onClose={() => setPanel(null)}
        className="max-w-6xl"
        title="Chuyển Excel sang Google Sheets"
        description="Quét toàn bộ folder con, chọn file rồi xử lý nền từng file."
      >
        <DriveConverterPanel />
      </Modal>

      <Modal
        open={panel === "policy"}
        onClose={() => setPanel(null)}
        className="max-w-4xl"
        title="Chính sách phân loại"
        description="Một chính sách dùng chung cho toàn bộ khách hàng trong hệ thống."
      >
        <ClassifierPolicySection canUpdate={canPolicy} />
      </Modal>
    </div>
  );
}

const TONES = {
  emerald: "bg-success-bg text-success-fg",
  amber: "bg-warning-bg text-warning-fg",
  blue: "bg-accent-soft text-accent",
  purple: "bg-violet-50 dark:bg-violet-500/15 text-violet-600 dark:text-violet-300",
  rose: "bg-rose-50 dark:bg-rose-500/15 text-rose-600 dark:text-rose-300",
} as const;

function PanelCard({
  icon: Icon,
  tone,
  title,
  description,
  summary,
  onClick,
}: {
  icon: LucideIcon;
  tone: keyof typeof TONES;
  title: string;
  description: string;
  summary: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="card flex items-start gap-4 p-6 text-left transition hover:border-accent/40 hover:shadow-lg"
    >
      <span
        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${TONES[tone]}`}
      >
        <Icon className="h-5 w-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="font-display text-xl">{title}</span>
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        </span>
        <span className="mt-1 block text-sm leading-relaxed text-muted-foreground">
          {description}
        </span>
        <span className="mt-3 inline-block rounded-lg bg-muted px-2.5 py-1 text-xs font-medium text-foreground">
          {summary}
        </span>
      </span>
    </button>
  );
}
