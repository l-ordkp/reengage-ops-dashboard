"""User access roles."""
from enum import Enum


class Role(str, Enum):
    MANAGER = "manager"           # Full access: Lead + Ops Log + Manage Users
    LEAD = "lead"                 # All Reviews, Chain Health, Configs, Search, Operators
    TENURED_OPERATOR = "tenured_operator"  # Weight 1.0 in assignment
    NEW_OPERATOR = "new_operator"          # Reduced weight (reduction_pct)


# Roles that have lead-level access (managers also have this)
LEAD_ROLES = {Role.LEAD, Role.MANAGER}

# Roles that receive review assignments (operators only)
ASSIGNABLE_ROLES = {Role.TENURED_OPERATOR, Role.NEW_OPERATOR}
