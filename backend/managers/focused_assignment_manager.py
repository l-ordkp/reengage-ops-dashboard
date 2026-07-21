"""
TEMPORARY focused assignment: assign only what must be worked today.

Assigns every CRITICAL + URGENT review (two-cap balanced, whole-chain bundles
— same machinery as assignment_manager) plus a small near-urgent buffer per
operator (~150 normals at 48-72h to deadline, drawn from chains the operator
already owns so it costs no extra portal logins). Far-out normals are NOT
assigned at all — they stay visible in All Reviews and age into the pool on
later runs. Goal: an operator's queue contains only reviews that matter today,
so daily capacity is never spent on far-future work while urgent reviews
expire.

This intentionally lives in its own file and changes nothing in
assignment_manager.py: it is an experiment toggled by FOCUSED_ASSIGNMENT_MODE
(env, default on). Rollback = set FOCUSED_ASSIGNMENT_MODE=false, redeploy.
All shared mechanics (operator caps, chain bundling, forced splits with
urgency-interleaved dealing, PG dual-write choreography) are imported from
the existing modules, not reimplemented.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict

from backend.managers.assignment_manager import (
    HOT_PRIORITIES,
    _build_group_plan,
    _build_operator_state,
    _materialize_assignments,
)
from backend.repositories.pg_reengage_repository import (
    expire_pending,
    fetch_already_assigned_uids,
    fetch_first_seen_uids,
    insert_pending,
    log_action,
    record_first_seen,
    void_pending,
)
from backend.repositories.review_repository import fetch_reviews_14d
from backend.repositories.user_repository import fetch_approved_operators

# Near-urgent buffer: normals within this many hours of their deadline are
# eligible; each operator gets ~NEAR_BUFFER_PER_OPERATOR of them (weight-scaled
# for new operators) on top of their hot share.
NEAR_URGENT_MAX_HOURS = 72
NEAR_BUFFER_PER_OPERATOR = int(os.getenv("NEAR_BUFFER_PER_OPERATOR", "150"))


def _record_first_seen(reviews) -> int:
    """First-seen ledger gate: record every scoped review the system has never
    seen before as an action='first_seen' ops_log row. This is the 'ingested'
    metric's source of truth — the day a review first passes scoping — and is
    deliberately independent of assignment decisions (far normals are counted
    on arrival even though they are not assigned).

    Counts ALL scoped reviews regardless of status: a review that arrives
    already replied or expired still 'came into the system'.

    FAIL-OPEN: a ledger failure must never block assignment. Errors are logged
    and swallowed; unrecorded reviews are still in tomorrow's pool, so they get
    counted a day late rather than lost. Idempotent per run (dedup lookup), so
    the leads' manual re-runs write ~0 extra rows."""
    try:
        candidates = reviews[["review_uid", "platform", "chain_name"]].drop_duplicates(
            "review_uid")
        candidate_uids = candidates["review_uid"].tolist()
        seen_uids = fetch_first_seen_uids(candidate_uids)
        new_rows = candidates[~candidates["review_uid"].isin(seen_uids)]
        record_first_seen(new_rows.to_dict("records"))
        return len(new_rows)
    except Exception:
        logging.getLogger(__name__).exception(
            "first_seen ledger gate failed; continuing with assignment")
        return -1


