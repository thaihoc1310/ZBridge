import { useQuery } from "@tanstack/react-query";
import { BrainCircuit, ChevronRight, Layers, Users, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import type { MentionClassifierSettings, StaffMember } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { Modal } from "../components/ui/Modal";
import { BulkMentionSection } from "../features/mentions/BulkMentionSection";
import { ClassifierPolicySection } from "../features/mentions/ClassifierPolicySection";
import { StaffRosterSection } from "../features/mentions/StaffRosterSection";
import { PERMISSIONS } from "../lib/permissions";
import { usePermissions } from "../lib/session";

type Panel = "staff" | "bulk" | "policy";

export function MentionSettingsPage() {
  const { can } = usePermissions();
  // One grant per section: the roster is a list of names, one bulk apply
  // overwrites every customer, and the policy governs the classifier.
  const canPolicy = can(PERMISSIONS.mentionPolicyManage);
  const canStaff = can(PERMISSIONS.staffManage);
  const canBulk = can(PERMISSIONS.mentionBulkApply);
  const [panel, setPanel] = useState<Panel | null>(null);

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
  return <div className="mx-auto max-w-5xl">
    <PageHeader
      eyebrow="Global policy"
      title="Tag"
      highlight="tên tự động"
      description="Nhân sự được tag, cấu hình chung cho nhiều khách hàng, và chính sách phân loại của toàn hệ thống."
    />

    <div className="grid gap-4 sm:grid-cols-2">
      {canStaff && <PanelCard
        icon={Users}
        tone="emerald"
        title="Nhân sự"
        description="Khai báo một lần những người có thể được tag, dùng lại ở mọi khách hàng."
        summary={roster.isLoading ? "Đang tải..." : `${staffCount} người`}
        onClick={() => setPanel("staff")}
      />}
      {canBulk && <PanelCard
        icon={Layers}
        tone="amber"
        title="Cấu hình chung"
        description="Áp một cấu hình tag cho nhiều khách hàng cùng lúc, ghi đè cấu hình cũ."
        summary="Ghi đè hàng loạt"
        onClick={() => setPanel("bulk")}
      />}
      {canPolicy && <PanelCard
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
      />}
    </div>

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
      title="Cấu hình chung"
      description="Đặt một cấu hình rồi áp cho nhiều khách hàng. Cấu hình cũ của những khách hàng được chọn sẽ bị ghi đè."
    >
      <BulkMentionSection canEdit={canBulk} />
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
  </div>;
}

const TONES = {
  emerald: "bg-emerald-50 text-emerald-600",
  amber: "bg-amber-50 text-amber-600",
  blue: "bg-blue-50 text-accent",
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
      <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${TONES[tone]}`}>
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
