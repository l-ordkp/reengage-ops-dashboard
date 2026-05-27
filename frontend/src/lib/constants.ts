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

// All timestamps stored server-side are in UTC. Operators are in India, so
// for any concrete timestamp we display we convert to IST and label it,
// rather than relying on the viewer's browser timezone (which differs
// between an IST operator and a US-based lead and would give them
// different strings for the same row).
export function formatIST(iso: string | Date | null | undefined): string {
  if (!iso) return "—";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (isNaN(d.getTime())) return "—";
  return (
    d.toLocaleString("en-US", {
      timeZone: "Asia/Kolkata",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    }) + " IST"
  );
}

// review_date is a date-only string in the restaurant's local market (US/CT),
// because the underlying review was posted by a US customer. Don't convert
// it — just label so an IST viewer doesn't mis-read it as their own date.
export function formatReviewDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr + "T00:00:00Z");
  if (isNaN(d.getTime())) return "—";
  const label = d.toLocaleDateString("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  return `${label} (US/CT)`;
}

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
