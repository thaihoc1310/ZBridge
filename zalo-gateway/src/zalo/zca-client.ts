import {
  CloseReason,
  LoginQRCallbackEventType,
  Reactions,
  ThreadType,
  Zalo,
  type API,
  type Credentials,
  type LoginQRCallbackEvent,
  type Message,
  type Reaction,
} from "zca-js";
import { reportGatewayError } from "../alerting.js";
import { GatewayError } from "../errors.js";
import { EncryptedSessionStore } from "./session.js";

/** The per-group entry of getGroupInfo, taken from the library so it stays in step. */
type GroupDetail = NonNullable<
  Awaited<ReturnType<API["getGroupInfo"]>>["gridInfoMap"][string]
>;
import type {
  BotState,
  ImageAttachment,
  IncomingGroupEvent,
  IncomingGroupMessageEvent,
  IncomingGroupReactionEvent,
  ListenerStatus,
  MentionTarget,
  RichTextPart,
  SendResult,
  ZaloClient,
  ZaloGroup,
  ZaloMember,
} from "./types.js";

type EventSink = (event: IncomingGroupEvent) => Promise<void>;

/** Context classification needs bodies, while the cap still prevents oversized events. */
const MAX_EVENT_CONTENT_LENGTH = 2_000;
const MAX_EVENT_MENTIONS = 1_000;
const LISTENER_RECOVERY_DELAYS_MS = [10_000, 30_000, 60_000, 120_000, 300_000];

function normalizeZaloMemberId(userId: string): string {
  return userId.endsWith("_0") ? userId.slice(0, -2) : userId;
}

function zaloTimestampToIso(value: string | number | null | undefined): string | null {
  const timestamp = Number(value);
  const date = Number.isFinite(timestamp)
    ? new Date(timestamp < 10_000_000_000 ? timestamp * 1_000 : timestamp)
    : null;
  return date && !Number.isNaN(date.getTime()) ? date.toISOString() : null;
}

export function usableZaloIds(
  values: Array<string | number | null | undefined>,
): string[] {
  return [...new Set(
    values
      .map((value) => String(value ?? ""))
      .filter((value) => value !== "" && value !== "0"),
  )];
}

function firstUsableZaloId(
  values: Array<string | number | null | undefined>,
): string | null {
  return usableZaloIds(values)[0] ?? null;
}

export function incomingReactionEvent(
  reaction: Reaction,
): IncomingGroupReactionEvent | null {
  if (reaction.isSelf || !reaction.isGroup) return null;
  const kind =
    reaction.data.content.rIcon === Reactions.HEART
      ? "heart"
      : reaction.data.content.rIcon === Reactions.LIKE
        ? "like"
        : null;
  if (!kind || !reaction.threadId || !reaction.data.uidFrom) return null;
  return {
    event_type: "reaction",
    // Outer IDs identify the reaction event; rMsg IDs identify its message.
    event_id: firstUsableZaloId([
      reaction.data.msgId,
      reaction.data.cliMsgId,
      reaction.data.actionId,
    ]),
    target_message_ids: usableZaloIds(
      reaction.data.content.rMsg.flatMap((item) => [item.gMsgID, item.cMsgID]),
    ),
    group_id: reaction.threadId,
    reactor_id: normalizeZaloMemberId(reaction.data.uidFrom),
    reactor_display_name: reaction.data.dName || null,
    reacted_at: zaloTimestampToIso(reaction.data.ts),
    reaction: kind,
  };
}

