"""
Daily review assignment algorithm: Min-Login with 1.2x Soft Cap.

Runs at 8 AM IST via Cloud Scheduler.
Distributes pending reviews to operators optimizing for:
  1. Fewest portal logins (keep chain x platform groups bundled)
  2. Chain affinity (same operator handles both DD and UE for a chain)
  3. Soft load cap (no operator gets > 1.2x their fair share)
  4. Expiring reviews first
  5. Random operator order each run (no first-iterator bias)
  6. Managers and leads never get assignments
"""
from __future__ import annotations

import random
import uuid
from collections import defaultdict

from backend.repositories.assignment_repository import (
    expire_stale_assignments,
    fetch_already_assigned_uids,
    insert_assignments,
    void_pending_assignments,
)
from backend.repositories.ops_log_repository import log_action
from backend.repositories.review_repository import fetch_reviews_14d
from backend.repositories.user_repository import fetch_approved_operators

SOFT_CAP_MULTIPLIER = 1.20


def run_assignment(full_reassign: bool = True) -> dict:
    """Main entry point — invoked by cron and manual trigger."""
    expire_stale_assignments()
    if full_reassign:
        void_pending_assignments()

    reviews = fetch_reviews_14d()
    operators = fetch_approved_operators()

    if operators.empty:
        return {"error": "No approved operators found", "assigned": 0}
    if reviews.empty:
        return {"info": "No reviews to assign", "assigned": 0}

    pending = reviews[reviews["status"] == "PENDING"].copy()
    if pending.empty:
        return {"info": "No pending reviews", "assigned": 0}

    if not full_reassign:
        already = fetch_already_assigned_uids()
        pending = pending[~pending["review_uid"].isin(already)]
        if pending.empty:
            return {"info": "All pending reviews already assigned", "assigned": 0}

    pending = pending.sort_values("hours_left", ascending=True)
    ops = _build_operator_state(operators, len(pending))
    group_plan = _build_group_plan(pending, ops)
    assignments = _materialize_assignments(pending, ops, group_plan)

    if assignments:
        insert_assignments(assignments)

    summary = _build_summary(assignments, ops, group_plan)
    log_action(
        review_uid="batch", platform="all", chain_name="all",
        action="assign_batch", operator_email="system", performed_by="system",
        remarks=f"Assigned {len(assignments)} reviews to {len(ops)} operators ({len(group_plan)} groups, min-login algo)",
    )
    return summary


# ── Internal helpers ────────────────────────────────────────────────────────

def _build_operator_state(operators, total_reviews: int) -> list[dict]:
    """Build per-operator state with soft caps. Shuffled so first one doesn't always win ties."""
    from backend.enums.role import Role

    ops = []
    for _, op in operators.iterrows():
        reduction = float(op.get("reduction_pct", 0)) if op["role"] == Role.NEW_OPERATOR else 0.0
        weight = max(1.0 - reduction / 100.0, 0.1)
        ops.append({
            "email": op["email"],
            "role": op["role"],
            "weight": weight,
            "assigned_count": 0,
            "groups": [],
            "chains": set(),
        })

    random.shuffle(ops)

    total_weight = sum(o["weight"] for o in ops)
    for op in ops:
        op["soft_cap"] = round(total_reviews * op["weight"] / total_weight * SOFT_CAP_MULTIPLIER)
    return ops


