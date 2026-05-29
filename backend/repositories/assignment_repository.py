"""Assignment data access — `reengage_dashboard_v2_assignments` table writes/reads."""
from __future__ import annotations

import pandas as pd

from backend.clients.bq_client import bq_exec, bq_read
from backend.config import TABLE_ASSIGNMENTS, TABLE_AUTOMATION_REVIEWS
from backend.utils.cache import cached

# ── Helpers ───────────────────────────────────────────────────────────────────

def _escape_sql(value: str) -> str:
    """Escape single quotes so the value is safe to embed inside a SQL literal."""
    return (value or "").replace("'", "''")


def _now_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ── Reads ─────────────────────────────────────────────────────────────────────

@cached(ttl=120)
def fetch_all_assignments_14d() -> pd.DataFrame:
    """All assignments in the last 14 days (excludes 'reassigned')."""
    return bq_read(f"""
        SELECT assignment_id, review_uid, order_id, operator_email,
               chain_name, platform, days_left, status, assigned_at, completed_at
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY))
          AND status != 'reassigned'
        ORDER BY assigned_at DESC
    """)


@cached(ttl=120)
def fetch_my_pending_assignments(email: str) -> pd.DataFrame:
    """Operator's pending assignments only."""
    safe_email = _escape_sql(email)
    return bq_read(f"""
        SELECT assignment_id, review_uid, order_id, chain_name, platform,
               days_left, status, assigned_at, completed_at
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE operator_email = '{safe_email}'
          AND status = 'pending'
          AND assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY))
        ORDER BY days_left ASC
    """)


def fetch_already_assigned_uids() -> set[str]:
    """UIDs of reviews that have a pending/completed assignment in the last 14 days."""
    df = bq_read(f"""
        SELECT DISTINCT review_uid
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE status IN ('pending', 'completed')
          AND assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY))
    """)
    return set(df["review_uid"].tolist()) if not df.empty else set()


def fetch_assignment_by_order_id(order_id: str) -> pd.DataFrame:
    """Find the most recent assignment for an order_id (used by extension mark-responded)."""
    safe_order_id = _escape_sql(order_id)
    return bq_read(f"""
        SELECT assignment_id FROM `{TABLE_ASSIGNMENTS}`
        WHERE order_id = '{safe_order_id}'
        LIMIT 1
    """)


def fetch_assignments_by_ids(
    review_uids: list[str], order_ids: list[str],
) -> pd.DataFrame:
    """Bulk lookup of any assignment whose review_uid OR order_id is in the
    given lists. Used by the observed-responded flow to classify each incoming
    item as already-completed / pending / new in a single round-trip."""
    rev_quoted = ", ".join(f"'{_escape_sql(u)}'" for u in review_uids if u)
    ord_quoted = ", ".join(f"'{_escape_sql(o)}'" for o in order_ids if o)
    where_clauses = []
    if rev_quoted:
        where_clauses.append(f"review_uid IN ({rev_quoted})")
    if ord_quoted:
        where_clauses.append(f"order_id IN ({ord_quoted})")
    if not where_clauses:
        return pd.DataFrame(columns=["assignment_id", "review_uid", "order_id", "status"])
    return bq_read(f"""
        SELECT assignment_id, review_uid, order_id, status
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE {' OR '.join(where_clauses)}
    """)


# ── Writes ────────────────────────────────────────────────────────────────────

def insert_assignments(rows: list[dict]) -> None:
    """Bulk insert new assignment rows (status='pending')."""
    if not rows:
        return
    now = _now_str()
    value_rows = []
    for row in rows:
        value_rows.append(
            f"('{row['assignment_id']}', '{_escape_sql(row['review_uid'])}', '{_escape_sql(row.get('order_id', ''))}', "
            f"'{_escape_sql(row['operator_email'])}', '{_escape_sql(row['chain_name'])}', '{_escape_sql(row['platform'])}', "
            f"{row['days_left']}, 'pending', TIMESTAMP('{now}'), NULL)"
        )
    batch_size = 500
    for batch_start in range(0, len(value_rows), batch_size):
        batch = value_rows[batch_start:batch_start + batch_size]
        bq_exec(f"""
        INSERT INTO `{TABLE_ASSIGNMENTS}`
            (assignment_id, review_uid, order_id, operator_email,
             chain_name, platform, days_left, status, assigned_at, completed_at)
        VALUES {', '.join(batch)}
        """)


