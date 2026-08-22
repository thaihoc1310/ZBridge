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
  events_healthy: boolean;
  event_backlog: number;
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
  sender_id: string;
  sender_display_name: string | null;
  sent_at: string | null;
  content: string;
  mentions: Array<{ user_id: string; position: number; length: number; text: string }>;
};

export type IncomingGroupReactionEvent = {
  event_type: "reaction";
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
