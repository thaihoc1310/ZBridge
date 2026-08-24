export type BotStatus =
  | "CONNECTED"
  | "DISCONNECTED"
  | "CONNECTING"
  | "AUTH_REQUIRED"
  | "ERROR";
export type DeliveryStatus = "SENT" | "FAILED";
export type DeliveryType =
  | "MANUAL_MESSAGE"
  | "MENTION_AUTOMATION"
  | "DEBT_REMINDER_IMAGE"
  | "DEBT_REMINDER_LINK"
  | "DEBT_REMINDER_MESSAGE";
export type DebtReminderStatus =
  | "PENDING"
  | "PROCESSING"
  | "SENT"
  | "FAILED"
  | "SKIPPED"
  | "CANCELLED";
export type MentionFollowupStatus =
  | "CLASSIFYING"
  | "PENDING"
  | "PROCESSING"
  | "SENT"
  | "FAILED"
  | "SKIPPED"
  | "CANCELLED";

export type Permission = { code: string; name: string; category: string };

export type Role = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: string[];
  user_count: number;
};

export type User = {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  role: Role;
  created_at: string;
  updated_at: string;
};

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
  listener_status: string | null;
  events_healthy: boolean;
};
export type QRState = {
  status: string;
  qr: string | null;
  account_name: string | null;
};
export type Customer = {
  id: string;
  name: string;
  avatar_url: string | null;
  has_debt: boolean;
  last_debt_paid_at: string | null;
  note: string | null;
  /** Google Sheet the debt reminder screenshots; verified when saved. */
  debt_file_url: string | null;
  zalo_group_id: string;
  member_count: number;
  is_available: boolean;
  last_synced_at: string;
  created_at: string;
  updated_at: string;
};
export type CustomerList = {
  items: Customer[];
  total: number;
  page: number;
  limit: number;
  pages: number;
};
export type SyncResult = {
  inserted: number;
  updated: number;
  unavailable: number;
  total: number;
  synced_at: string;
};
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
export type DeliveryLogList = {
  items: DeliveryLog[];
  total: number;
  page: number;
  limit: number;
  pages: number;
};
export type ModelCallStatus = "PROCESSING" | "SUCCEEDED" | "FAILED";
export type ModelCallLog = {
  id: string;
  customer_id: string | null;
  customer_name: string;
  trigger: "MENTION" | "PRICE_INQUIRY";
  provider: string;
  model: string;
  request_payload: Record<string, unknown>;
  response_payload: Record<string, unknown> | null;
  status: ModelCallStatus;
  outcome: string | null;
  error_type: string | null;
  error_message: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  created_at: string;
  finished_at: string | null;
};
export type ModelCallLogList = {
  items: ModelCallLog[];
  total: number;
  page: number;
  limit: number;
  pages: number;
};
export type Dashboard = {
  bot_status: BotStatus;
  customer_count: number;
  customers_with_debt: number;
  customers_without_debt: number;
  messages_today: number;
  messages_by_hour: Array<{ hour: number; count: number }>;
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
  /** Derived from the two feature flags; the UI edits those, not this. */
  enabled: boolean;
  mention_tag_enabled: boolean;
  price_inquiry_enabled: boolean;
  delay_minutes: number;
  active_windows: MentionTimeWindow[];
  targets: MentionTarget[];
  price_targets: MentionTarget[];
  pending_followups: number;
  updated_at: string | null;
};

export type StaffMember = {
  user_id: string;
  display_name: string;
  avatar_url: string | null;
  note: string | null;
  mention_customer_count: number;
  price_customer_count: number;
};

export type BulkMentionPreviewRow = {
  customer_id: string;
  name: string;
  is_available: boolean;
  has_automation: boolean;
  current_target_count: number;
  active_followups: number;
  /** False when this customer already has exactly this configuration. */
  will_change: boolean;
  missing_members: string[];
};

export type BulkMentionPreview = {
  rows: BulkMentionPreviewRow[];
  gateway_error: string | null;
};

