// ── Review ──────────────────────────────────────────────────────────────────
export interface Review {
  review_uid: string;
  order_id: string;
  review_id: string;
  chain_name: string;
  brand_name: string;
  platform: string;
  slug: string;
  store_id: string;
  customer_name: string;
  customer_id: string;
  orders_count: number;
  customer_type: string;
  star_rating: number;
  rating_type: string;
  rating_value: string;
  rating_numeric: number;
  rating_display: string;
  review_text: string;
  items: string;
  order_value: number;
  review_date: string;
  days_left: number;
  portal_link: string;
  response_text: string | null;
  response_type: string | null;
  coupon_value: number | null;
  config_id: string | null;
  status: string;
  priority: string;
  is_replied: boolean;
  portal_username: string;
  portal_password: string;
  assignment_id?: string;
}

// ── User ────────────────────────────────────────────────────────────────────
export interface User {
  email: string;
  name: string;
  role: string;
  approved: boolean;
  reduction_pct: number;
  added_by: string;
  created_at: string;
  updated_at: string;
}

// ── Assignment ──────────────────────────────────────────────────────────────
export interface Assignment {
  assignment_id: string;
  review_uid: string;
  order_id: string;
  operator_email: string;
  chain_name: string;
  platform: string;
  days_left: number;
  status: string;
  assigned_at: string;
  completed_at: string | null;
}

// ── Operator Performance ────────────────────────────────────────────────────
export interface OperatorPerformance {
  operator_email: string;
  name?: string;
  role?: string;
  total_assigned: number;
  assigned_today: number;
  assigned_this_week: number;
  completed: number;
  expired: number;
  pending: number;
  completion_rate: number;
}

// ── Daily Breakdown ─────────────────────────────────────────────────────────
export interface DailyBreakdown {
  operator_email: string;
  name?: string;
  assign_date: string;
  assigned: number;
  completed: number;
  expired: number;
  pending: number;
  completion_pct: number;
}

// ── Chain Breakdown ─────────────────────────────────────────────────────────
export interface ChainBreakdown {
  operator_email: string;
  chain_name: string;
  platform: string;
  assigned: number;
  completed: number;
  expired: number;
  pending: number;
}

// ── Chain Health ─────────────────────────────────────────────────────────────
export interface ChainHealth {
  chain_name: string;
  total: number;
  responded: number;
  pending: number;
  expired: number;
  critical: number;
  has_response: number;
  avg_rating: number;
  locations: number;
  response_rate: number;
  ai_coverage: number;
}

// ── Response Config ─────────────────────────────────────────────────────────
export interface ResponseConfig {
  config_id: string;
  config_name: string;
  chain_name: string;
  paused: boolean;
  response_type: string;
  tonality: string;
  vb_platforms: string[];
  ratings: number[];
  [key: string]: unknown;
}

// ── Ops Log Entry ───────────────────────────────────────────────────────────
export interface OpsLogEntry {
  id: string;
  review_uid: string;
  platform: string;
  chain_name: string;
  action: string;
  operator_email: string;
  performed_by: string;
  remarks: string;
  processing_timestamp: string;
}

// ── Paginated Response ──────────────────────────────────────────────────────
export interface ReviewsResponse {
  items: Review[];
  total: number;
  page: number;
  page_size: number;
}

// ── Review Stats ────────────────────────────────────────────────────────────
export interface ReviewStats {
  total: number;
  pending: number;
  responded: number;
  expired: number;
  critical: number;
  auto_posted: number;
  has_response: number;
}

// ── Auth User ───────────────────────────────────────────────────────────────
export interface AuthUser {
  email: string;
  name: string;
  role: string;
}
