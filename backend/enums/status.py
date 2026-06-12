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
    # The platform reported the review as already replied AND the responder did
    # not match the slug's Loop username — i.e. the merchant or a third-party
    # account replied. Inserted/flipped by the observed-responded flow. Treated
    # as "responded, not by Loop" — operator queue hides it (so it doesn't get
    # re-handled) but it does NOT count toward Loop's per-operator throughput
    # or Chain Value's `loop_responded` waterfall leg.
    AUTO_RESOLVED = "auto_resolved"
