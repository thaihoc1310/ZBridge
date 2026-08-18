import {
  LoginQRCallbackEventType,
  ThreadType,
  Zalo,
  type API,
  type Credentials,
  type LoginQRCallbackEvent,
  type Message,
} from "zca-js";
import { GatewayError } from "../errors.js";
import { EncryptedSessionStore } from "./session.js";
import type {
  BotState,
  ImageAttachment,
  IncomingGroupMessageEvent,
  MentionTarget,
  RichTextPart,
  SendResult,
  ZaloClient,
  ZaloGroup,
  ZaloMember,
} from "./types.js";

type EventSink = (event: IncomingGroupMessageEvent) => Promise<void>;

export class ZcaJsClient implements ZaloClient {
  private api: API | null = null;
  private status: BotState["status"] = "AUTH_REQUIRED";
  private accountName: string | null = null;
  private zaloUserId: string | null = null;
  private avatarUrl: string | null = null;
  private qrImage: string | null = null;
  private qrStatus: string | null = null;
  private lastError: string | null = null;
  private loginTask: Promise<void> | null = null;
  private outboundTail: Promise<void> = Promise.resolve();

  constructor(
    private readonly sessions: EncryptedSessionStore,
    private readonly eventSink: EventSink,
    private readonly sendIntervalMs = 1000,
  ) {}

  async initialize(): Promise<void> {
    const credentials = await this.sessions.load();
    if (!credentials) {
      this.status = "AUTH_REQUIRED";
      return;
    }
    try {
      this.status = "CONNECTING";
      const zalo = new Zalo();
      this.api = await zalo.login(credentials);
      await this.loadProfile();
      this.startListener();
      this.status = "CONNECTED";
      console.info("BOT_CONNECTED restored_session=true");
    } catch (error) {
      this.api = null;
      this.status = "AUTH_REQUIRED";
      this.lastError = this.safeError(error);
      console.warn("BOT_AUTH_REQUIRED saved_session_invalid=true");
    }
  }

  async connect(): Promise<BotState> {
    if (this.status === "CONNECTED" || this.status === "CONNECTING") return this.getStatus();
    this.status = "CONNECTING";
    this.qrStatus = "PREPARING_QR";
    this.qrImage = null;
    this.lastError = null;
    console.info("BOT_CONNECTING");
    this.loginTask = this.runQrLogin().finally(() => {
      this.loginTask = null;
    });
    void this.loginTask;
    return this.getStatus();
  }

  async reconnect(): Promise<BotState> {
    this.stopListener();
    this.api = null;
    const credentials = await this.sessions.load();
    if (!credentials) {
      this.status = "AUTH_REQUIRED";
      return this.connect();
    }
    try {
      this.status = "CONNECTING";
      this.api = await new Zalo().login(credentials);
      await this.loadProfile();
      this.startListener();
      this.status = "CONNECTED";
      this.lastError = null;
      console.info("BOT_CONNECTED reconnect=true");
    } catch (error) {
      this.status = "AUTH_REQUIRED";
      this.lastError = this.safeError(error);
      await this.sessions.clear();
      return this.connect();
    }
    return this.getStatus();
  }

  async disconnect(): Promise<BotState> {
    this.stopListener();
    this.api = null;
    this.status = "DISCONNECTED";
    this.qrImage = null;
    this.qrStatus = null;
    await this.sessions.clear();
    console.info("BOT_DISCONNECTED session_removed=true");
    return this.getStatus();
  }

  async getStatus(): Promise<BotState> {
    return {
      status: this.status,
      account_name: this.accountName,
      zalo_user_id: this.zaloUserId,
      avatar_url: this.avatarUrl,
      session_active: await this.sessions.exists(),
      qr_status: this.qrStatus,
      last_error: this.lastError,
    };
  }

  async getQr(): Promise<{ status: string; qr: string | null; account_name: string | null }> {
    return {
      status: this.status === "CONNECTED" ? "CONNECTED" : (this.qrStatus ?? this.status),
      qr: this.qrImage,
      account_name: this.accountName,
    };
  }

