/** Mirrors app/core/permissions.py — keep both lists in step. */
export const PERMISSIONS = {
  dashboardRead: "dashboard:read",
  botRead: "bot:read",
  botConnect: "bot:connect",
  botDisconnect: "bot:disconnect",
  customerRead: "customer:read",
  customerUpdate: "customer:update",
  customerSync: "customer:sync",
  messageSend: "message:send",
  mentionRead: "mention:read",
  mentionUpdate: "mention:update",
  debtReminderRead: "debt_reminder:read",
  debtReminderUpdate: "debt_reminder:update",
  activityRead: "activity:read",
  userRead: "user:read",
  userCreate: "user:create",
  userUpdate: "user:update",
  userDelete: "user:delete",
  roleRead: "role:read",
  roleManage: "role:manage",
} as const;

export type PermissionCode = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];
