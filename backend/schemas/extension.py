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


class ObservedRespondedItem(BaseModel):
    platform: str  # "Doordash" or "UberEats"
    # review_uid must align with how fetch_reviews_14d derives it:
    #   DD → cxReviewId  (review_id in automation_reviews)
    #   UE → workflowUUID (order_id in automation_reviews; review_id is NULL)
    review_uid: str
    order_id: str
    store_id: str = ""


class ObservedRespondedBody(BaseModel):
    items: list[ObservedRespondedItem]