export type BulkMentionApplyResult = {
  updated: number;
  created: number;
  unchanged: number;
  skipped: string[];
  cancelled_followups: number;
  dropped_members: Record<string, number>;
};

export type MentionClassifierSettings = {
  ai_classifier_enabled: boolean;
  bare_mention_requires_response: boolean;
  skip_phrases: string[];
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

export type ActiveMentionTask = {
  id: string;
  trigger: "MENTION" | "PRICE_INQUIRY";
  status: MentionFollowupStatus;
  target_user_ids: string[];
  target_display_names: string[];
  due_at: string;
  created_at: string;
  attempt_count: number;
  error_message: string | null;
};
export type ActiveMentionCompany = {
  customer_id: string;
  customer_name: string;
  task_count: number;
  next_due_at: string;
  tasks: ActiveMentionTask[];
};
export type ActiveMentionCompanyList = {
  items: ActiveMentionCompany[];
  total_companies: number;
  total_tasks: number;
  page: number;
  limit: number;
  pages: number;
};

export type DebtBulkPreviewRow = {
  customer_id: string;
  name: string;
  is_available: boolean;
  has_debt: boolean;
  has_debt_file: boolean;
  has_automation: boolean;
  enabled: boolean;
  current_day_of_month: number | null;
  current_repeat_interval_days: number | null;
  current_send_time: string | null;
  will_change: boolean;
};
export type DebtBulkPreview = { rows: DebtBulkPreviewRow[] };
export type DebtBulkApplyResult = {
  created: number;
  updated: number;
  unchanged: number;
  cancelled_runs: number;
  skipped: string[];
};

export type DebtReminderRunStep = {
  type: "IMAGE" | "LINK" | "MESSAGE";
  status: DebtReminderStatus;
  zalo_message_id: string | null;
  error_message: string | null;
};
export type DebtReminderRun = {
  id: string;
  customer_id: string;
  customer_name: string;
  status: DebtReminderStatus;
  scheduled_for: string;
  retry_at: string;
  attempt_count: number;
  created_at: string;
  processed_at: string | null;
  sheet_name: string | null;
  sheet_url: string | null;
  error_code: string | null;
  error_message: string | null;
  steps: DebtReminderRunStep[];
};
export type DebtReminderRunList = {
  items: DebtReminderRun[];
  total: number;
  page: number;
  limit: number;
  pages: number;
  status_counts: Record<string, number>;
  retention_days: number;
};

export type DriveFolder = {
  id: string;
  folder_id: string;
  name: string;
  url: string;
  drive_id: string | null;
  capabilities: Record<string, unknown>;
  last_checked_at: string;
  created_at: string;
};
export type GoogleOAuthStatus = {
  configured: boolean;
  connected: boolean;
  email: string | null;
  connected_at: string | null;
  last_verified_at: string | null;
  last_error: string | null;
  redirect_uri: string;
};
export type GoogleOAuthStart = { authorization_url: string };
export type DriveConversionItemStatus =
  | "DISCOVERED"
  | "PENDING"
  | "PROCESSING"
  | "CONVERTED"
  | "FAILED"
  | "SKIPPED";
export type DriveConversionItem = {
  id: string;
  source_file_id: string;
  source_name: string;
  source_url: string;
  parent_folder_id: string;
  parent_folder_name: string;
  parent_folder_url: string;
  relative_path: string;
  size_bytes: number | null;
  can_download: boolean;
  can_trash: boolean;
  selected: boolean;
  status: DriveConversionItemStatus;
  destination_url: string | null;
  original_trashed: boolean;
  attempt_count: number;
  error_code: string | null;
  error_message: string | null;
};
export type DriveConversionJobStatus =
  | "SCANNING"
  | "READY"
  | "QUEUED"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED";
export type DriveConversionJob = {
  id: string;
  folder_id: string;
  folder_name: string;
  status: DriveConversionJobStatus;
  delete_originals: boolean;
  total_files: number;
  selected_files: number;
  converted_files: number;
  failed_files: number;
  skipped_files: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  created_at: string;
  items: DriveConversionItem[];
};
