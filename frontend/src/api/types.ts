export type BotStatus = "CONNECTED" | "DISCONNECTED" | "CONNECTING" | "AUTH_REQUIRED" | "ERROR";
export type DeliveryStatus = "SENT" | "FAILED";
export type DeliveryType =
  | "MANUAL_MESSAGE"
  | "MENTION_AUTOMATION"
  | "DEBT_REMINDER_IMAGE"
  | "DEBT_REMINDER_LINK"
  | "DEBT_REMINDER_MESSAGE";
export type DebtReminderStatus = "PENDING" | "PROCESSING" | "SENT" | "FAILED" | "SKIPPED" | "CANCELLED";

export type User = { id: string; email: string };
export type Bot = {
  status: BotStatus;
  account_name: string | null;
  zalo_user_id: string | null;
  avatar_url: string | null;
  group_count: number;
  session_active: boolean;
  last_connected_at: string | null;
  last_health_check_at: string | null;
  last_error: string | null;
};
export type QRState = { status: string; qr: string | null; account_name: string | null };
export type Customer = {
  id: string;
  name: string;
  avatar_url: string | null;
  has_debt: boolean;
  last_debt_paid_at: string | null;
  note: string | null;
  folder_url: string | null;
  zalo_group_id: string;
  member_count: number;
  is_available: boolean;
  last_synced_at: string;
  created_at: string;
  updated_at: string;
};
export type CustomerList = { items: Customer[]; total: number; page: number; limit: number; pages: number };
export type SyncResult = { inserted: number; updated: number; unavailable: number; total: number; synced_at: string };
export type DeliveryLog = {
  id: string;
  customer_id: string;
  customer_name: string;
  type: DeliveryType;
  status: DeliveryStatus;
  zalo_message_id: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
};
export type DeliveryLogList = { items: DeliveryLog[]; total: number; page: number; limit: number; pages: number };
export type Dashboard = {
  bot_status: BotStatus;
  customer_count: number;
  customers_with_debt: number;
  messages_today: number;
  failed_today: number;
  last_sync_at: string | null;
  last_successful_message_at: string | null;
};

export type GroupMember = {
  user_id: string;
  display_name: string;
  avatar_url: string | null;
};

export type MentionTarget = GroupMember;

export type MentionTimeWindow = {
  start: string;
  end: string;
};

export type MentionAutomation = {
  id: string | null;
  group_id: string;
  enabled: boolean;
  delay_minutes: number;
  active_windows: MentionTimeWindow[];
  targets: MentionTarget[];
  pending_followups: number;
  updated_at: string | null;
};

export type DebtReminderPart =
  | { type: "text"; text: string }
  | { type: "mention"; user_id: string; display_name: string };

export type DebtReminder = {
  id: string | null;
  customer_id: string;
  enabled: boolean;
  day_of_month: number;
  repeat_interval_days: number;
  send_time: string;
  message_parts: DebtReminderPart[];
  next_run_at: string | null;
  last_run_status: DebtReminderStatus | null;
  last_run_at: string | null;
  last_error: string | null;
  updated_at: string | null;
};