def run_focused_assignment(full_reassign: bool = True) -> dict:
    """Entry point — same contract and write choreography as run_assignment."""
    expire_pending()
    # NOTE: unlike run_assignment, voiding of current pending assignments is
    # DEFERRED until the new plan has passed its invariant check (see below).
    # This function can abort on a bad plan; voiding first would leave every
    # operator with an empty queue on abort. Planning does not depend on the
    # void: fetch_reviews_14d's status CASE keeps a review PENDING while its
    # assignment row is pending, so the pool is identical either way.

    reviews = fetch_reviews_14d()
    operators = fetch_approved_operators()

    if operators.empty:
        return {"error": "No approved operators found", "assigned": 0}
    if reviews.empty:
        return {"info": "No reviews to assign", "assigned": 0}

    first_seen_recorded = _record_first_seen(reviews)

    pending = reviews[reviews["status"] == "PENDING"].copy()
    if pending.empty:
        return {"info": "No pending reviews", "assigned": 0}

    if not full_reassign:
        already_assigned_uids = fetch_already_assigned_uids()
        pending = pending[~pending["review_uid"].isin(already_assigned_uids)]
        if pending.empty:
            return {"info": "All pending reviews already assigned", "assigned": 0}

    pending = pending.sort_values("hours_left", ascending=True)
    hot_reviews = pending[pending["priority"].isin(HOT_PRIORITIES)]
    near_urgent_reviews = pending[
        (pending["hours_left"] > 48)
        & (pending["hours_left"] <= NEAR_URGENT_MAX_HOURS)
    ]

    if hot_reviews.empty and near_urgent_reviews.empty:
        return {"info": "No hot or near-urgent reviews to assign", "assigned": 0}

    # Pool caps computed over the hot pool only: total cap == hot cap since
    # the pool is all-hot; the buffer is bookkept separately below.
    ops = _build_operator_state(operators, len(hot_reviews), len(hot_reviews))
    if hot_reviews.empty:
        hot_group_plan, hot_groups = defaultdict(list), {}
    else:
        hot_group_plan, hot_groups = _build_group_plan(hot_reviews, ops)
    assignments = _materialize_assignments(ops, hot_group_plan, hot_groups)

    buffer_plan, buffer_groups = _build_buffer_plan(ops, near_urgent_reviews)
    buffer_assignments = _materialize_assignments(ops, buffer_plan, buffer_groups)
    assignments += buffer_assignments

    # Invariant: every hot review must be in the insert set. This is the
    # guarantee that makes "focused" safe — nothing urgent is ever left
    # unassigned. Refuse to write a plan that violates it.
    hot_uids = set(hot_reviews["review_uid"])
    planned_uids = {assignment["review_uid"] for assignment in assignments}
    missing_hot_uids = hot_uids - planned_uids
    if missing_hot_uids:
        return {
            "error": f"invariant violated: {len(missing_hot_uids)} hot reviews unassigned",
            "assigned": 0,
        }

    # Plan verified — now it is safe to void the old queues and write the new
    # ones. PG-first ordering preserved for both operations.
    if full_reassign:
        void_pending()

    if assignments:
        insert_pending(assignments)

    unassigned_normals = len(pending) - len(assignments)
    summary = {
        "assigned": len(assignments),
        "hot_assigned": len(hot_reviews),
        "buffer_assigned": len(buffer_assignments),
        "unassigned_normals": unassigned_normals,
        # new scoped reviews recorded in the first_seen ledger this run
        # (-1 = ledger gate failed, see logs; assignment proceeded regardless)
        "first_seen_recorded": first_seen_recorded,
        "operators": len(ops),
        "groups": len(hot_group_plan) + len(buffer_plan),
        "per_operator": {
            op["email"]: {
                "count": op["assigned_count"],
                "hot": op["hot_count"],
                "buffer": op.get("buffer_count", 0),
                "chain_platforms": len(set(op["groups"])),
                "chains": len(op["chains"]),
            }
            for op in ops
        },
    }
    log_action(
        review_uid="batch", platform="all", chain_name="all",
        action="assign_batch", operator_email="system", performed_by="system",
        remarks=(
            f"Assigned {len(assignments)} reviews to {len(ops)} operators "
            f"({len(hot_reviews)} hot + {len(buffer_assignments)} near-urgent buffer, "
            f"{unassigned_normals} normals left unassigned, focused algo)"
        ),
    )
    return summary


