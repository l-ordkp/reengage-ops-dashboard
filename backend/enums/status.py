"""Status enums for reviews and assignments."""
from enum import Enum


class ReviewStatus(str, Enum):
    """Lifecycle status of a review."""
    PENDING = "PENDING"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"


class AssignmentStatus(str, Enum):
    """Lifecycle status of an assignment row in BigQuery."""
    PENDING = "pending"
    COMPLETED = "completed"
    EXPIRED = "expired"
    REASSIGNED = "reassigned"
