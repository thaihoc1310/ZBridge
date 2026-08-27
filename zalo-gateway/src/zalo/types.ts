export type ConnectionStatus =
  | "CONNECTED"
  | "DISCONNECTED"
  | "CONNECTING"
  | "AUTH_REQUIRED"
  | "ERROR";

/**
 * Health of the Zalo websocket that delivers incoming group events.
 *
 * `LISTENING` is the only state in which the gateway can observe that a
 * customer replied or reacted, so the backend must not send mention follow-ups in any
 * other state — it would keep tagging people who already answered.
 */
export type ListenerStatus =
  | "IDLE"
  | "STARTING"
  | "LISTENING"
  | "RECONNECTING"
  | "CLOSED"
  | "STOPPED";

export type BotState = {
  status: ConnectionStatus;
  account_name: string | null;
  zalo_user_id: string | null;
  avatar_url: string | null;
  session_active: boolean;
  qr_status: string | null;
  last_error: string | null;
  listener_status: ListenerStatus;
  /**
   * The event channel is working: connected, listening, and the outbox can
   * still store and forward. Deliberately independent of the backlog — an event
   * being POSTed right now is the channel working, not failing.
   */
  events_healthy: boolean;
  /** Nothing is waiting to reach the backend, so replies observed so far are known. */
  events_caught_up: boolean;
  event_backlog: number;
  /** Age of the oldest undelivered event, which separates a blip from a stall. */
  event_backlog_age_ms: number | null;
};

export type EventTransportStatus = {
  healthy: boolean;
  pending: number;
  oldestPendingMs: number | null;
};

export type ZaloGroup = {
  group_id: string;
  name: string;
  avatar_url: string | null;
  member_count: number;
};

export type ZaloMember = {
  user_id: string;
  display_name: string;
  avatar_url: string | null;
};

export type MentionTarget = Pick<ZaloMember, "user_id" | "display_name">;

export type RichTextPart =
  | { type: "text"; text: string }
  | { type: "mention"; user_id: string; display_name: string };

export type ImageAttachment = {
  data: Buffer;
  width: number;
  height: number;
};

export type IncomingGroupMessageEvent = {
  event_type: "message";
  group_id: string;
  message_id: string;
  /** Every non-zero zca-js identifier for matching later reaction events. */
  message_aliases: string[];
  sender_id: string;
  sender_display_name: string | null;
  sent_at: string | null;
  content: string;
  mentions: Array<{ user_id: string; position: number; length: number; text: string }>;
};

export type IncomingGroupReactionEvent = {
  event_type: "reaction";
  /** ID of the reaction event itself, used to make context ingestion idempotent. */
  event_id: string | null;
  /** gMsgID/cMsgID values of the message that received the reaction. */
  target_message_ids: string[];
  group_id: string;
  reactor_id: string;
  reactor_display_name: string | null;
  reacted_at: string | null;
  reaction: "heart" | "like";
};

export type IncomingGroupEvent = IncomingGroupMessageEvent | IncomingGroupReactionEvent;

export type SendResult = {
  message_id: string;
};

export interface ZaloClient {
  initialize(): Promise<void>;
  connect(): Promise<BotState>;
  reconnect(): Promise<BotState>;
  disconnect(): Promise<BotState>;
  getStatus(): Promise<BotState>;
  getQr(): Promise<{ status: string; qr: string | null; account_name: string | null }>;
  getGroups(): Promise<ZaloGroup[]>;
  getGroupMembers(groupId: string): Promise<ZaloMember[]>;
  getGroupMembersBatch(groupIds: string[]): Promise<Record<string, ZaloMember[]>>;
  sendText(groupId: string, content: string): Promise<SendResult>;
  sendMention(groupId: string, targets: MentionTarget[]): Promise<SendResult>;
  sendImage(groupId: string, image: ImageAttachment): Promise<SendResult>;
  sendLink(groupId: string, link: string): Promise<SendResult>;
  sendRichText(groupId: string, parts: RichTextPart[]): Promise<SendResult>;
}