def mark_assignment_completed(assignment_id: str) -> None:
    """Set an assignment to completed in our own table.

    We deliberately do NOT write `is_loop_replied=TRUE` to elt_data.automation_reviews
    anymore — single-row UPDATEs on that elt-owned table were causing concurrent-
    update collisions with the dbt MERGE that owns the partition. Loop-replied
    state is now derived at read time by JOIN'ing automation_reviews to our
    reengage_dashboard_v2_assignments table on review_uid (see fetch_chain_totals_14d
    and fetch_reviews_14d).
    """
    now = _now_str()
    safe_assignment_id = _escape_sql(assignment_id)
    bq_exec(f"""
    UPDATE `{TABLE_ASSIGNMENTS}`
    SET status = 'completed', completed_at = TIMESTAMP('{now}')
    WHERE assignment_id = '{safe_assignment_id}'
    """)


def update_assignment_by_order_id(order_id: str) -> None:
    """Mark pending assignment(s) for this order_id as completed (extension flow)."""
    now = _now_str()
    safe_order_id = _escape_sql(order_id)
    bq_exec(f"""
        UPDATE `{TABLE_ASSIGNMENTS}`
        SET status = 'completed', completed_at = TIMESTAMP('{now}')
        WHERE order_id = '{safe_order_id}' AND status = 'pending'
    """)


def insert_completed_assignment(
    review_uid: str, order_id: str, operator_email: str,
    chain_name: str, platform: str,
    platform_reply_id: str = "", platform_coupon_id: str = "",
) -> None:
    """Create a synthetic completed assignment (used when extension marks a review without prior assignment)."""
    import uuid
    now = _now_str()
    safe_review_uid = _escape_sql(review_uid)
    safe_order_id = _escape_sql(order_id)
    safe_operator_email = _escape_sql(operator_email)
    safe_chain_name = _escape_sql(chain_name)
    safe_platform = _escape_sql(platform)
    reply_id_sql = f"'{_escape_sql(platform_reply_id)}'" if platform_reply_id else "NULL"
    coupon_id_sql = f"'{_escape_sql(platform_coupon_id)}'" if platform_coupon_id else "NULL"
    bq_exec(f"""
        INSERT INTO `{TABLE_ASSIGNMENTS}`
            (assignment_id, review_uid, order_id, operator_email,
             chain_name, platform, days_left, status, assigned_at, completed_at,
             platform_reply_id, platform_coupon_id)
        VALUES
            ('{uuid.uuid4()}', '{safe_review_uid}', '{safe_order_id}', '{safe_operator_email}',
             '{safe_chain_name}', '{safe_platform}', 0, 'completed',
             TIMESTAMP('{now}'), TIMESTAMP('{now}'),
             {reply_id_sql}, {coupon_id_sql})
    """)


def bulk_insert_observed_assignments(
    items: list[dict], operator_email: str,
) -> None:
    """Insert one completed assignment per observed-responded item. Each item:
    {review_uid, order_id, platform, chain_name}. operator_email is the
    observer (the operator whose browser captured the platform's signal),
    not a claim that they replied. The distinguishing remark goes into
    ops_log, not into the assignment row itself."""
    if not items:
        return
    import uuid
    now = _now_str()
    safe_operator_email = _escape_sql(operator_email)
    value_rows = []
    for item in items:
        value_rows.append(
            f"('{uuid.uuid4()}', '{_escape_sql(item['review_uid'])}', '{_escape_sql(item['order_id'])}', "
            f"'{safe_operator_email}', '{_escape_sql(item.get('chain_name', ''))}', '{_escape_sql(item['platform'])}', "
            f"0, 'completed', TIMESTAMP('{now}'), TIMESTAMP('{now}'), NULL, NULL)"
        )
    batch_size = 500
    for start in range(0, len(value_rows), batch_size):
        batch = value_rows[start:start + batch_size]
        bq_exec(f"""
            INSERT INTO `{TABLE_ASSIGNMENTS}`
                (assignment_id, review_uid, order_id, operator_email,
                 chain_name, platform, days_left, status, assigned_at, completed_at,
                 platform_reply_id, platform_coupon_id)
            VALUES {', '.join(batch)}
        """)