def _build_buffer_plan(ops: list[dict], near_urgent_reviews) -> tuple[dict, dict]:
    """Assign each operator ~NEAR_BUFFER_PER_OPERATOR near-urgent normals.

    Login-first selection order per operator:
      1. groups (chain x platform) the operator already holds hot work in —
         same portal session, zero extra logins;
      2. other platforms of chains they already own — same chain, one login;
      3. unowned groups, largest remaining first, so a shortfall is covered
         with the fewest new logins.
    Rows within a group go nearest-deadline first (each group's row list is
    sorted by hours_left, and _materialize_assignments deals in that order).
    """
    if near_urgent_reviews.empty:
        return defaultdict(list), {}

    near_groups = {
        (chain, plat): grp.sort_values("hours_left").to_dict("records")
        for (chain, plat), grp in near_urgent_reviews.groupby(["chain_name", "platform"])
    }
    stock_remaining = {
        group_key: len(rows) for group_key, rows in near_groups.items()
    }
    buffer_plan: dict = defaultdict(list)
    buffer_room = [
        max(round(NEAR_BUFFER_PER_OPERATOR * op["weight"]), 0) for op in ops
    ]
    # Frozen ownership snapshots: the take-loop mutates op["groups"]/["chains"]
    # (PR #31 review — a lazy filter over the live sets skipped the sibling
    # platform of a just-acquired chain).
    owned_groups_per_op = [set(op["groups"]) for op in ops]
    owned_chains_per_op = [set(op["chains"]) for op in ops]
    for op in ops:
        op["buffer_count"] = 0

    def assign_buffer_rows(op_idx: int, group_key) -> None:
        take_count = min(buffer_room[op_idx], stock_remaining[group_key])
        if take_count <= 0:
            return
        buffer_plan[group_key].append((op_idx, take_count))
        stock_remaining[group_key] -= take_count
        buffer_room[op_idx] -= take_count
        operator = ops[op_idx]
        operator["assigned_count"] += take_count
        operator["buffer_count"] += take_count
        operator["groups"].append(group_key)
        operator["chains"].add(group_key[0])

    # PASS 1 — owned stock only, for EVERY operator, before anyone may touch
    # unowned groups. A single greedy pass lets early-shuffled operators raid
    # the near-urgent stock of chains that later operators own (unowned
    # selection is largest-first, which is exactly where someone else's chain
    # sits), destroying the zero-extra-login property for the later ones.
    for op_idx in range(len(ops)):
        for group_key in near_groups:
            if group_key in owned_groups_per_op[op_idx]:
                assign_buffer_rows(op_idx, group_key)
        for group_key in near_groups:
            chain_name = group_key[0]
            if (chain_name in owned_chains_per_op[op_idx]
                    and group_key not in owned_groups_per_op[op_idx]):
                assign_buffer_rows(op_idx, group_key)

    # PASS 2 — fill any leftover room from unowned stock, chain-grouped
    # (both platforms of a chain offered consecutively, biggest chain first)
    # so a shortfall costs the fewest new logins.
    for op_idx in range(len(ops)):
        if buffer_room[op_idx] <= 0:
            continue
        unowned_groups_by_chain = defaultdict(list)
        for group_key in near_groups:
            if (group_key[0] not in owned_chains_per_op[op_idx]
                    and stock_remaining[group_key] > 0):
                unowned_groups_by_chain[group_key[0]].append(group_key)
        chains_by_stock = sorted(
            unowned_groups_by_chain,
            key=lambda chain_name: -sum(
                stock_remaining[group_key]
                for group_key in unowned_groups_by_chain[chain_name]
            ),
        )
        for chain_name in chains_by_stock:
            for group_key in unowned_groups_by_chain[chain_name]:
                assign_buffer_rows(op_idx, group_key)
            if buffer_room[op_idx] <= 0:
                break

    # Trim each group's row list to just the dealt prefix so
    # _materialize_assignments (which deals plan counts over the group's row
    # list) sees consistent data.
    dealt_near_groups = {
        group_key: near_groups[group_key][
            : sum(count for _, count in buffer_plan[group_key])
        ]
        for group_key in buffer_plan
    }
    return buffer_plan, dealt_near_groups
