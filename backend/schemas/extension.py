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