def bulk_complete_pending_by_ids(
    review_uids: list[str], order_ids: list[str],
) -> None:
    """Flip any pending assignments matching the given review_uids or order_ids
    to status='completed'. Used by the observed-responded flow when an
    operator was already assigned a review but the platform now reports it
    replied (merchant self-resolved while operator was prepping, or operator
    submitted directly via the platform UI bypassing our extension)."""
    now = _now_str()
    rev_quoted = ", ".join(f"'{_escape_sql(u)}'" for u in review_uids if u)
    ord_quoted = ", ".join(f"'{_escape_sql(o)}'" for o in order_ids if o)
    where_clauses = []
    if rev_quoted:
        where_clauses.append(f"review_uid IN ({rev_quoted})")
    if ord_quoted:
        where_clauses.append(f"order_id IN ({ord_quoted})")
    if not where_clauses:
        return
    bq_exec(f"""
        UPDATE `{TABLE_ASSIGNMENTS}`
        SET status = 'completed', completed_at = TIMESTAMP('{now}')
        WHERE status = 'pending' AND ({' OR '.join(where_clauses)})
    """)


def update_assignment_platform_ids(
    order_id: str, platform_reply_id: str = "", platform_coupon_id: str = "",
) -> None:
    """Stamp the platform-issued IDs onto the most recent assignment row for this order.

    Run after update_assignment_by_order_id so that pre-existing pending
    assignments (now marked completed) also pick up the platform reply/coupon
    IDs returned by DoorDash/UberEats at reply-submission time.
    """
    if not (platform_reply_id or platform_coupon_id):
        return
    safe_order_id = _escape_sql(order_id)
    set_parts = []
    if platform_reply_id:
        set_parts.append(f"platform_reply_id = '{_escape_sql(platform_reply_id)}'")
    if platform_coupon_id:
        set_parts.append(f"platform_coupon_id = '{_escape_sql(platform_coupon_id)}'")
    bq_exec(f"""
        UPDATE `{TABLE_ASSIGNMENTS}`
        SET {', '.join(set_parts)}
        WHERE order_id = '{safe_order_id}'
    """)


def mark_is_loop_replied(order_id: str) -> None:
    """No-op kept for backward compatibility with extension_manager callers.

    Previously this fired a single-row UPDATE on elt_data.automation_reviews
    to flip is_loop_replied=TRUE. That table is dbt-owned and our UPDATEs
    were colliding with the dbt MERGE (concurrent-update self-failures up to
    46% over the last 50 runs, breaking ClickHouse ingestion). Loop-replied
    status is now derived at read time from reengage_dashboard_v2_assignments
    (a Loop reply ⇔ an assignment row with status='completed' for that
    review_uid). We keep the function as a no-op so we don't break callers
    in the middle of a deploy.
    """
    _ = order_id  # intentionally unused


def expire_stale_assignments() -> None:
    """
    Mark pending assignments as expired once the platform deadline has passed.
    Recomputes the deadline from review_timestamp + N days against CURRENT_TIMESTAMP
    so the rule matches the live status engine (hour-precise, no date rounding).
    """
    bq_exec(f"""
    UPDATE `{TABLE_ASSIGNMENTS}` a
    SET status = 'expired'
    WHERE a.status = 'pending'
      AND EXISTS (
        SELECT 1 FROM `{TABLE_AUTOMATION_REVIEWS}` ar
        WHERE ar.order_id = a.order_id
          AND CURRENT_TIMESTAMP() >= CASE
            WHEN a.platform = 'Doordash' THEN
              TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 7 DAY)
            WHEN a.platform = 'UberEats' THEN
              TIMESTAMP_ADD(COALESCE(ar.review_timestamp, ar.order_timestamp), INTERVAL 14 DAY)
            ELSE CURRENT_TIMESTAMP()
          END
      )
    """)


