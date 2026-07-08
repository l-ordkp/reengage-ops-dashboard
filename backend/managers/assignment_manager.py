"""
Daily review assignment algorithm: Min-Login with 1.2x Soft Caps (total + hot).

Runs at 8 AM IST via Cloud Scheduler.
Distributes pending reviews to operators optimizing for:
  1. Fewest portal logins (keep chain x platform groups bundled)
  2. Chain affinity (same operator handles both DD and UE for a chain)
  3. Soft load cap (no operator gets > 1.2x their fair share of total reviews)
  4. Soft urgency cap (no operator gets > 1.2x their fair share of hot
     reviews, hot = critical + urgent, hours_left <= 48). Urgency-heavy
     bundles are placed first, while every operator still has hot headroom;
     a group is split across operators only when its hot count cannot fit
     under any single operator's hot cap — the minimum number of extra
     logins the fairness constraint forces.
  5. Expiring reviews first, dealt in urgency-interleaved order on splits
     so every recipient gets the same mix of deadlines
  6. Random operator order each run (no first-iterator bias)
  7. Managers and leads never get assignments
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
# hot = critical/urgent priority as computed by fetch_reviews_14d (<= 48h to
# platform deadline) — read from the priority column, not re-derived here, so
# the definition can't drift from review_repository's CASE.
HOT_PRIORITIES = frozenset({"CRITICAL", "URGENT"})
# On quiet days a proportional hot cap rounds down to ~0 and would force
# pointless group splits over a handful of hot reviews; below this many the
# imbalance is meaningless, so every operator can hold at least this many.
# Deliberately NOT weight-scaled: it is a de-minimis threshold, and a reduced
# operator's smaller soft_cap still loses capacity tie-breaks on quiet days.
HOT_CAP_FLOOR = 5


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
    total_hot = int(pending["priority"].isin(HOT_PRIORITIES).sum())
    ops = _build_operator_state(operators, len(pending), total_hot)
    group_plan, groups = _build_group_plan(pending, ops)
    assignments = _materialize_assignments(ops, group_plan, groups)

    if assignments:
        insert_assignments(assignments)

    summary = _build_summary(assignments, ops, group_plan)
    log_action(
        review_uid="batch", platform="all", chain_name="all",
        action="assign_batch", operator_email="system", performed_by="system",
        remarks=f"Assigned {len(assignments)} reviews to {len(ops)} operators ({len(group_plan)} groups, min-login two-cap algo)",
    )
    return summary


# ── Internal helpers ────────────────────────────────────────────────────────

def _build_operator_state(operators, total_reviews: int, total_hot: int) -> list[dict]:
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
            "hot_count": 0,
            "groups": [],
            "chains": set(),
        })

    random.shuffle(ops)

    total_weight = sum(o["weight"] for o in ops)
    for op in ops:
        share = op["weight"] / total_weight * SOFT_CAP_MULTIPLIER
        op["soft_cap"] = round(total_reviews * share)
        op["hot_cap"] = max(round(total_hot * share), HOT_CAP_FLOOR)
    return ops


def _build_group_plan(pending, ops: list[dict]) -> tuple[dict, dict]:
    """Decide which operator gets each chain x platform group."""
    groups = {
        (chain, plat): grp.sort_values("hours_left").to_dict("records")
        for (chain, plat), grp in pending.groupby(["chain_name", "platform"])
    }
    group_hot = {
        g: sum(1 for r in rows if r["priority"] in HOT_PRIORITIES)
        for g, rows in groups.items()
    }
    chain_bundles = defaultdict(list)
    for (chain, plat) in groups:
        chain_bundles[chain].append((chain, plat))
    # Hot-heaviest bundles first: hot capacity is the scarce resource (each
    # operator's hot cap is a fraction of their total cap), so it must be
    # allocated while everyone still has hot headroom. Cold bundles are the
    # filler that evens out totals afterwards.
    sorted_bundles = sorted(
        chain_bundles.items(),
        key=lambda x: (
            sum(group_hot[g] for g in x[1]),
            sum(len(groups[g]) for g in x[1]),
        ),
        reverse=True,
    )

    group_plan: dict = defaultdict(list)
    for chain, chain_groups in sorted_bundles:
        bundle_size = sum(len(groups[g]) for g in chain_groups)
        bundle_hot = sum(group_hot[g] for g in chain_groups)
        best_idx = _best_op_for_chain(ops, chain, bundle_size, bundle_hot)

        if best_idx is not None:
            for g in chain_groups:
                group_plan[g].append((best_idx, len(groups[g])))
                ops[best_idx]["groups"].append(g)
            ops[best_idx]["assigned_count"] += bundle_size
            ops[best_idx]["hot_count"] += bundle_hot
            ops[best_idx]["chains"].add(chain)
        else:
            # Bundle too big — split across operators
            for g in sorted(chain_groups,
                            key=lambda g: (group_hot[g], len(groups[g])),
                            reverse=True):
                g_size, g_hot = len(groups[g]), group_hot[g]
                best_idx = _best_op_for_group(ops, g, g_size, g_hot)
                if best_idx is not None:
                    group_plan[g].append((best_idx, g_size))
                    ops[best_idx]["assigned_count"] += g_size
                    ops[best_idx]["hot_count"] += g_hot
                    ops[best_idx]["groups"].append(g)
                    ops[best_idx]["chains"].add(g[0])
                else:
                    _split_group_across_ops(ops, g, g_size, g_hot, group_plan)

    return group_plan, groups


def _split_group_across_ops(ops, g, g_size: int, g_hot: int, group_plan) -> None:
    """No single operator can hold this group under both caps — shard it.

    Each shard is sized by the recipient's feasible take: how many of the
    group's reviews fit under BOTH their remaining total and hot budgets
    (hot budget converts to review count via the group's hot ratio, since
    slices are dealt urgency-interleaved and carry a proportional hot
    share). Recruiting largest-feasible-take first keeps the shard count —
    i.e. the extra portal logins — at the minimum the caps force.
    """
    remaining, hot_remaining = g_size, g_hot
    while remaining > 0:
        hot_ratio = hot_remaining / remaining

        def feasible(op):
            room_total = op["soft_cap"] - op["assigned_count"]
            room_hot = op["hot_cap"] - op["hot_count"]
            if hot_ratio > 0:
                return max(0, min(room_total, int(room_hot / hot_ratio)))
            return max(0, room_total)

        best_idx = max(range(len(ops)), key=lambda i: feasible(ops[i]))
        take = feasible(ops[best_idx])
        if take == 0:
            # Nobody fits both caps: fall back to total headroom so the
            # overflow spreads across operators (hot stays proportional via
            # interleaved dealing) instead of piling onto one.
            best_idx = max(
                range(len(ops)),
                key=lambda i: ops[i]["soft_cap"] - ops[i]["assigned_count"],
            )
            take = max(ops[best_idx]["soft_cap"] - ops[best_idx]["assigned_count"], 1)
        take = min(remaining, take)
        # Half-up rounding, not round() — banker's rounding on .5 fractions
        # would under-count a shard's hot share, leaving hot rows to leak into
        # the fallback path and breach a cap a correct count would respect.
        # Cap-safe: feasible() guarantees take * hot_ratio <= room_hot.
        # (feasible() truncates, deliberately: under-promise capacity when
        # sizing a shard, over-count consumption when booking it.)
        hot_take = min(int(take * hot_ratio + 0.5), hot_remaining)
        if take == remaining:
            hot_take = hot_remaining

        group_plan[g].append((best_idx, take))
        ops[best_idx]["assigned_count"] += take
        ops[best_idx]["hot_count"] += hot_take
        ops[best_idx]["groups"].append(g)
        ops[best_idx]["chains"].add(g[0])
        remaining -= take
        hot_remaining -= hot_take


def _materialize_assignments(ops, group_plan, groups) -> list[dict]:
    """Turn the plan into insertable assignment rows.

    A group's rows are sorted by hours_left ascending; when a group is split,
    deal rows to recipients proportionally (largest-deficit-first) instead of
    contiguous slices, so no recipient gets all the soonest-expiring reviews.
    """
    rows = []
    for (chain, plat), plan in group_plan.items():
        review_rows = groups[(chain, plat)]
        planned_total = sum(count for _, count in plan)
        given = [0] * len(plan)
        for dealt, rev in enumerate(review_rows, start=1):
            slot = max(
                (j for j in range(len(plan)) if given[j] < plan[j][1]),
                key=lambda j: plan[j][1] / planned_total * dealt - given[j],
            )
            given[slot] += 1
            rows.append({
                "assignment_id": str(uuid.uuid4()),
                "review_uid": rev["review_uid"],
                "order_id": rev.get("order_id", ""),
                "operator_email": ops[plan[slot][0]]["email"],
                "chain_name": chain,
                "platform": plat,
                # Snapshot floor(hours/24) into the legacy days_left column on
                # the assignments table. The column is metadata-only — live
                # status/priority is recomputed from hours_left on each read.
                "days_left": max(int(rev["hours_left"] // 24), 0),
            })
    return rows


def _build_summary(assignments, ops, group_plan) -> dict:
    return {
        "assigned": len(assignments),
        "operators": len(ops),
        "groups": len(group_plan),
        "per_operator": {
            op["email"]: {
                "count": op["assigned_count"],
                "hot": op["hot_count"],
                "chain_platforms": len(set(op["groups"])),
                "chains": len(op["chains"]),
            }
            for op in ops
        },
    }


def _best_op_for_chain(ops, chain, bundle_size: int, bundle_hot: int) -> int | None:
    """Find operator who fits the entire chain bundle under both caps.
    Prefer already-handling, fewer logins, more hot headroom, more capacity."""
    best_idx = None
    best_score = None
    for i, op in enumerate(ops):
        remaining = op["soft_cap"] - op["assigned_count"]
        remaining_hot = op["hot_cap"] - op["hot_count"]
        if remaining < bundle_size or remaining_hot < bundle_hot:
            continue
        score = (chain in op["chains"], -len(set(op["groups"])), remaining_hot, remaining)
        if best_score is None or score > best_score:
            best_idx = i
            best_score = score
    return best_idx


def _best_op_for_group(ops, group, group_size: int, group_hot: int) -> int | None:
    """Same as _best_op_for_chain but for a single chain x platform group."""
    chain = group[0]
    best_idx = None
    best_score = None
    for i, op in enumerate(ops):
        remaining = op["soft_cap"] - op["assigned_count"]
        remaining_hot = op["hot_cap"] - op["hot_count"]
        if remaining < group_size or remaining_hot < group_hot:
            continue
        score = (group in op["groups"], chain in op["chains"],
                 -len(set(op["groups"])), remaining_hot, remaining)
        if best_score is None or score > best_score:
            best_idx = i
            best_score = score
    return best_idx