/** Preserve the semantic presence of an image without forwarding its large payload. */
export function incomingMessageContent(data: {
  msgType: string;
  content: unknown;
}): string {
  if (data.msgType === "chat.photo") return "[image]";
  return typeof data.content === "string" ? data.content : "";
}

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
  private readonly inboundTails = new Map<string, Promise<void>>();
  private listenerStatus: ListenerStatus = "IDLE";
  private listenerAttached = false;
  private recoveryTimer: NodeJS.Timeout | null = null;
  private recoveryAttempt = 0;

  constructor(
    private readonly sessions: EncryptedSessionStore,
    private readonly eventSink: EventSink,
    private readonly sendIntervalMs = 1000,
    private readonly eventTransportStatus: () => { healthy: boolean; pending: number } = () => ({
      healthy: true,
      pending: 0,
    }),
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
      this.setApi(await zalo.login(credentials));
      await this.loadProfile();
      this.startListener();
      this.status = "CONNECTED";
      console.info("BOT_CONNECTED restored_session=true");
    } catch (error) {
      this.setApi(null);
      this.status = "AUTH_REQUIRED";
      this.lastError = this.safeError(error);
      console.warn("BOT_AUTH_REQUIRED saved_session_invalid=true");
      reportGatewayError(
        "BOT_SESSION_INVALID",
        `Session Zalo đã lưu không dùng được nữa, cần quét lại mã QR: ${this.lastError}`,
        "CRITICAL",
      );
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
    this.setApi(null);
    const credentials = await this.sessions.load();
    if (!credentials) {
      this.status = "AUTH_REQUIRED";
      return this.connect();
    }
    try {
      this.status = "CONNECTING";
      this.setApi(await new Zalo().login(credentials));
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
    this.setApi(null);
    this.status = "DISCONNECTED";
    this.qrImage = null;
    this.qrStatus = null;
    await this.sessions.clear();
    console.info("BOT_DISCONNECTED session_removed=true");
    return this.getStatus();
  }

  async getStatus(): Promise<BotState> {
    const transport = this.eventTransportStatus();
    return {
      status: this.status,
      account_name: this.accountName,
      zalo_user_id: this.zaloUserId,
      avatar_url: this.avatarUrl,
      session_active: await this.sessions.exists(),
      qr_status: this.qrStatus,
      last_error: this.lastError,
      listener_status: this.listenerStatus,
      events_healthy:
        this.status === "CONNECTED"
        && this.listenerStatus === "LISTENING"
        && transport.healthy,
      event_backlog: transport.pending,
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
      const missing = chunk.filter((groupId) => !detail.gridInfoMap[groupId]);
      if (missing.length > 0) {
        throw new GatewayError(
          "GROUP_SYNC_INCOMPLETE",
          `Zalo trả thiếu ${missing.length}/${chunk.length} nhóm; chưa áp dụng lần đồng bộ này.`,
          503,
        );
      }
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
    return this.resolveMembers(group);
  }

  /**
   * Members of many groups in one round trip.
   *
   * getGroupInfo takes a list, so building a company-wide roster costs one call
   * rather than one per customer. Groups Zalo does not return are omitted rather
   * than failing the batch: one stale group must not hide every other member.
   */
  async getGroupMembersBatch(groupIds: string[]): Promise<Record<string, ZaloMember[]>> {
    const api = this.requireApi();
    const unique = [...new Set(groupIds)].filter(Boolean);
    const result: Record<string, ZaloMember[]> = {};
    for (let index = 0; index < unique.length; index += 50) {
      const chunk = unique.slice(index, index + 50);
      const detail = await api.getGroupInfo(chunk);
      const present = chunk.filter((groupId) => {
        if (detail.gridInfoMap[groupId]) return true;
        console.warn("ZALO_GROUP_MISSING_IN_BATCH group_id=%s", groupId);
        return false;
      });
      // A group whose member list Zalo truncates needs follow-up calls to name
      // everyone. Resolving groups one after another turns that into a wait
      // proportional to the customer count, which runs past the caller's
      // timeout; a small pool keeps it flat without hammering Zalo.
      let cursor = 0;
      const workers = Array.from({ length: Math.min(4, present.length) }, async () => {
        while (cursor < present.length) {
          const groupId = present[cursor++];
          if (!groupId) return;
          result[groupId] = await this.resolveMembers(detail.gridInfoMap[groupId]!);
        }
      });
      await Promise.all(workers);
    }
    return result;
  }

  private async resolveMembers(group: GroupDetail): Promise<ZaloMember[]> {
    const api = this.requireApi();
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
        group.groupId,
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

  /** Swapping the API instance also invalidates the listener bound to the old one. */
  private setApi(api: API | null): void {
    this.clearRecoveryTimer();
    this.recoveryAttempt = 0;
    this.listenerAttached = false;
    this.listenerStatus = api ? "IDLE" : "STOPPED";
    this.api = api;
  }

  private async runQrLogin(): Promise<void> {
    try {
      const zalo = new Zalo();
      this.setApi(await zalo.loginQR({}, (event) => this.handleQrEvent(event)));
      const context = this.requireApiUnchecked().getContext();
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
      this.setApi(null);
      this.status = "AUTH_REQUIRED";
      this.qrStatus = "AUTH_REQUIRED";
      this.lastError = this.safeError(error);
      console.error("BOT_AUTH_REQUIRED qr_login_failed=true");
      reportGatewayError(
        "BOT_QR_LOGIN_FAILED",
        `Đăng nhập Zalo bằng mã QR thất bại: ${this.lastError}`,
        "ERROR",
      );
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
    const api = this.api;
    if (!api) return;
    if (!this.listenerAttached) {
      api.listener.on("connected", () => {
        if (this.api !== api) return;
        this.listenerStatus = "LISTENING";
        this.recoveryAttempt = 0;
        this.clearRecoveryTimer();
        console.info("ZALO_LISTENER_CONNECTED");
      });
      api.listener.on("disconnected", (code, reason) => {
        if (this.api !== api || code === CloseReason.ManualClosure) return;
        // zca-js may still retry on its own; `closed` tells us when it gave up.
        this.listenerStatus = "RECONNECTING";
        console.warn("ZALO_LISTENER_DISCONNECTED code=%d reason=%s", code, reason || "unknown");
      });
      api.listener.on("closed", (code, reason) => {
        if (this.api !== api) return;
        this.handleListenerClosed(code, reason);
      });
      api.listener.on("error", (error) => {
        console.error("ZALO_LISTENER_ERROR", this.safeError(error));
      });
      api.listener.on("message", (message) => this.handleMessage(message));
      api.listener.on("reaction", (reaction) => this.handleReaction(reaction));
      this.listenerAttached = true;
    }
    try {
      this.listenerStatus = "STARTING";
      api.listener.start({ retryOnClose: true });
      console.info("ZALO_LISTENER_STARTED");
    } catch (error) {
      this.listenerStatus = "CLOSED";
      this.lastError = this.safeError(error);
      console.error("ZALO_LISTENER_START_FAILED", this.lastError);
      reportGatewayError(
        "ZALO_LISTENER_START_FAILED",
        `Không mở được kênh nhận tin nhắn Zalo: ${this.lastError}`,
        "ERROR",
      );
      this.scheduleListenerRecovery();
    }
  }

  /**
   * `closed` only fires once zca-js has stopped retrying, so the event channel
   * is dead until we act. Leaving `status` at CONNECTED here would make the
   * backend believe replies are still observable and tag customers forever.
   */
  private handleListenerClosed(code: number, reason: string): void {
    const detail = reason || `code ${code}`;
    if (code === CloseReason.ManualClosure) {
      this.listenerStatus = "STOPPED";
      return;
    }
    this.listenerStatus = "CLOSED";
    if (code === CloseReason.KickConnection || code === CloseReason.DuplicateConnection) {
      this.setApi(null);
      this.status = "AUTH_REQUIRED";
      this.qrStatus = "AUTH_REQUIRED";
      this.lastError = `Zalo đã đóng phiên đăng nhập của bot (${detail}). Hãy quét lại mã QR.`;
      console.error("BOT_AUTH_REQUIRED listener_closed=%d reason=%s", code, detail);
      reportGatewayError(
        "BOT_SESSION_KILLED",
        `Zalo đã đóng phiên của bot (${detail}). Bot ngừng hoạt động cho tới khi quét lại mã QR.`,
        "CRITICAL",
        { close_code: String(code) },
      );
      return;
    }
    this.lastError = `Kênh sự kiện Zalo đã đóng (${detail}). Gateway đang tự kết nối lại.`;
    console.error("ZALO_LISTENER_CLOSED code=%d reason=%s", code, detail);
    reportGatewayError(
      "ZALO_EVENT_CHANNEL_CLOSED",
      `Mất kênh nhận tin nhắn Zalo (${detail}). Đang tự kết nối lại; trong lúc đó tag tên tự động tạm dừng.`,
      "ERROR",
      { close_code: String(code) },
    );
    this.scheduleListenerRecovery();
  }

  private scheduleListenerRecovery(): void {
    if (this.recoveryTimer) return;
    const api = this.api;
    if (!api) return;
    const delayMs =
      LISTENER_RECOVERY_DELAYS_MS[
        Math.min(this.recoveryAttempt, LISTENER_RECOVERY_DELAYS_MS.length - 1)
      ] ?? 300_000;
    this.recoveryAttempt += 1;
    console.warn(
      "ZALO_LISTENER_RECOVERY_SCHEDULED attempt=%d delay_ms=%d",
      this.recoveryAttempt,
      delayMs,
    );
    this.recoveryTimer = setTimeout(() => {
      this.recoveryTimer = null;
      if (this.api !== api) return;
      try {
        this.listenerStatus = "STARTING";
        api.listener.start({ retryOnClose: true });
        console.info("ZALO_LISTENER_RECOVERY_STARTED attempt=%d", this.recoveryAttempt);
      } catch (error) {
        this.listenerStatus = "CLOSED";
        console.error("ZALO_LISTENER_RECOVERY_FAILED", this.safeError(error));
        this.scheduleListenerRecovery();
      }
    }, delayMs);
  }

  private clearRecoveryTimer(): void {
    if (!this.recoveryTimer) return;
    clearTimeout(this.recoveryTimer);
    this.recoveryTimer = null;
  }

  private stopListener(): void {
    this.clearRecoveryTimer();
    this.recoveryAttempt = 0;
    this.listenerStatus = "STOPPED";
    try {
      this.api?.listener.stop();
    } catch (error) {
      console.warn("ZALO_LISTENER_STOP_FAILED", this.safeError(error));
    }
  }

  private requireApiUnchecked(): API {
    if (!this.api) throw new GatewayError("BOT_DISCONNECTED", "Bot chưa kết nối với Zalo.", 409);
    return this.api;
  }

  private handleMessage(message: Message): void {
    if (message.isSelf || message.type !== ThreadType.Group) return;
    const mentions = message.data.mentions ?? [];
    const messageAliases = usableZaloIds([
      message.data.msgId,
      message.data.cliMsgId,
      message.data.realMsgId,
      message.data.actionId,
    ]);
    const messageId = messageAliases[0] ?? null;
    if (!messageId) return;
    const content = incomingMessageContent(message.data);
    const event: IncomingGroupMessageEvent = {
      event_type: "message",
      group_id: message.threadId,
      message_id: messageId,
      message_aliases: messageAliases,
      sender_id: this.normalizeMemberId(message.data.uidFrom),
      sender_display_name: message.data.dName || null,
      sent_at: zaloTimestampToIso(message.data.ts),
      // Trimmed on purpose: an oversized body would be rejected by the backend
      // and the reply acknowledgement it carries would be lost for good.
      content: content.slice(0, MAX_EVENT_CONTENT_LENGTH),
      mentions: mentions.slice(0, MAX_EVENT_MENTIONS).map((mention) => ({
        user_id: this.normalizeMemberId(mention.uid),
        position: mention.pos,
        length: mention.len,
        text: content.slice(mention.pos, mention.pos + mention.len),
      })),
    };
    this.forwardEventInOrder(event);
  }

  private handleReaction(reaction: Reaction): void {
    const event = incomingReactionEvent(reaction);
    if (!event) return;
    this.forwardEventInOrder(event);
  }

  private forwardEventInOrder(event: IncomingGroupEvent): void {
    const previous = this.inboundTails.get(event.group_id) ?? Promise.resolve();
    const current = previous
      .catch(() => undefined)
      .then(() => this.eventSink(event));
    this.inboundTails.set(event.group_id, current);
    void current.catch((error) => {
      console.error(
        "ZALO_EVENT_FORWARD_FAILED group_id=%s error=%s",
        event.group_id,
        this.safeError(error),
      );
      // A dropped event means a customer reply was never acknowledged, so the
      // bot may keep tagging someone who already answered.
      reportGatewayError(
        "ZALO_EVENT_DROPPED",
        `Không đẩy được sự kiện Zalo sang backend: ${this.safeError(error)}.`
          + " Có thể bỏ sót tin nhắn/reaction và tag lại người đã phản hồi.",
        "CRITICAL",
        { zalo_group_id: event.group_id },
      );
    }).finally(() => {
      if (this.inboundTails.get(event.group_id) === current) {
        this.inboundTails.delete(event.group_id);
      }
    });
  }

  private safeError(error: unknown): string {
    return error instanceof Error ? error.message : "Zalo API gặp lỗi không xác định.";
  }

  private normalizeMemberId(userId: string): string {
    return normalizeZaloMemberId(userId);
  }
}
