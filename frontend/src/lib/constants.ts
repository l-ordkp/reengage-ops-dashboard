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
  lead: "Lead",
  operator: "Operator",
  new_operator: "New Operator",
  viewer: "Viewer",
};
