"""
AI response generation business logic.
Wraps OpenAI calls + PG persistence + config matching.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional, Tuple

from backend.clients.openai_client import get_openai_client
from backend.repositories.response_repository import upsert_response

logger = logging.getLogger(__name__)


RESPONSE_PROMPT = """
You are an AI assistant for a restaurant chain for online orders, responding to customer reviews with a **{tone}** tone. Your response should be natural and **final**, with **no placeholders**.

### **Review Details**
- **Platform:** {platform}
- **Customer Name:** {customer_name}
- **Review Rating:** {rating_display}
- **Review Feedback:** {review_text}
- **Coupon Given:** ${coupon} (will be "None" if not applicable)
{item_reviews_point}
{items_point}

### **Platform Vocabulary (CRITICAL)**
- If Platform is "Doordash", the rating system is **Loved / Liked / Didn't like**.
  NEVER use the word "star" or "stars" anywhere in the response. Do not say
  "5-star rating", "thanks for the stars", etc. Refer to the rating only as
  Loved / Liked / Didn't like, or simply as "your rating" / "your feedback".
- If Platform is "UberEats", the rating is a star count (1-5). You may use
  "stars" naturally when referring to it.

### **Response Guidelines**
- **DO NOT** ask the customer any questions. This is a one-time reply.
- **DO NOT** echo or repeat the customer's exact words or phrases.
- For a **positive** review (Loved, Liked, or 4-5 stars): Thank warmly.
- For a **neutral** review (3 stars): Acknowledge feedback.
- For a **negative** review (Didn't like, or 1-2 stars): Apologize genuinely.

### **Coupon Guidelines**
- If coupon is "None", "0", "$0", empty, or zero -> DO NOT mention any coupon
- If coupon is a positive number -> YOU MUST include it naturally

### **Critical Name Requirement**
- MUST include the exact customer name "{customer_name}" in your response.

### **Important Constraints**
- Response MUST be within **{char_limit} characters**.
- Keep it concise but meaningful.
- Ensure the response is final and requires no manual edits.

Now, generate a response following these guidelines.
"""


# ── Rating helpers ───────────────────────────────────────────────────────────

def _rating_display(review: dict) -> str:
    """
    Human-readable rating label fed into the LLM prompt.

    DoorDash uses three customer-facing buckets (Loved / Liked / Didn't like).
    The API still emits legacy 1-5 enums for a small tail of reviews, but the
    merchant portal collapses everything into those three buckets, so we do
    too. UberEats genuinely uses 1-5 stars and never sets `rating_value`.
    """
    platform = review.get("platform", "")
    rating_value = review.get("rating_value")
    star_rating = review.get("star_rating")
    if platform == "Doordash" and rating_value:
        return {
            "RATING_VALUE_LOVED":       "Loved",
            "RATING_VALUE_FIVE":        "Loved",
            "RATING_VALUE_THUMBS_UP":   "Liked",
            "RATING_VALUE_FOUR":        "Liked",
            "RATING_VALUE_THREE":       "Didn't like",
            "RATING_VALUE_TWO":         "Didn't like",
            "RATING_VALUE_ONE":         "Didn't like",
            "RATING_VALUE_THUMBS_DOWN": "Didn't like",
        }.get(rating_value, rating_value)
    if star_rating is not None:
        try:
            sr = int(float(star_rating))
            if sr > 0:
                return f"{sr} stars"
        except (ValueError, TypeError):
            pass
    return "No rating"


def _sentiment(review: dict) -> str:
    platform = review.get("platform", "")
    rating_value = review.get("rating_value")
    star_rating = review.get("star_rating")
    if platform == "Doordash" and rating_value:
        if rating_value in ("RATING_VALUE_THUMBS_DOWN",
                            "RATING_VALUE_ONE", "RATING_VALUE_TWO"):
            return "negative"
        if rating_value in ("RATING_VALUE_THUMBS_UP", "RATING_VALUE_THREE",
                            "RATING_VALUE_FOUR"):
            return "neutral"
        if rating_value in ("RATING_VALUE_LOVED", "RATING_VALUE_FIVE"):
            return "positive"
    if star_rating is not None:
        try:
            sr = int(float(star_rating))
            if sr <= 2: return "negative"
            if sr == 3: return "neutral"
            if sr >= 4: return "positive"
        except (ValueError, TypeError):
            pass
    return "positive"


def _tone(sentiment: str, default_tone: str) -> str:
    return {
        "negative": "apologetic",
        "neutral": "professional",
        "positive": default_tone,
    }.get(sentiment, "professional")


# ── Config matching ──────────────────────────────────────────────────────────

def find_matching_config(review: dict, configs: list[dict]) -> Optional[dict]:
    """Pick the best matching response config for a review (most recent that matches all criteria)."""
    star_rating = review.get("star_rating")
    rating_value = review.get("rating_value")
    merchant = review.get("platform")
    customer_type = review.get("customer_type")
    review_text = review.get("review_text") or ""
    feedback_type = "with_feedback" if review_text.strip() else "without_feedback"

    matching = []
    for cfg in configs:
        if cfg.get("paused", False):
            continue
        feedback_list = cfg.get("feedback_presence", ["with_feedback", "without_feedback"])
        if feedback_type not in feedback_list:
            continue
        ratings = cfg.get("ratings", [])
        if ratings:
            rating_matches = False
            if star_rating is not None and str(star_rating) in ratings:
                rating_matches = True
            if rating_value is not None and rating_value in ratings:
                rating_matches = True
            if not rating_matches:
                continue
        platforms = cfg.get("vb_platforms", [])
        if platforms and (merchant is None or merchant not in platforms):
            continue
        customer_types = cfg.get("customer_types", [])
        if customer_types and (customer_type is None or customer_type not in customer_types):
            continue
        matching.append(cfg)

    if not matching:
        return None
    matching.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return matching[0]


# ── Generation ───────────────────────────────────────────────────────────────

def _validate(response: str, review: dict, coupon: str) -> Optional[str]:
    errors = []
    customer_name = review.get("customer_name")
    if customer_name and response and customer_name not in response:
        errors.append("Customer name not found in response")
    if response and "$0" in response:
        errors.append("$0 coupon is found in response")
    if coupon and coupon not in ("None", "0"):
        if response and f"${coupon}" not in response:
            errors.append(f"Coupon value ${coupon} not found in response")
    if review.get("platform") == "Doordash" and response:
        if re.search(r"\bstars?\b", response, re.IGNORECASE):
            errors.append("DoorDash response mentions 'star' — disallowed")
    return "|".join(errors) if errors else None


def _call_openai(review: dict, config: dict, coupon_value: float) -> Tuple[str, Optional[str]]:
    client = get_openai_client()
    char_limit = 300 if "Doordash" in review.get("platform", "") else 500
    tone = _tone(_sentiment(review), config.get("tonality", "neutral"))
    rating_display = _rating_display(review)

    coupon_str = "None"
    if coupon_value and coupon_value > 0:
        coupon_str = str(int(coupon_value)) if float(coupon_value).is_integer() else str(coupon_value)

    items_point = ""
    item_reviews_point = ""
    if review.get("items") and review.get("item_reviews"):
        items_point = f"- **Item Ordered:** {review.get('items', '')}"
        item_reviews_point = f"- **Item Reviews:** {review.get('item_reviews', '')}"

    prompt = RESPONSE_PROMPT.format(
        platform=review.get("platform", "Unknown"),
        tone=tone, customer_name=review.get("customer_name", "Customer"),
        rating_display=rating_display, review_text=review.get("review_text", ""),
        coupon=coupon_str, item_reviews_point=item_reviews_point,
        items_point=items_point, char_limit=char_limit,
    )

    response_text = ""
    for _ in range(3):
        resp = client.chat.completions.create(
            model="gpt-4.1-nano", temperature=0.7,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = resp.choices[0].message.content.strip()
        if len(response_text) <= char_limit:
            break
        time.sleep(1)

    response_text = response_text[:char_limit]
    errors = _validate(response_text, review, coupon_str)
    return response_text, errors


def generate_and_save(review: dict, config: dict) -> dict:
    """Generate an AI response and persist to PostgreSQL. Returns generation outcome."""
    platform = review.get("platform", "")
    platform_configs = config.get("platform_configs", {})
    platform_config = platform_configs.get(platform, {})

    if platform_config and platform_config.get("coupon_type"):
        coupon_value = (
            platform_config.get("fixed_value", 0.0)
            if platform_config["coupon_type"] == "FIXED"
            else platform_config.get("percentage_value", 0.0)
        )
    else:
        coupon_value = 0.0
    min_order_value = platform_config.get("min_order_value", 0.0) if platform_config else 0.0
    response_type = config.get("response_type", "AI")

    response_text, errors = _call_openai(review, config, coupon_value)
    if not response_text:
        return {
            "response_text": None, "errors": errors or "No response generated",
            "coupon_value": coupon_value, "saved": False,
        }

    saved = upsert_response(
        review=review, response_text=response_text, errors=errors,
        config_id=config.get("config_id"), coupon_value=coupon_value,
        min_order_value=min_order_value, response_type=response_type,
    )
    return {
        "response_text": response_text, "errors": errors,
        "coupon_value": coupon_value,
        "saved": saved is not None,
        "response_id": saved.id if saved else None,
    }
