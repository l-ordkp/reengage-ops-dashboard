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
) -> None:
    """Create a synthetic completed assignment (used when extension marks a review without prior assignment)."""
    import uuid
    now = _now_str()
    safe_review_uid = _escape_sql(review_uid)
    safe_order_id = _escape_sql(order_id)
    safe_operator_email = _escape_sql(operator_email)
    safe_chain_name = _escape_sql(chain_name)
    safe_platform = _escape_sql(platform)
    bq_exec(f"""
        INSERT INTO `{TABLE_ASSIGNMENTS}`
            (assignment_id, review_uid, order_id, operator_email,
             chain_name, platform, days_left, status, assigned_at, completed_at)
        VALUES
            ('{uuid.uuid4()}', '{safe_review_uid}', '{safe_order_id}', '{safe_operator_email}',
             '{safe_chain_name}', '{safe_platform}', 0, 'completed',
             TIMESTAMP('{now}'), TIMESTAMP('{now}'))
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
    Mark pending assignments as expired if the review's response window has passed.
    Uses real review_timestamp to compute days_left (not the stale snapshot).
    """
    bq_exec(f"""
    UPDATE `{TABLE_ASSIGNMENTS}` a
    SET status = 'expired'
    WHERE a.status = 'pending'
      AND (
        a.days_left <= 0
        OR EXISTS (
          SELECT 1 FROM `{TABLE_AUTOMATION_REVIEWS}` ar
          WHERE ar.order_id = a.order_id
            AND CASE
              WHEN a.platform = 'Doordash' THEN
                DATE_DIFF(DATE_ADD(DATE(DATETIME(COALESCE(ar.review_timestamp, ar.order_timestamp), 'America/Chicago')), INTERVAL 7 DAY), CURRENT_DATE('America/Chicago'), DAY)
              WHEN a.platform = 'UberEats' THEN
                DATE_DIFF(DATE_ADD(DATE(DATETIME(COALESCE(ar.review_timestamp, ar.order_timestamp), 'America/Chicago')), INTERVAL 14 DAY), CURRENT_DATE('America/Chicago'), DAY)
              ELSE 0
            END <= 0
        )
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
