export type ConnectionStatus =
  | "CONNECTED"
  | "DISCONNECTED"
  | "CONNECTING"
  | "AUTH_REQUIRED"
  | "ERROR";

export type BotState = {
  status: ConnectionStatus;
  account_name: string | null;
  zalo_user_id: string | null;
  avatar_url: string | null;
  session_active: boolean;
  qr_status: string | null;
  last_error: string | null;
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
  group_id: string;
  message_id: string;
  sender_id: string;
  content: string;
  mentions: Array<{ user_id: string; position: number; length: number }>;
};

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
  sendText(groupId: string, content: string): Promise<SendResult>;
  sendMention(groupId: string, targets: MentionTarget[]): Promise<SendResult>;
  sendImage(groupId: string, image: ImageAttachment): Promise<SendResult>;
  sendLink(groupId: string, link: string): Promise<SendResult>;
  sendRichText(groupId: string, parts: RichTextPart[]): Promise<SendResult>;
}
