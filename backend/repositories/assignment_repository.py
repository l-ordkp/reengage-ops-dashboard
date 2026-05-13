"""Assignment data access — `reengage_dashboard_v2_assignments` table writes/reads."""
from __future__ import annotations

import pandas as pd

from backend.clients.bq_client import bq_exec, bq_read
from backend.config import TABLE_ASSIGNMENTS, TABLE_AUTOMATION_REVIEWS
from backend.utils.cache import cached

# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe(val: str) -> str:
    return (val or "").replace("'", "''")


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
    se = _safe(email)
    return bq_read(f"""
        SELECT assignment_id, review_uid, order_id, chain_name, platform,
               days_left, status, assigned_at, completed_at
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE operator_email = '{se}'
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
    safe_id = _safe(order_id)
    return bq_read(f"""
        SELECT assignment_id FROM `{TABLE_ASSIGNMENTS}`
        WHERE order_id = '{safe_id}'
        LIMIT 1
    """)


# ── Writes ────────────────────────────────────────────────────────────────────

def insert_assignments(rows: list[dict]) -> None:
    """Bulk insert new assignment rows (status='pending')."""
    if not rows:
        return
    now = _now_str()
    values = []
    for r in rows:
        values.append(
            f"('{r['assignment_id']}', '{_safe(r['review_uid'])}', '{_safe(r.get('order_id', ''))}', "
            f"'{_safe(r['operator_email'])}', '{_safe(r['chain_name'])}', '{_safe(r['platform'])}', "
            f"{r['days_left']}, 'pending', TIMESTAMP('{now}'), NULL)"
        )
    batch_size = 500
    for i in range(0, len(values), batch_size):
        batch = values[i:i + batch_size]
        bq_exec(f"""
        INSERT INTO `{TABLE_ASSIGNMENTS}`
            (assignment_id, review_uid, order_id, operator_email,
             chain_name, platform, days_left, status, assigned_at, completed_at)
        VALUES {', '.join(batch)}
        """)


def mark_assignment_completed(assignment_id: str) -> None:
    """Set an assignment to completed and propagate `is_loop_replied=TRUE`."""
    now = _now_str()
    sa = _safe(assignment_id)
    bq_exec(f"""
    UPDATE `{TABLE_ASSIGNMENTS}`
    SET status = 'completed', completed_at = TIMESTAMP('{now}')
    WHERE assignment_id = '{sa}'
    """)
    bq_exec(f"""
    UPDATE `{TABLE_AUTOMATION_REVIEWS}`
    SET is_loop_replied = TRUE
    WHERE order_id IN (
        SELECT order_id FROM `{TABLE_ASSIGNMENTS}` WHERE assignment_id = '{sa}'
    )
    """)


def update_assignment_by_order_id(order_id: str) -> None:
    """Mark pending assignment(s) for this order_id as completed (extension flow)."""
    now = _now_str()
    safe_id = _safe(order_id)
    bq_exec(f"""
        UPDATE `{TABLE_ASSIGNMENTS}`
        SET status = 'completed', completed_at = TIMESTAMP('{now}')
        WHERE order_id = '{safe_id}' AND status = 'pending'
    """)


def insert_completed_assignment(
    review_uid: str, order_id: str, operator_email: str,
    chain_name: str, platform: str,
) -> None:
    """Create a synthetic completed assignment (used when extension marks a review without prior assignment)."""
    import uuid
    now = _now_str()
    bq_exec(f"""
        INSERT INTO `{TABLE_ASSIGNMENTS}`
            (assignment_id, review_uid, order_id, operator_email,
             chain_name, platform, days_left, status, assigned_at, completed_at)
        VALUES
            ('{uuid.uuid4()}', '{_safe(review_uid)}', '{_safe(order_id)}', '{_safe(operator_email)}',
             '{_safe(chain_name)}', '{_safe(platform)}', 0, 'completed',
             TIMESTAMP('{now}'), TIMESTAMP('{now}'))
    """)


def mark_is_loop_replied(order_id: str) -> None:
    """Set is_loop_replied=TRUE on automation_reviews for a given order."""
    safe_id = _safe(order_id)
    bq_exec(f"""
        UPDATE `{TABLE_AUTOMATION_REVIEWS}`
        SET is_loop_replied = TRUE
        WHERE order_id = '{safe_id}'
    """)


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

    se = _safe(removed_email)
    orphaned_df = bq_read(f"""
        SELECT assignment_id, review_uid, order_id, chain_name, platform, days_left
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE operator_email = '{se}' AND status = 'pending'
        ORDER BY days_left ASC
    """)
    if orphaned_df.empty:
        return 0

    remaining_df = bq_read(f"""
        SELECT email FROM `{TABLE_USERS}`
        WHERE approved = TRUE AND role NOT IN ('{ROLE_LEAD}', 'manager') AND email != '{se}'
    """)
    if remaining_df.empty:
        return 0

    operators = remaining_df["email"].tolist()
    existing_df = bq_read(f"""
        SELECT operator_email, chain_name, platform
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE status = 'pending' AND operator_email != '{se}'
    """)

    op_combos: dict[str, set] = defaultdict(set)
    op_counts: dict[str, int] = defaultdict(int)
    if not existing_df.empty:
        for _, row in existing_df.iterrows():
            op_combos[row["operator_email"]].add((row["chain_name"], row["platform"]))
            op_counts[row["operator_email"]] += 1
    for op in operators:
        op_combos.setdefault(op, set())
        op_counts.setdefault(op, 0)

    groups: dict[tuple, list] = defaultdict(list)
    for _, row in orphaned_df.iterrows():
        groups[(row["chain_name"], row["platform"])].append(row)

    now = _now_str()
    updates: list[tuple[str, str]] = []
    for (chain, plat), reviews in groups.items():
        has_combo = [op for op in operators if (chain, plat) in op_combos[op]]
        no_combo = [op for op in operators if (chain, plat) not in op_combos[op]]
        has_combo.sort(key=lambda op: op_counts[op])
        no_combo.sort(key=lambda op: (len(op_combos[op]), op_counts[op]))
        preferred = has_combo + no_combo
        for i, row in enumerate(reviews):
            target = preferred[i % len(preferred)]
            updates.append((row["assignment_id"], target))
            op_counts[target] += 1
            op_combos[target].add((chain, plat))

    if updates:
        cases = " ".join(f"WHEN '{_safe(aid)}' THEN '{_safe(t)}'" for aid, t in updates)
        aid_list = ", ".join(f"'{_safe(aid)}'" for aid, _ in updates)
        bq_exec(f"""
        UPDATE `{TABLE_ASSIGNMENTS}`
        SET operator_email = CASE assignment_id {cases} END,
            assigned_at = TIMESTAMP('{now}')
        WHERE assignment_id IN ({aid_list})
        """)
    return len(orphaned_df)
