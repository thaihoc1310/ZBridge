export const VIETNAM_TIME_ZONE = "Asia/Ho_Chi_Minh";

export function formatDate(value?: string | null, withTime = true) {
  if (!value) return "Chưa có";
  return new Intl.DateTimeFormat("vi-VN", {
    timeZone: VIETNAM_TIME_ZONE,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
  }).format(new Date(value));
}

function vietnamWallClock(date: Date) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: VIETNAM_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const read = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  return {
    year: read("year"),
    month: read("month"),
    day: read("day"),
    hour: read("hour"),
    minute: read("minute"),
  };
}

/** `datetime-local` value as Vietnam wall clock, not the browser timezone. */
export function toDatetimeLocalValue(iso?: string | null) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const { year, month, day, hour, minute } = vietnamWallClock(date);
  return `${year}-${month}-${day}T${hour}:${minute}`;
}

export function fromDatetimeLocalValue(value: string) {
  if (!value.trim()) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!match) return null;
  const [, year, month, day, hour, minute] = match;
  const date = new Date(`${year}-${month}-${day}T${hour}:${minute}:00+07:00`);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

export function nowDatetimeLocalValue() {
  return toDatetimeLocalValue(new Date().toISOString());
}

export function initials(name?: string | null) {
  return (name || "ZG")
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}
