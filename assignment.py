"""
Review assignment engine — Min-Login with Soft Load Cap.

Runs daily at 8 AM (via Cloud Scheduler or manual trigger).
Distributes pending reviews to operators, optimising for:
  1. Minimum logins: keep whole chain×platform groups together (never split if possible)
  2. Chain affinity: pair same-chain DD+UE to same operator
  3. Soft load cap at 125% of weighted average (only split if exceeding cap)
  4. Expiring reviews first (lowest days_left)
  5. Leads are never assigned reviews
"""

from __future__ import annotations

import uuid
from collections import defaultdict

import pandas as pd

from config import ROLE_LEAD, ROLE_NEW, TABLE_USERS, TABLE_ASSIGNMENTS
from db import bq_read
from data_loaders import load_reviews
from write_helpers import insert_assignments, expire_stale_assignments, log_action

SOFT_CAP_MULTIPLIER = 1.25  # 125% of weighted average


def _load_operators() -> pd.DataFrame:
    return bq_read(f"""
        SELECT email, name, role, reduction_pct
        FROM `{TABLE_USERS}`
        WHERE approved = TRUE AND role != '{ROLE_LEAD}'
        ORDER BY email
    """)


def _load_already_assigned_uids() -> set:
    df = bq_read(f"""
        SELECT DISTINCT review_uid
        FROM `{TABLE_ASSIGNMENTS}`
        WHERE status IN ('pending', 'completed')
          AND assigned_at >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY))
    """)
    return set(df["review_uid"].tolist()) if not df.empty else set()


def run_assignment() -> dict:
    expire_stale_assignments()

    reviews = load_reviews()
    operators = _load_operators()

    if operators.empty:
        return {"error": "No approved operators found", "assigned": 0}
    if reviews.empty:
        return {"info": "No reviews to assign", "assigned": 0}

    pending = reviews[reviews["status"] == "PENDING"].copy()
    if pending.empty:
        return {"info": "No pending reviews", "assigned": 0}

    already_assigned = _load_already_assigned_uids()
    pending = pending[~pending["review_uid"].isin(already_assigned)]
    if pending.empty:
        return {"info": "All pending reviews already assigned", "assigned": 0}

    pending = pending.sort_values("days_left", ascending=True)

    # Build operator list with weights
    ops = []
    for _, op in operators.iterrows():
        reduction = float(op.get("reduction_pct", 0)) if op["role"] == ROLE_NEW else 0.0
        weight = max(1.0 - reduction / 100.0, 0.1)
        ops.append({
            "email": op["email"],
            "role": op["role"],
            "weight": weight,
            "assigned_count": 0,
            "groups": [],       # list of (chain, platform) tuples
            "chains": set(),    # unique chains handled
        })

    total_weight = sum(o["weight"] for o in ops)
    total_reviews = len(pending)

    # Soft cap per operator (125% of their weighted share)
    for op in ops:
        op["soft_cap"] = round(total_reviews * op["weight"] / total_weight * SOFT_CAP_MULTIPLIER)

    # Group reviews by chain×platform
    groups = {}
    for (chain, plat), grp in pending.groupby(["chain_name", "platform"]):
        groups[(chain, plat)] = grp.sort_values("days_left").to_dict("records")

    # Build chain bundles: group same-chain DD+UE together
    chain_bundles = defaultdict(list)
    for (chain, plat) in groups:
        chain_bundles[chain].append((chain, plat))

    # Sort bundles by total size (largest first)
    sorted_bundles = sorted(
        chain_bundles.items(),
        key=lambda x: sum(len(groups[g]) for g in x[1]),
        reverse=True,
    )

    # Phase 1: Assign whole chain bundles to operators
    group_plan = defaultdict(list)

    for chain, chain_groups in sorted_bundles:
        bundle_size = sum(len(groups[g]) for g in chain_groups)
        best_idx = _best_operator_for_chain(ops, chain, bundle_size)

        if best_idx is not None:
            # Whole bundle fits under soft cap
            for g in chain_groups:
                group_plan[g].append((best_idx, len(groups[g])))
                ops[best_idx]["groups"].append(g)
            ops[best_idx]["assigned_count"] += bundle_size
            ops[best_idx]["chains"].add(chain)
        else:
            # Bundle too large — try assigning individual groups within the chain
            for g in sorted(chain_groups, key=lambda g: len(groups[g]), reverse=True):
                g_size = len(groups[g])
                best_idx = _best_operator_for_group_minlogin(ops, g, g_size)

                if best_idx is not None:
                    group_plan[g].append((best_idx, g_size))
                    ops[best_idx]["assigned_count"] += g_size
                    ops[best_idx]["groups"].append(g)
                    ops[best_idx]["chains"].add(g[0])
                else:
                    # Must split — assign to operators with most remaining capacity
                    remaining = g_size
                    while remaining > 0:
                        best_idx = _operator_with_most_capacity(ops)
                        capacity = ops[best_idx]["soft_cap"] - ops[best_idx]["assigned_count"]
                        capacity = max(capacity, 1)  # always take at least 1
                        take = min(remaining, capacity)
                        group_plan[g].append((best_idx, take))
                        ops[best_idx]["assigned_count"] += take
                        ops[best_idx]["groups"].append(g)
                        ops[best_idx]["chains"].add(g[0])
                        remaining -= take

    # Build assignment rows
    assignments = []
    for (chain, plat), plan in group_plan.items():
        review_rows = groups[(chain, plat)]
        offset = 0
        for (op_idx, count) in plan:
            for rev in review_rows[offset:offset + count]:
                assignments.append({
                    "assignment_id": str(uuid.uuid4()),
                    "review_uid": rev["review_uid"],
                    "order_id": rev.get("order_id", ""),
                    "operator_email": ops[op_idx]["email"],
                    "chain_name": chain,
                    "platform": plat,
                    "days_left": rev["days_left"],
                })
            offset += count

    if assignments:
        insert_assignments(assignments)

    summary = {
        "assigned": len(assignments),
        "operators": len(ops),
        "groups": len(groups),
        "per_operator": {
            op["email"]: {
                "count": op["assigned_count"],
                "chain_platforms": len(set(op["groups"])),
                "chains": len(op["chains"]),
            }
            for op in ops
        },
    }

    log_action(
        review_uid="batch", platform="all", chain_name="all",
        action="assign_batch", operator_email="system", performed_by="system",
        remarks=f"Assigned {len(assignments)} reviews to {len(ops)} operators "
                f"({len(groups)} groups, min-login algo)",
    )

    return summary


