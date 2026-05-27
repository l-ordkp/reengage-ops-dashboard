export const PRIORITY_COLOR: Record<string, string> = {
  CRITICAL: "text-red-500",
  URGENT: "text-orange-400",
  NORMAL: "text-green-400",
};

export const STATUS_COLOR: Record<string, string> = {
  PENDING: "text-yellow-400",
  RESPONDED: "text-green-400",
  EXPIRED: "text-gray-500",
};

export const PRIORITY_ICON: Record<string, string> = {
  CRITICAL: "!!!",
  URGENT: "!!",
  NORMAL: "-",
};

export const STATUS_ICON: Record<string, string> = {
  PENDING: "\u25CF",
  RESPONDED: "\u2713",
  EXPIRED: "\u2715",
};

export const ROLE_LABELS: Record<string, string> = {
  manager: "Manager",
  lead: "Lead",
  tenured_operator: "Tenured Operator",
  new_operator: "New Operator",
};

// "Time left until platform deadline" formatter.
//   <= 0  : "Expired"
//   < 24h : "Nh"           (e.g., "7h")
//   else  : "Xd Yh" or "Xd" if hours == 0  (e.g., "1d 5h", "6d")
export function formatHoursLeft(h: number | null | undefined): string {
  if (h == null) return "-";
  if (h <= 0) return "Expired";
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  const r = h % 24;
  return r === 0 ? `${d}d` : `${d}d ${r}h`;
}
