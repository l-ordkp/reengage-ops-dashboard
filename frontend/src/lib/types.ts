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
  review_date: string;       // date-only, in restaurant local time (US/CT)
  hours_left: number;
  portal_link: string;
  // Populated by search/queue enrichment. ISO string in UTC; render with formatIST().
  completed_at?: string | null;
  assigned_at?: string | null;
  assigned_to?: string | null;
  assignment_status?: string | null;
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
// Math: total = out_of_scope + pending + responded + expired
//       loop_responded ⊆ responded  (subset, not part of the partition sum)
export interface ChainHealth {
  chain_name: string;
  total: number;             // all reviews in 14d for this ReEngage chain
  out_of_scope: number;      // = total - in_scope
  in_scope: number;          // matches an active config
  pending: number;           // in-scope, not yet responded, not expired
  responded: number;         // in-scope, is_replied OR is_loop_replied
  loop_responded: number;    // in-scope, is_loop_replied (subset of responded)
  expired: number;           // in-scope, past window, no reply
  critical: number;          // pending AND hours_left <= 24 (act today)
  urgent: number;            // pending AND 24 < hours_left <= 48 (act by tomorrow)
  has_response: number;
  avg_rating: number;
  locations: number;
  response_rate: number;     // responded / in_scope
  ai_coverage: number;       // has_response / in_scope
  loop_coverage: number;     // loop_responded / in_scope
}

export interface ChainHealthSummary {
  total: number;
  out_of_scope: number;
  in_scope: number;
  pending: number;
  responded: number;
  loop_responded: number;
  expired: number;
  critical: number;
  urgent: number;
}

// ── Flow (period activity) ───────────────────────────────────────────────────
// Independent event counts over the last N days, each by its own event date.
// They do NOT sum, and are NOT reconciled with the stock partition above.
export interface FlowMetric {
  total: number;
  doordash: number;
  ubereats: number;
}
export interface ChainHealthFlow {
  period_start: string;   // ISO date (America/Chicago)
  period_end: string;
  ingested: FlowMetric;   // posted in the window
  solved: FlowMetric;     // Loop-completed in the window (by completed_at)
  missed: FlowMetric;     // deadline fell in the window, not replied by deadline
}

export interface ChainHealthResponse {
  summary: ChainHealthSummary;
  chains: ChainHealth[];
  flow?: ChainHealthFlow;
}

// ── Chain Value ─────────────────────────────────────────────────────────────
export interface ChainValueRow {
  platform: string;
  total_reviews: number;
  in_scope: number;
  responded: number;
  loop_responded: number;
}

export interface ChainValueResponse {
  chain: string;
  overall: ChainValueRow;
  platforms: ChainValueRow[];
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