def _build_group_plan(pending, ops: list[dict]) -> dict:
    """Decide which operator gets each chain x platform group."""
    groups = {
        (chain, plat): grp.sort_values("hours_left").to_dict("records")
        for (chain, plat), grp in pending.groupby(["chain_name", "platform"])
    }
    chain_bundles = defaultdict(list)
    for (chain, plat) in groups:
        chain_bundles[chain].append((chain, plat))
    sorted_bundles = sorted(
        chain_bundles.items(),
        key=lambda x: sum(len(groups[g]) for g in x[1]),
        reverse=True,
    )

    group_plan: dict = defaultdict(list)
    for chain, chain_groups in sorted_bundles:
        bundle_size = sum(len(groups[g]) for g in chain_groups)
        best_idx = _best_op_for_chain(ops, chain, bundle_size)

        if best_idx is not None:
            for g in chain_groups:
                group_plan[g].append((best_idx, len(groups[g])))
                ops[best_idx]["groups"].append(g)
            ops[best_idx]["assigned_count"] += bundle_size
            ops[best_idx]["chains"].add(chain)
        else:
            # Bundle too big — split across operators
            for g in sorted(chain_groups, key=lambda g: len(groups[g]), reverse=True):
                g_size = len(groups[g])
                best_idx = _best_op_for_group(ops, g, g_size)
                if best_idx is not None:
                    group_plan[g].append((best_idx, g_size))
                    ops[best_idx]["assigned_count"] += g_size
                    ops[best_idx]["groups"].append(g)
                    ops[best_idx]["chains"].add(g[0])
                else:
                    # Must split this single group across multiple operators
                    remaining = g_size
                    while remaining > 0:
                        best_idx = _op_with_most_capacity(ops)
                        capacity = max(ops[best_idx]["soft_cap"] - ops[best_idx]["assigned_count"], 1)
                        take = min(remaining, capacity)
                        group_plan[g].append((best_idx, take))
                        ops[best_idx]["assigned_count"] += take
                        ops[best_idx]["groups"].append(g)
                        ops[best_idx]["chains"].add(g[0])
                        remaining -= take

    # Attach groups dict to the result via closure (returned together)
    _build_group_plan._groups = groups  # type: ignore[attr-defined]
    return group_plan


def _materialize_assignments(pending, ops, group_plan) -> list[dict]:
    """Turn the plan into insertable assignment rows."""
    groups = _build_group_plan._groups  # type: ignore[attr-defined]
    rows = []
    for (chain, plat), plan in group_plan.items():
        review_rows = groups[(chain, plat)]
        offset = 0
        for (op_idx, count) in plan:
            for rev in review_rows[offset:offset + count]:
                rows.append({
                    "assignment_id": str(uuid.uuid4()),
                    "review_uid": rev["review_uid"],
                    "order_id": rev.get("order_id", ""),
                    "operator_email": ops[op_idx]["email"],
                    "chain_name": chain,
                    "platform": plat,
                    # Snapshot floor(hours/24) into the legacy days_left column on
                    # the assignments table. The column is metadata-only — live
                    # status/priority is recomputed from hours_left on each read.
                    "days_left": max(int(rev["hours_left"] // 24), 0),
                })
            offset += count
    return rows


def _build_summary(assignments, ops, group_plan) -> dict:
    return {
        "assigned": len(assignments),
        "operators": len(ops),
        "groups": len(group_plan),
        "per_operator": {
            op["email"]: {
                "count": op["assigned_count"],
                "chain_platforms": len(set(op["groups"])),
                "chains": len(op["chains"]),
            }
            for op in ops
        },
    }


def _best_op_for_chain(ops, chain, bundle_size: int) -> int | None:
    """Find operator who can fit the entire chain bundle. Prefer already-handling, fewer logins, more capacity."""
    best_idx = None
    best_score = None
    for i, op in enumerate(ops):
        remaining = op["soft_cap"] - op["assigned_count"]
        if remaining < bundle_size:
            continue
        score = (chain in op["chains"], -len(set(op["groups"])), remaining)
        if best_score is None or score > best_score:
            best_idx = i
            best_score = score
    return best_idx


def _best_op_for_group(ops, group, group_size: int) -> int | None:
    """Same as _best_op_for_chain but for a single chain x platform group."""
    chain = group[0]
    best_idx = None
    best_score = None
    for i, op in enumerate(ops):
        remaining = op["soft_cap"] - op["assigned_count"]
        if remaining < group_size:
            continue
        score = (group in op["groups"], chain in op["chains"], -len(set(op["groups"])), remaining)
        if best_score is None or score > best_score:
            best_idx = i
            best_score = score
    return best_idx


def _op_with_most_capacity(ops) -> int:
    return max(range(len(ops)), key=lambda i: ops[i]["soft_cap"] - ops[i]["assigned_count"])