  async getGroups(): Promise<ZaloGroup[]> {
    const api = this.requireApi();
    const allGroups = await api.getAllGroups();
    const ids = Object.keys(allGroups.gridVerMap);
    const groups: ZaloGroup[] = [];
    for (let index = 0; index < ids.length; index += 50) {
      const chunk = ids.slice(index, index + 50);
      if (chunk.length === 0) continue;
      const detail = await api.getGroupInfo(chunk);
      for (const info of Object.values(detail.gridInfoMap)) {
        groups.push({
          group_id: info.groupId,
          name: info.name,
          avatar_url: info.fullAvt || info.avt || null,
          member_count: info.totalMember ?? info.memberIds?.length ?? 0,
        });
      }
    }
    return groups;
  }

  async getGroupMembers(groupId: string): Promise<ZaloMember[]> {
    const api = this.requireApi();
    const detail = await api.getGroupInfo(groupId);
    const group = detail.gridInfoMap[groupId];
    if (!group) {
      throw new GatewayError("GROUP_NOT_FOUND", "Không tìm thấy nhóm trên Zalo.", 404);
    }

    const currentMembers = group.currentMems ?? [];
    const resolved = new Map<string, ZaloMember>();
    for (const member of currentMembers) {
      const userId = this.normalizeMemberId(member.id);
      resolved.set(userId, {
        user_id: userId,
        display_name: member.dName || member.zaloName || userId,
        avatar_url: member.avatar || member.avatar_25 || null,
      });
    }
    const memberIds = [
      ...new Set([
        ...(group.memberIds ?? []).map((id) => this.normalizeMemberId(id)),
        ...(group.memVerList ?? [])
          .flatMap((entry) => {
            const id = entry.split("_")[0];
            return id ? [id] : [];
          })
          .map((id) => this.normalizeMemberId(id)),
        ...currentMembers.map((member) => this.normalizeMemberId(member.id)),
      ]),
    ];
    const unresolvedIds = memberIds.filter((memberId) => !resolved.has(memberId));
    for (let index = 0; index < unresolvedIds.length; index += 50) {
      const chunk = unresolvedIds.slice(index, index + 50);
      if (chunk.length === 0) continue;
      const response = await api.getGroupMembersInfo(chunk);
      for (const [responseId, profile] of Object.entries(response.profiles)) {
        const userId = this.normalizeMemberId(profile.id || responseId);
        resolved.set(userId, {
          user_id: userId,
          display_name:
            profile?.displayName ||
            profile?.zaloName ||
            userId,
          avatar_url: profile?.avatar || null,
        });
      }
    }

    const members = memberIds.map(
      (memberId) =>
        resolved.get(memberId) ?? {
          user_id: memberId,
          display_name: memberId,
          avatar_url: null,
        },
    );
    if (members.length < group.totalMember) {
      console.warn(
        "ZALO_GROUP_MEMBERS_PARTIAL group_id=%s resolved=%d total=%d has_more=%d",
        groupId,
        members.length,
        group.totalMember,
        group.hasMoreMember,
      );
    }
    return members.sort((left, right) =>
      left.display_name.localeCompare(right.display_name, "vi"),
    );
  }

  async sendText(groupId: string, content: string): Promise<SendResult> {
    return this.enqueueOutbound(async () => {
      const api = this.requireApi();
      console.info("ZALO_SEND_STARTED group_id=%s", groupId);
      try {
        const response = await api.sendMessage({ msg: content }, groupId, ThreadType.Group);
        if (!response.message?.msgId) {
          throw new GatewayError("SEND_FAILED", "Zalo không trả về mã tin nhắn.", 502);
        }
        console.info("ZALO_SEND_SUCCESS group_id=%s", groupId);
        return { message_id: String(response.message.msgId) };
      } catch (error) {
        console.error("ZALO_SEND_FAILED group_id=%s", groupId);
        if (error instanceof GatewayError) throw error;
        throw new GatewayError("ZALO_API_ERROR", this.safeError(error), 502);
      }
    });
  }

  async sendMention(groupId: string, targets: MentionTarget[]): Promise<SendResult> {
    if (targets.length === 0) {
      throw new GatewayError("VALIDATION_ERROR", "Cần ít nhất một người để tag.", 422);
    }
    const parts: string[] = [];
    const mentions: Array<{ uid: string; pos: number; len: number }> = [];
    let position = 0;
    for (const target of targets) {
      const label = `@${target.display_name}`;
      parts.push(label);
      mentions.push({ uid: target.user_id, pos: position, len: label.length });
      position += label.length + 1;
    }
    return this.enqueueOutbound(async () => {
      const api = this.requireApi();
      try {
        const response = await api.sendMessage(
          { msg: parts.join(" "), mentions },
          groupId,
          ThreadType.Group,
        );
        if (!response.message?.msgId) {
          throw new GatewayError("SEND_FAILED", "Zalo không trả về mã tin nhắn.", 502);
        }
        console.info("ZALO_MENTION_SENT group_id=%s targets=%d", groupId, targets.length);
        return { message_id: String(response.message.msgId) };
      } catch (error) {
        if (error instanceof GatewayError) throw error;
        throw new GatewayError("ZALO_API_ERROR", this.safeError(error), 502);
      }
    });
  }