def void_pending_assignments() -> None:
    """Mark all pending assignments as 'reassigned' (before a full redistribution)."""
    bq_exec(f"""
    UPDATE `{TABLE_ASSIGNMENTS}`
    SET status = 'reassigned'
    WHERE status = 'pending'
    """)


def redistribute_assignments_for_removed_operator(removed_email: str) -> int:
    """
    When a user is removed, reassign their pending reviews to other operators.
    Returns the number of reviews redistributed.
    """
    from collections import defaultdict
    from backend.config import ROLE_LEAD, TABLE_USERS

    safe_removed_email = _escape_sql(removed_email)
    orphaned_df = bq_read(f"""
        SELECT assignment_id, review_uid, order_id, chain_name, platform, days_left
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE operator_email = '{safe_removed_email}' AND status = 'pending'
        ORDER BY days_left ASC
    """)
    if orphaned_df.empty:
        return 0

    remaining_df = bq_read(f"""
        SELECT email FROM `{TABLE_USERS}`
        WHERE approved = TRUE AND role NOT IN ('{ROLE_LEAD}', 'manager') AND email != '{safe_removed_email}'
    """)
    if remaining_df.empty:
        return 0

    operators = remaining_df["email"].tolist()
    existing_df = bq_read(f"""
        SELECT operator_email, chain_name, platform
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE status = 'pending' AND operator_email != '{safe_removed_email}'
    """)

    combos_per_operator: dict[str, set] = defaultdict(set)
    counts_per_operator: dict[str, int] = defaultdict(int)
    if not existing_df.empty:
        for _, row in existing_df.iterrows():
            combos_per_operator[row["operator_email"]].add((row["chain_name"], row["platform"]))
            counts_per_operator[row["operator_email"]] += 1
    for operator_email in operators:
        combos_per_operator.setdefault(operator_email, set())
        counts_per_operator.setdefault(operator_email, 0)

    reviews_by_chain_platform: dict[tuple, list] = defaultdict(list)
    for _, row in orphaned_df.iterrows():
        reviews_by_chain_platform[(row["chain_name"], row["platform"])].append(row)

    now = _now_str()
    reassignments: list[tuple[str, str]] = []
    for (chain, platform), reviews in reviews_by_chain_platform.items():
        operators_with_combo = [op for op in operators if (chain, platform) in combos_per_operator[op]]
        operators_without_combo = [op for op in operators if (chain, platform) not in combos_per_operator[op]]
        operators_with_combo.sort(key=lambda op: counts_per_operator[op])
        operators_without_combo.sort(key=lambda op: (len(combos_per_operator[op]), counts_per_operator[op]))
        preferred_operators = operators_with_combo + operators_without_combo
        for review_index, row in enumerate(reviews):
            target_operator = preferred_operators[review_index % len(preferred_operators)]
            reassignments.append((row["assignment_id"], target_operator))
            counts_per_operator[target_operator] += 1
            combos_per_operator[target_operator].add((chain, platform))

    if reassignments:
        case_clauses = " ".join(
            f"WHEN '{_escape_sql(assignment_id)}' THEN '{_escape_sql(target_operator)}'"
            for assignment_id, target_operator in reassignments
        )
        assignment_id_list = ", ".join(
            f"'{_escape_sql(assignment_id)}'" for assignment_id, _ in reassignments
        )
        bq_exec(f"""
        UPDATE `{TABLE_ASSIGNMENTS}`
        SET operator_email = CASE assignment_id {case_clauses} END,
            assigned_at = TIMESTAMP('{now}')
        WHERE assignment_id IN ({assignment_id_list})
        """)
    return len(orphaned_df)
