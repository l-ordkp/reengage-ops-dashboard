"""Chrome extension API schemas."""
from __future__ import annotations

from pydantic import BaseModel


class MarkRespondedBody(BaseModel):
    order_id: str
    platform: str
    chain_name: str = ""
    # QC fields captured from the merchant portal request
    replied_response: str = ""
    replied_discount: str = ""
    exact_match_response: bool = True
    exact_match_discount: bool = True
    # Platform-issued IDs captured from the reply-submission response.
    # DoorDash: result.messageId + campaignId. UberEats: submitEaterReviewReply.uuid
    # + submitEaterReviewReply.promotion.uuid. Empty when not present (e.g. no coupon).
    platform_reply_id: str = ""
    platform_coupon_id: str = ""
