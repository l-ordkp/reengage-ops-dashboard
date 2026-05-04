"""AI response generator — no Streamlit dependency. Uses backend.* imports."""

import json
import time
import logging
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd
from openai import OpenAI

from backend.secret_manager import get_openai_api_key
from backend.pg_db import get_pg_session
from backend.models import ReviewResponse

logger = logging.getLogger(__name__)

_client = None


def _get_openai_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=get_openai_api_key())
    return _client


RESPONSE_PROMPT = """
You are an AI assistant for a restaurant chain for online orders, responding to customer reviews with a **{tone}** tone. Your response should be natural and **final**, with **no placeholders**.

### **Review Details**
- **Customer Name:** {customer_name}
- **Review Rating:** {rating_display}
- **Review Feedback:** {review_text}
- **Coupon Given:** ${coupon} (will be "None" if not applicable)
{item_reviews_point}
{items_point}

### **Response Guidelines**
- **DO NOT** ask the customer any questions. This is a one-time reply.
- **DO NOT** echo or repeat the customer's exact words or phrases.
- If the review is **positive (4-5 stars, Thumbs Up, or Loved)**: Thank warmly.
- If the review is **neutral (3 stars, Thumbs Up)**: Acknowledge feedback.
- If the review is **negative (1-2 stars or Thumbs Down)**: Apologize genuinely.

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


def get_rating_display(review: dict) -> str:
    platform = review.get("platform", "")
    rating_value = review.get("rating_value")
    star_rating = review.get("star_rating")
    if platform == "Doordash" and rating_value:
        rating_map = {
            "RATING_VALUE_THUMBS_DOWN": "Thumbs Down",
            "RATING_VALUE_THUMBS_UP": "Thumbs Up",
            "RATING_VALUE_LOVED": "Loved",
            "RATING_VALUE_FIVE": "5 stars",
        }
        return rating_map.get(rating_value, rating_value)
    if star_rating is not None:
        try:
            sr = int(float(star_rating))
            if sr > 0:
                return f"{sr} stars"
        except (ValueError, TypeError):
            pass
    return "No rating"


def get_sentiment_from_rating(review: dict) -> str:
    platform = review.get("platform", "")
    rating_value = review.get("rating_value")
    star_rating = review.get("star_rating")
    if platform == "Doordash" and rating_value:
        if rating_value == "RATING_VALUE_THUMBS_DOWN":
            return "negative"
        elif rating_value == "RATING_VALUE_THUMBS_UP":
            return "neutral"
        elif rating_value in ("RATING_VALUE_LOVED", "RATING_VALUE_FIVE"):
            return "positive"
    if star_rating is not None:
        try:
            sr = int(float(star_rating))
            if sr <= 2:
                return "negative"
            elif sr == 3:
                return "neutral"
            elif sr >= 4:
                return "positive"
        except (ValueError, TypeError):
            pass
    return "positive"


def adjust_tone_by_sentiment(sentiment: str, default_tone: str) -> str:
    return {"negative": "apologetic", "neutral": "professional", "positive": default_tone}.get(sentiment, "professional")


def find_matching_config(review: dict, configurations: list[dict]) -> Optional[dict]:
    review_star_rating = review.get("star_rating")
    review_rating_value = review.get("rating_value")
    review_merchant = review.get("platform")
    review_customer_type = review.get("customer_type")
    review_text = review.get("review_text") or ""
    review_feedback_type = "with_feedback" if review_text.strip() else "without_feedback"

    matching = []
    for cfg in configurations:
        if cfg.get("paused", False):
            continue
        feedback_list = cfg.get("feedback_presence", ["with_feedback", "without_feedback"])
        if review_feedback_type not in feedback_list:
            continue
        ratings = cfg.get("ratings", [])
        if ratings:
            rating_matches = False
            if review_star_rating is not None and str(review_star_rating) in ratings:
                rating_matches = True
            if review_rating_value is not None and review_rating_value in ratings:
                rating_matches = True
            if not rating_matches:
                continue
        platforms = cfg.get("vb_platforms", [])
        if platforms and (review_merchant is None or review_merchant not in platforms):
            continue
        customer_types = cfg.get("customer_types", [])
        if customer_types and (review_customer_type is None or review_customer_type not in customer_types):
            continue
        matching.append(cfg)

    if not matching:
        return None
    matching.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return matching[0]


def generate_ai_response(review: dict, config: dict, coupon_value: float) -> Tuple[str, Optional[str]]:
    client = _get_openai_client()
    char_limit = 300 if "Doordash" in review.get("platform", "") else 500
    sentiment = get_sentiment_from_rating(review)
    tone = adjust_tone_by_sentiment(sentiment, config.get("tonality", "neutral"))
    rating_display = get_rating_display(review)
    coupon_str = "None"
    if coupon_value and coupon_value > 0:
        coupon_str = str(int(coupon_value)) if float(coupon_value).is_integer() else str(coupon_value)
    items_point = ""
    item_reviews_point = ""
    if review.get("items") and review.get("item_reviews"):
        items_point = f"- **Item Ordered:** {review.get('items', '')}"
        item_reviews_point = f"- **Item Reviews:** {review.get('item_reviews', '')}"

    prompt = RESPONSE_PROMPT.format(
        tone=tone, customer_name=review.get("customer_name", "Customer"),
        rating_display=rating_display, review_text=review.get("review_text", ""),
        coupon=coupon_str, item_reviews_point=item_reviews_point,
        items_point=items_point, char_limit=char_limit,
    )
    response_text = ""
    for attempt in range(3):
        resp = client.chat.completions.create(
            model="gpt-4.1-nano", temperature=0.7,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = resp.choices[0].message.content.strip()
        if len(response_text) <= char_limit:
            break
        time.sleep(1)
    response_text = response_text[:char_limit]
    errors = validate_response(response_text, review, coupon_str)
    return response_text, errors


def validate_response(response: str, review: dict, coupon: str) -> Optional[str]:
    errors = []
    customer_name = review.get("customer_name")
    if customer_name and response and customer_name not in response:
        errors.append("Customer name not found in response")
    if response and "$0" in response:
        errors.append("$0 coupon is found in response")
    if coupon and coupon != "None" and coupon != "0":
        if response and f"${coupon}" not in response:
            errors.append(f"Coupon value ${coupon} not found in response")
    return "|".join(errors) if errors else None


def save_response_to_db(review, response_text, errors, config_id, coupon_value, min_order_value, response_type):
    session = get_pg_session()
    try:
        existing = session.query(ReviewResponse).filter(ReviewResponse.order_id == review.get("order_id")).first()
        if existing:
            existing.response_text = response_text
            existing.response_type = response_type
            existing.config_id = config_id
            existing.coupon_value = coupon_value
            existing.min_order_value = min_order_value
            existing.generated_at = datetime.utcnow()
            existing.response_sent = None
            existing.errors = errors
            session.commit()
            session.refresh(existing)
            return existing

        order_ts = review.get("event_timestamp")
        rr = ReviewResponse(
            platform=review.get("platform"), slug=review.get("slug"),
            b_name_id=review.get("b_name_id"), store_id=review.get("store_id"),
            order_id=review.get("order_id"),
            order_timestamp=order_ts if not pd.isna(order_ts) else None,
            review_timestamp=order_ts if not pd.isna(order_ts) else None,
            review_id=review.get("review_id"), customer_name=review.get("customer_name"),
            rating=_safe_int(review.get("star_rating")), review_text=review.get("review_text"),
            response_text=response_text, response_type=response_type,
            generated_at=datetime.utcnow(), config_id=config_id,
            coupon_value=coupon_value, min_order_value=min_order_value,
            errors=errors, items=review.get("items"), item_reviews=review.get("item_reviews"),
        )
        session.add(rr)
        session.commit()
        session.refresh(rr)
        return rr
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to save response: {e}")
        return None
    finally:
        session.close()


def _safe_int(val):
    if val is None:
        return None
    try:
        v = int(float(val))
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def generate_and_save(review: dict, config: dict) -> dict:
    platform = review.get("platform", "")
    platform_configs = config.get("platform_configs", {})
    platform_config = platform_configs.get(platform, {})
    if platform_config and platform_config.get("coupon_type"):
        coupon_value = platform_config.get("fixed_value", 0.0) if platform_config["coupon_type"] == "FIXED" else platform_config.get("percentage_value", 0.0)
    else:
        coupon_value = 0.0
    min_order_value = platform_config.get("min_order_value", 0.0) if platform_config else 0.0
    response_type = config.get("response_type", "AI")
    response_text, errors = generate_ai_response(review, config, coupon_value)
    if not response_text:
        return {"response_text": None, "errors": errors or "No response generated", "coupon_value": coupon_value, "saved": False}
    saved = save_response_to_db(review, response_text, errors, config.get("config_id"), coupon_value, min_order_value, response_type)
    return {"response_text": response_text, "errors": errors, "coupon_value": coupon_value, "saved": saved is not None, "response_id": saved.id if saved else None}
