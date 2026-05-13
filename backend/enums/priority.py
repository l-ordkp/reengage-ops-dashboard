"""Review priority based on days remaining in response window."""
from enum import Enum


class Priority(str, Enum):
    CRITICAL = "CRITICAL"  # days_left <= 1
    URGENT = "URGENT"      # days_left == 2
    NORMAL = "NORMAL"      # days_left > 2
