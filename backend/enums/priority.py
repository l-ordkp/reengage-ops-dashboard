"""Review priority based on hours remaining until platform deadline."""
from enum import Enum


class Priority(str, Enum):
    CRITICAL = "CRITICAL"  # hours_left <= 24
    URGENT = "URGENT"      # 24 < hours_left <= 48
    NORMAL = "NORMAL"      # hours_left > 48