  async sendImage(groupId: string, image: ImageAttachment): Promise<SendResult> {
    return this.enqueueOutbound(async () => {
      const api = this.requireApi();
      try {
        const response = await api.sendMessage(
          {
            msg: "",
            attachments: {
              data: image.data,
              filename: "cong-no.png",
              metadata: {
                totalSize: image.data.length,
                width: image.width,
                height: image.height,
              },
            },
          },
          groupId,
          ThreadType.Group,
        );
        const messageId = response.attachment[0]?.msgId;
        if (!messageId) {
          throw new GatewayError("SEND_IMAGE_FAILED", "Zalo không xác nhận ảnh đã gửi.", 502);
        }
        return { message_id: String(messageId) };
      } catch (error) {
        if (error instanceof GatewayError) throw error;
        throw new GatewayError("ZALO_API_ERROR", this.safeError(error), 502);
      }
    });
  }

  async sendLink(groupId: string, link: string): Promise<SendResult> {
    return this.enqueueOutbound(async () => {
      const api = this.requireApi();
      try {
        const response = await api.sendLink({ link }, groupId, ThreadType.Group);
        if (!response.msgId) {
          throw new GatewayError("SEND_LINK_FAILED", "Zalo không xác nhận link đã gửi.", 502);
        }
        return { message_id: String(response.msgId) };
      } catch (linkError) {
        try {
          const fallback = await api.sendMessage({ msg: link }, groupId, ThreadType.Group);
          if (!fallback.message?.msgId) throw linkError;
          return { message_id: String(fallback.message.msgId) };
        } catch (error) {
          if (error instanceof GatewayError) throw error;
          throw new GatewayError("ZALO_API_ERROR", this.safeError(error), 502);
        }
      }
    });
  }

  async sendRichText(groupId: string, parts: RichTextPart[]): Promise<SendResult> {
    let content = "";
    const mentions: Array<{ uid: string; pos: number; len: number }> = [];
    for (const part of parts) {
      if (part.type === "text") {
        content += part.text;
      } else {
        const label = `@${part.display_name}`;
        mentions.push({ uid: part.user_id, pos: content.length, len: label.length });
        content += label;
      }
    }
    if (!content.trim() || content.length > 5000) {
      throw new GatewayError("VALIDATION_ERROR", "Nội dung nhắc công nợ không hợp lệ.", 422);
    }
    return this.enqueueOutbound(async () => {
      const api = this.requireApi();
      try {
        const response = await api.sendMessage(
          { msg: content, mentions },
          groupId,
          ThreadType.Group,
        );
        if (!response.message?.msgId) {
          throw new GatewayError("SEND_FAILED", "Zalo không trả về mã tin nhắn.", 502);
        }
        return { message_id: String(response.message.msgId) };
      } catch (error) {
        if (error instanceof GatewayError) throw error;
        throw new GatewayError("ZALO_API_ERROR", this.safeError(error), 502);
      }
    });
  }

  private async enqueueOutbound<T>(operation: () => Promise<T>): Promise<T> {
    const previous = this.outboundTail;
    let release: () => void = () => undefined;
    this.outboundTail = new Promise<void>((resolve) => {
      release = resolve;
    });
    await previous;
    try {
      return await operation();
    } finally {
      setTimeout(release, this.sendIntervalMs);
    }
  }

  private requireApi(): API {
    if (!this.api || this.status !== "CONNECTED") {
      const code = this.status === "AUTH_REQUIRED" ? "AUTH_REQUIRED" : "BOT_DISCONNECTED";
      throw new GatewayError(code, "Bot chưa kết nối với Zalo.", 409);
    }
    return this.api;
  }