def _best_operator_for_chain(ops, chain, bundle_size):
    """Find operator who can take the whole chain bundle under soft cap.
    Prefer: already handles this chain > fewest logins > most remaining capacity."""
    best_idx = None
    best_score = None

    for i, op in enumerate(ops):
        remaining = op["soft_cap"] - op["assigned_count"]
        if remaining < bundle_size:
            continue
        already_has_chain = chain in op["chains"]
        n_logins = len(set(op["groups"]))
        # Score: (already has chain → prefer, fewer logins → prefer, more capacity → prefer)
        score = (already_has_chain, -n_logins, remaining)
        if best_score is None or score > best_score:
            best_idx = i
            best_score = score

    return best_idx


def _best_operator_for_group_minlogin(ops, group, group_size):
    """Find operator who can take a single group under soft cap.
    Prefer: already handles this chain > fewest logins > most capacity."""
    chain = group[0]
    best_idx = None
    best_score = None

    for i, op in enumerate(ops):
        remaining = op["soft_cap"] - op["assigned_count"]
        if remaining < group_size:
            continue
        already_has_chain = chain in op["chains"]
        already_has_group = group in op["groups"]
        n_logins = len(set(op["groups"]))
        score = (already_has_group, already_has_chain, -n_logins, remaining)
        if best_score is None or score > best_score:
            best_idx = i
            best_score = score

    return best_idx


def _operator_with_most_capacity(ops):
    """Fallback: operator with most remaining capacity under soft cap."""
    return max(range(len(ops)),
               key=lambda i: ops[i]["soft_cap"] - ops[i]["assigned_count"])


if __name__ == "__main__":
    import json
    result = run_assignment()
    print(json.dumps(result, indent=2, default=str))
