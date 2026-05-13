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


def remove_user(email: str) -> None:
    """Redistribute pending assignments to other operators, then delete the user."""
    from backend.repositories.assignment_repository import (
        redistribute_assignments_for_removed_operator,
    )
    redistribute_assignments_for_removed_operator(email)
    repo_delete_user(email)


def backfill_name(email: str, name: str) -> None:
    update_name_if_empty(email, name)


def total_user_count() -> int:
    return fetch_user_count()


def is_lead(role: str) -> bool:
    return role in (Role.LEAD, Role.MANAGER)