  private async runQrLogin(): Promise<void> {
    try {
      const zalo = new Zalo();
      this.api = await zalo.loginQR({}, (event) => this.handleQrEvent(event));
      const context = this.api.getContext();
      const credentials: Credentials = {
        cookie: context.cookie.toJSON()?.cookies ?? [],
        imei: context.imei,
        userAgent: context.userAgent,
      };
      await this.sessions.save(credentials);
      await this.loadProfile();
      this.startListener();
      this.status = "CONNECTED";
      this.qrStatus = "CONNECTED";
      this.qrImage = null;
      console.info("BOT_CONNECTED qr_login=true");
    } catch (error) {
      this.api = null;
      this.status = "AUTH_REQUIRED";
      this.qrStatus = "AUTH_REQUIRED";
      this.lastError = this.safeError(error);
      console.error("BOT_AUTH_REQUIRED qr_login_failed=true");
    }
  }

  private handleQrEvent(event: LoginQRCallbackEvent): void {
    switch (event.type) {
      case LoginQRCallbackEventType.QRCodeGenerated:
        this.qrImage = event.data.image;
        this.qrStatus = "WAITING_FOR_SCAN";
        break;
      case LoginQRCallbackEventType.QRCodeScanned:
        this.accountName = event.data.display_name;
        this.avatarUrl = event.data.avatar;
        this.qrStatus = "QR_SCANNED";
        break;
      case LoginQRCallbackEventType.QRCodeExpired:
        this.qrStatus = "QR_EXPIRED";
        event.actions.retry();
        break;
      case LoginQRCallbackEventType.QRCodeDeclined:
        this.qrStatus = "QR_DECLINED";
        break;
      case LoginQRCallbackEventType.GotLoginInfo:
        void this.sessions.save({
          cookie: event.data.cookie,
          imei: event.data.imei,
          userAgent: event.data.userAgent,
        });
        break;
    }
  }

  private async loadProfile(): Promise<void> {
    if (!this.api) return;
    const { profile } = await this.api.fetchAccountInfo();
    this.accountName = profile.displayName || profile.zaloName || null;
    this.zaloUserId = profile.userId;
    this.avatarUrl = profile.avatar || null;
  }

  private startListener(): void {
    if (!this.api) return;
    this.api.listener.on("message", (message) => this.handleMessage(message));
    this.api.listener.on("connected", () => {
      console.info("ZALO_LISTENER_CONNECTED");
    });
    this.api.listener.on("disconnected", (code, reason) => {
      console.warn(
        "ZALO_LISTENER_DISCONNECTED code=%d reason=%s",
        code,
        reason || "unknown",
      );
    });
    this.api.listener.on("closed", (code, reason) => {
      console.error(
        "ZALO_LISTENER_CLOSED code=%d reason=%s",
        code,
        reason || "unknown",
      );
    });
    this.api.listener.on("error", (error) => {
      console.error("ZALO_LISTENER_ERROR", this.safeError(error));
    });
    this.api.listener.start({ retryOnClose: true });
    console.info("ZALO_LISTENER_STARTED");
  }

  private stopListener(): void {
    try {
      this.api?.listener.stop();
    } catch (error) {
      console.warn("ZALO_LISTENER_STOP_FAILED", this.safeError(error));
    }
  }

  private handleMessage(message: Message): void {
    if (message.isSelf || message.type !== ThreadType.Group) return;
    const mentions = message.data.mentions ?? [];
    const messageId = [
      message.data.msgId,
      message.data.cliMsgId,
      message.data.realMsgId,
      message.data.actionId,
    ]
      .map((value) => String(value ?? ""))
      .find((value) => value !== "" && value !== "0");
    if (!messageId) return;
    const event: IncomingGroupMessageEvent = {
      group_id: message.threadId,
      message_id: messageId,
      sender_id: this.normalizeMemberId(message.data.uidFrom),
      content:
        typeof message.data.content === "string" ? message.data.content : "",
      mentions: mentions.map((mention) => ({
        user_id: this.normalizeMemberId(mention.uid),
        position: mention.pos,
        length: mention.len,
      })),
    };
    void this.eventSink(event).catch((error) => {
      console.error(
        "ZALO_EVENT_FORWARD_FAILED group_id=%s error=%s",
        message.threadId,
        this.safeError(error),
      );
    });
  }

  private safeError(error: unknown): string {
    return error instanceof Error ? error.message : "Zalo API gặp lỗi không xác định.";
  }

  private normalizeMemberId(userId: string): string {
    return userId.endsWith("_0") ? userId.slice(0, -2) : userId;
  }
}
