import type {
  BotState,
  ImageAttachment,
  MentionTarget,
  RichTextPart,
  SendResult,
  ZaloClient,
  ZaloGroup,
  ZaloMember,
} from "./types.js";

export class MockZaloClient implements ZaloClient {
  private connected = true;

  async initialize(): Promise<void> {}
  async connect(): Promise<BotState> {
    this.connected = true;
    return this.getStatus();
  }
  async reconnect(): Promise<BotState> {
    this.connected = true;
    return this.getStatus();
  }
  async disconnect(): Promise<BotState> {
    this.connected = false;
    return this.getStatus();
  }
  async getStatus(): Promise<BotState> {
    return {
      status: this.connected ? "CONNECTED" : "DISCONNECTED",
      account_name: "ZBridge Demo Bot",
      zalo_user_id: "mock-983479823749",
      avatar_url: null,
      session_active: this.connected,
      qr_status: null,
      last_error: null,
    };
  }
  async getQr() {
    return { status: this.connected ? "CONNECTED" : "AUTH_REQUIRED", qr: null, account_name: "ZBridge Demo Bot" };
  }
  async getGroups(): Promise<ZaloGroup[]> {
    return [
      { group_id: "mock-group-1", name: "ABC — Accounting", avatar_url: null, member_count: 12 },
      { group_id: "mock-group-2", name: "XYZ Support", avatar_url: null, member_count: 18 },
      { group_id: "mock-group-3", name: "Customer Test", avatar_url: null, member_count: 6 },
    ];
  }
  async getGroupMembers(groupId: string): Promise<ZaloMember[]> {
    if (!this.connected) throw new Error("Bot disconnected");
    const members: Record<string, ZaloMember[]> = {
      "mock-group-1": [
        { user_id: "mock-user-1", display_name: "Nguyễn Minh Anh", avatar_url: null },
        { user_id: "mock-user-2", display_name: "Trần Hoàng Nam", avatar_url: null },
        { user_id: "mock-user-3", display_name: "Lê Thu Hà", avatar_url: null },
      ],
      "mock-group-2": [
        { user_id: "mock-user-4", display_name: "Phạm Gia Bảo", avatar_url: null },
        { user_id: "mock-user-5", display_name: "Vũ Khánh Linh", avatar_url: null },
      ],
      "mock-group-3": [
        { user_id: "mock-user-6", display_name: "Đỗ Thanh Tùng", avatar_url: null },
      ],
    };
    return members[groupId] ?? [];
  }
  async sendText(_groupId: string, _content: string): Promise<SendResult> {
    if (!this.connected) throw new Error("Bot disconnected");
    return { message_id: `mock-${Date.now()}` };
  }
  async sendMention(_groupId: string, targets: MentionTarget[]): Promise<SendResult> {
    if (!this.connected) throw new Error("Bot disconnected");
    if (targets.length === 0) throw new Error("Mention targets are required");
    return { message_id: `mock-mention-${Date.now()}` };
  }
  async sendImage(_groupId: string, image: ImageAttachment): Promise<SendResult> {
    if (!this.connected) throw new Error("Bot disconnected");
    if (image.data.length === 0) throw new Error("Image is required");
    return { message_id: `mock-image-${Date.now()}` };
  }
  async sendLink(_groupId: string, link: string): Promise<SendResult> {
    if (!this.connected) throw new Error("Bot disconnected");
    if (!link) throw new Error("Link is required");
    return { message_id: `mock-link-${Date.now()}` };
  }
  async sendRichText(_groupId: string, parts: RichTextPart[]): Promise<SendResult> {
    if (!this.connected) throw new Error("Bot disconnected");
    if (parts.length === 0) throw new Error("Message parts are required");
    return { message_id: `mock-rich-text-${Date.now()}` };
  }
}
