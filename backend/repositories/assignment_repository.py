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
    """UIDs of reviews the 8 AM cron should skip re-ingesting. Includes
    pending (currently being worked), completed (Loop submitted or matched
    portal account replied via UI), and auto_resolved (platform reports
    replied by someone outside Loop). Re-creating a pending row for any of
    these would either double-assign work, lose the external-replied signal,
    or both.
    """
    df = bq_read(f"""
        SELECT DISTINCT review_uid
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE status IN ('pending', 'completed', 'auto_resolved')
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
    """Mark pending assignment(s) for this order_id as completed (extension flow).

    Deliberately scoped to `status='pending'` only. Auto-resolved rows are
    promoted by `promote_auto_resolved_to_completed` instead — if we widened
    this WHERE to include `auto_resolved` and the same order_id had both a
    pending and an auto_resolved row (rare race between cron ingest and
    observation), a single UPDATE would flip BOTH to completed and double-
    count in throughput / Chain Value.
    """
    now = _now_str()
    safe_order_id = _escape_sql(order_id)
    bq_exec(f"""
        UPDATE `{TABLE_ASSIGNMENTS}`
        SET status = 'completed', completed_at = TIMESTAMP('{now}')
        WHERE order_id = '{safe_order_id}' AND status = 'pending'
    """)


def promote_auto_resolved_to_completed(order_id: str, operator_email: str) -> None:
    """Promote at most ONE auto_resolved row for this order_id to completed
    and stamp the actual submitter on `operator_email`. Covers the race
    where an external responder beat us to the platform UI and our extension
    wrote `auto_resolved`, but then a Loop operator submitted via our
    extension on top — the latest submit wins.

    Two guards against creating duplicate `completed` rows for one order:
      1. The UPDATE pins to a single assignment_id via a scalar subquery
         (ORDER BY assigned_at DESC LIMIT 1). If the assignments table holds
         multiple auto_resolved rows for the same order_id (TOCTOU race
         between concurrent observed_responded calls, or a re-ingestion that
         flipped a stale pending row into a second auto_resolved while a
         first one already existed), only the most recent is promoted —
         older auto_resolved orphans stay as `auto_resolved`, benign for
         every read (queue/Chain Value already filter or dedupe by order_id).
      2. NOT EXISTS short-circuits the whole UPDATE if any `completed` row
         already exists for the order_id, so we never sit a fresh promote
         next to a pre-existing completion.

    Pre-PR-B the operator queue still shows auto_resolved rows so this race
    can happen; post-PR-B the queue hides them and this UPDATE should
    essentially never match a row. Cheap to keep as a safety net.
    """
    if not operator_email:
        return
    now = _now_str()
    safe_order_id = _escape_sql(order_id)
    safe_email = _escape_sql(operator_email)
    # observed_out_of_window is reset to FALSE: the previous OOW classification
    # reflected the *observation* arriving past the platform deadline, but
    # a Loop operator has now just submitted via the extension — that's
    # fresh work that should count toward today's throughput. Without this
    # reset, the operator's credit would be silently filtered out by
    # operator_repository's `NOT IFNULL(observed_out_of_window, FALSE)`.
    bq_exec(f"""
        UPDATE `{TABLE_ASSIGNMENTS}` AS target
        SET status = 'completed',
            completed_at = TIMESTAMP('{now}'),
            operator_email = '{safe_email}',
            observed_out_of_window = FALSE
        WHERE target.assignment_id = (
            SELECT assignment_id
            FROM `{TABLE_ASSIGNMENTS}`
            WHERE order_id = '{safe_order_id}'
              AND status = 'auto_resolved'
            ORDER BY assigned_at DESC
            LIMIT 1
          )
          AND NOT EXISTS (
            SELECT 1 FROM `{TABLE_ASSIGNMENTS}` AS existing_completed
            WHERE existing_completed.order_id = '{safe_order_id}'
              AND existing_completed.status = 'completed'
          )
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


def bulk_insert_observed_assignments(items: list[dict]) -> None:
    """Insert one row per observed-responded item where no prior assignment
    existed. Each item must carry:
        review_uid, order_id, platform, chain_name (optional),
        status                  ('completed' for `missed_but_ours`,
                                 'auto_resolved' for `external`),
        operator_email          (matched Loop portal username, or '' for external),
        observed_out_of_window  (bool — True if review was past the platform
                                 response deadline or not in automation_reviews
                                 at observation time; filtered out of per-
                                 operator and daily-throughput counts).

    The `operator_email` column reflects who actually replied. The `''`
    sentinel means "no Loop operator did this work" (the column is NOT NULL
    in BQ). The observer is recorded in ops_log via `performed_by`.

    Idempotent: (a) dedups the batch by review (keeping 'completed' over
    'auto_resolved'), and (b) skips any review that ALREADY has a terminal
    (completed/auto_resolved) row via a NOT EXISTS guard — so a duplicate or
    late re-observation can't create a second terminal row. BigQuery has no
    constraints and inserts have visibility lag, so this is best-effort
    (reads still dedupe by review_uid as the ultimate guard), but it stops the
    common double-observation from duplicating rows.
    """
    if not items:
        return
    import uuid
    now = _now_str()
    # (a) dedupe within the batch by COALESCE(review_uid, order_id); completed wins.
    _rank = {"completed": 1, "auto_resolved": 0}
    by_key: dict[str, dict] = {}
    for item in items:
        key = item.get("review_uid") or item.get("order_id")
        cur = by_key.get(key)
        if cur is None or _rank.get(item.get("status"), 0) > _rank.get(cur.get("status"), 0):
            by_key[key] = item
    structs = []
    for item in by_key.values():
        status = item.get("status") or "auto_resolved"
        op_email = (item.get("operator_email") or "").strip()
        oow_sql = "TRUE" if item.get("observed_out_of_window") else "FALSE"
        structs.append(
            f"STRUCT('{uuid.uuid4()}' AS assignment_id, '{_escape_sql(item['review_uid'])}' AS review_uid, "
            f"'{_escape_sql(item['order_id'])}' AS order_id, '{_escape_sql(op_email)}' AS operator_email, "
            f"'{_escape_sql(item.get('chain_name', ''))}' AS chain_name, '{_escape_sql(item['platform'])}' AS platform, "
            f"'{_escape_sql(status)}' AS status, TIMESTAMP('{now}') AS ts, {oow_sql} AS oow)"
        )
    batch_size = 500
    for start in range(0, len(structs), batch_size):
        batch = structs[start:start + batch_size]
        # (b) INSERT ... SELECT with a NOT EXISTS guard against existing terminal rows.
        bq_exec(f"""
            INSERT INTO `{TABLE_ASSIGNMENTS}`
                (assignment_id, review_uid, order_id, operator_email,
                 chain_name, platform, days_left, status, assigned_at, completed_at,
                 platform_reply_id, platform_coupon_id, observed_out_of_window)
            SELECT s.assignment_id, s.review_uid, s.order_id, s.operator_email,
                   s.chain_name, s.platform, 0, s.status, s.ts, s.ts, NULL, NULL, s.oow
            FROM UNNEST([{', '.join(batch)}]) AS s
            -- Two single-equality NOT EXISTS (BigQuery can't anti-join an OR of
            -- equalities): skip if a terminal row already exists under either key.
            WHERE NOT EXISTS (
              SELECT 1 FROM `{TABLE_ASSIGNMENTS}` a
              WHERE a.review_uid = s.review_uid AND a.status IN ('completed', 'auto_resolved')
            )
            AND NOT EXISTS (
              SELECT 1 FROM `{TABLE_ASSIGNMENTS}` a2
              WHERE a2.order_id = s.order_id AND s.order_id != '' AND a2.status IN ('completed', 'auto_resolved')
            )
        """)


def bulk_flip_pending_to(
    review_uids: list[str], order_ids: list[str],
    new_status: str, new_operator_email: str,
    observed_out_of_window: bool = False,
) -> None:
    """Flip pending assignments matching the given review_uids/order_ids to
    `new_status`, reset `operator_email`, and stamp `observed_out_of_window`.

    `new_status` should be 'completed' (responder matched the slug's Loop
    portal account — `missed_but_ours`) or 'auto_resolved' (anyone else —
    `external`). `new_operator_email` is the matched Loop username for
    `missed_but_ours`; pass '' (empty string) for `external` so the original
    pending assignee is cleared (they didn't actually do the work). The
    operator_email column is NOT NULL in BQ — '' is the sentinel for "no
    Loop operator did this work".

    `observed_out_of_window` is True when the original review_timestamp is
    past the platform deadline (DD 7d, UE 14d) at observation time. Almost
    always False for the pending-flip path — the cron only creates pending
    rows for in-window reviews — but threaded through for completeness.
    """
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
    safe_email = _escape_sql(new_operator_email or "")
    safe_status = _escape_sql(new_status)
    oow_sql = "TRUE" if observed_out_of_window else "FALSE"
    bq_exec(f"""
        UPDATE `{TABLE_ASSIGNMENTS}`
        SET status = '{safe_status}',
            completed_at = TIMESTAMP('{now}'),
            operator_email = '{safe_email}',
            observed_out_of_window = {oow_sql}
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
