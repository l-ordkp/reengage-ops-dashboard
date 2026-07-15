"""User CRUD orchestration."""
from __future__ import annotations

from backend.enums.role import Role
from backend.repositories.user_repository import (
    delete_user as repo_delete_user,
    fetch_all_users,
    fetch_user,
    fetch_user_count,
    insert_or_update_user,
    update_approval,
    update_name_if_empty,
    update_role,
)
from backend.utils.serializers import df_to_dicts


def get_user(email: str) -> dict | None:
    return fetch_user(email)


def list_users() -> list[dict]:
    return df_to_dicts(fetch_all_users())


def add_user(email: str, name: str, role: str, reduction_pct: float, added_by: str) -> None:
    insert_or_update_user(email, name, role, reduction_pct, added_by)


def change_role(email: str, new_role: str, reduction_pct: float) -> None:
    reduction = reduction_pct if new_role == Role.NEW_OPERATOR else 0.0
    update_role(email, new_role, reduction)


def set_approval(email: str, approved: bool) -> None:
    update_approval(email, approved)


def remove_user(email: str, performed_by: str) -> None:
    """
    Redistribute pending assignments to other operators, delete the user,
    and write an audit row to ops_log so the redistribution is traceable.
    """
    from backend.repositories.pg_reengage_repository import (
        log_action,
        redistribute_pending_for_removed_operator,
    )
    from backend.repositories.user_repository import fetch_approved_operators

    operators_df = fetch_approved_operators()
    candidate_operators = (
        [e for e in operators_df["email"].tolist() if e != email]
        if not operators_df.empty else []
    )
    n_redistributed = redistribute_pending_for_removed_operator(
        email, candidate_operators,
    )
    repo_delete_user(email)
    log_action(
        review_uid="batch", platform="all", chain_name="all",
        action="user_removed",
        operator_email=email,
        performed_by=performed_by,
        remarks=f"Redistributed {n_redistributed} pending reviews after user removal",
    )


def backfill_name(email: str, name: str) -> None:
    update_name_if_empty(email, name)


def total_user_count() -> int:
    return fetch_user_count()


def is_lead(role: str) -> bool:
    return role in (Role.LEAD, Role.MANAGER)
