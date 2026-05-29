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
- **Coupon to include:** {coupon_display}
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

### **Coupon Guidelines (STRICT)**
- If the **Coupon to include** line says "NO COUPON":
  - You MUST NOT mention any dollar amount anywhere in the reply.
  - You MUST NOT use the words "discount", "coupon", "credit", "voucher",
    "off your", "save", "deal", "promo", or any similar promotional
    language.
  - Do NOT invent a small token amount like "$0.50", "$1", or "$2" — the
    customer receives nothing.
- If the **Coupon to include** line shows a positive dollar amount
  (e.g. "$5"):
  - You MUST include that exact dollar amount in the response, written
    with the "$" symbol and the same number (e.g. "$5").
  - Frame it naturally as a discount or credit on their next order.

### **Item Reference Guidelines**
- When Review Feedback is empty AND Item Ordered is provided, you MUST
  reference the food category in your reply (do not fall back to generic
  "your meal" / "your order" in this case — the category is the only signal
  available to make the reply feel personal).
- When Review Feedback is present, referencing the order is optional —
  prioritise responding to the customer's words.
- NEVER quote exact item names, sizes, modifiers, or combos verbatim.
  Generalise to a short food category that captures the order
  (e.g. "burger meal", "pizza", "wings", "bowl", "sandwich", "tacos",
  "your sides"). Pick the most representative category.
- If the items don't map cleanly to one category, fall back to neutral
  phrasing like "your meal" or "your order" — never list items.
- If no items are provided, do not invent any.

### **Critical Name Requirement**
- MUST include the exact customer name "{customer_name}" in your response.

### **Important Constraints**
- Response MUST be within **{char_limit} characters**.
- Keep it concise but meaningful.
- Ensure the response is final and requires no manual edits.

Now, generate a response following these guidelines. Output only the
reply text — no preamble, no explanation, no sign-off block.
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
    """Pick the best matching response config for a review (most recent that matches all criteria).

    All six filter dimensions (chain, ratings, vb_platforms, customer_types,
    feedback_presence, paused) use the same rule across SQL eligibility and
    Python matching — an empty/missing list means "no filter / accept all".
    chain_name MUST match exactly; we never let one chain's config respond
    to another chain's review (was a real bug — see commit history).
    """
    review_chain = review.get("chain_name")
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
        # Chain must match exactly — no cross-tenant matches.
        if cfg.get("chain_name") != review_chain:
            continue
        feedback_presence = cfg.get("feedback_presence") or []
        if feedback_presence and feedback_type not in feedback_presence:
            continue
        ratings = cfg.get("ratings") or []
        if ratings:
            rating_matches = False
            if star_rating is not None and str(star_rating) in ratings:
                rating_matches = True
            if rating_value is not None and rating_value in ratings:
                rating_matches = True
            if not rating_matches:
                continue
        platforms = cfg.get("vb_platforms") or []
        if platforms and (merchant is None or merchant not in platforms):
            continue
        customer_types = cfg.get("customer_types") or []
        if customer_types and (customer_type is None or customer_type not in customer_types):
            continue
        matching.append(cfg)

    if not matching:
        return None
    matching.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    return matching[0]


# ── Generation ───────────────────────────────────────────────────────────────

_COUPON_LANGUAGE_RE = re.compile(
    r"\b(discount|coupon|credit|voucher|off\s+your|promo|save|deal)\b",
    re.IGNORECASE,
)


def _validate(response: str, review: dict, coupon: str) -> Optional[str]:
    errors = []
    customer_name = review.get("customer_name")
    if customer_name and response and customer_name not in response:
        errors.append("Customer name not found in response")

    no_coupon = coupon in ("None", "0", "", "0.0") or not coupon
    if response:
        if no_coupon:
            # Any $-amount or coupon-style word is hallucination when no
            # coupon was configured.
            if re.search(r"\$\d", response):
                errors.append("Response contains a $-amount but no coupon was configured")
            if _COUPON_LANGUAGE_RE.search(response):
                errors.append("Response uses coupon language but no coupon was configured")
        else:
            if f"${coupon}" not in response:
                errors.append(f"Coupon value ${coupon} not found in response")

    if review.get("platform") == "Doordash" and response:
        if re.search(r"\bstars?\b", response, re.IGNORECASE):
            errors.append("DoorDash response mentions 'star' — disallowed")
    return "|".join(errors) if errors else None


MAX_ATTEMPTS = 3


def _call_openai(review: dict, config: dict, coupon_value: float) -> Tuple[str, Optional[str]]:
    client = get_openai_client()
    char_limit = 300 if "Doordash" in review.get("platform", "") else 500
    tone = _tone(_sentiment(review), config.get("tonality", "neutral"))
    rating_display = _rating_display(review)

    coupon_str = "None"
    if coupon_value and coupon_value > 0:
        coupon_str = str(int(coupon_value)) if float(coupon_value).is_integer() else str(coupon_value)

    # coupon_display is what the model literally sees. "NO COUPON" / "$5" is
    # much harder for the model to misinterpret than the old "$None" string.
    coupon_display = f"${coupon_str}" if coupon_str != "None" else "NO COUPON"

    items_point = ""
    item_reviews_point = ""
    if review.get("items"):
        items_point = f"- **Item Ordered:** {review.get('items')}"
    if review.get("item_reviews"):
        item_reviews_point = f"- **Item Reviews:** {review.get('item_reviews')}"

    prompt = RESPONSE_PROMPT.format(
        platform=review.get("platform", "Unknown"),
        tone=tone, customer_name=review.get("customer_name", "Customer"),
        rating_display=rating_display, review_text=review.get("review_text", ""),
        coupon_display=coupon_display, item_reviews_point=item_reviews_point,
        items_point=items_point, char_limit=char_limit,
    )

    # Multi-turn retry: when an attempt fails char-limit or validator, feed
    # the failed text + the specific failure reasons back as conversation
    # context so the next attempt can correct itself rather than starting
    # blind. Shared budget (MAX_ATTEMPTS) across both failure modes.
    messages = [{"role": "user", "content": prompt}]
    response_text = ""
    errors: Optional[str] = None
    for attempt in range(MAX_ATTEMPTS):
        resp = client.chat.completions.create(
            model="gpt-4.1-nano", temperature=0.7, messages=messages,
        )
        response_text = resp.choices[0].message.content.strip()
        length_ok = len(response_text) <= char_limit
        errors = _validate(response_text, review, coupon_str)
        if length_ok and not errors:
            break

        # Build feedback for next attempt
        problems: list[str] = []
        if not length_ok:
            problems.append(
                f"Length was {len(response_text)} chars; the limit is {char_limit}. "
                f"Shorten the reply."
            )
        if errors:
            problems.append(f"Validation errors: {errors}")
        feedback = (
            "Your previous reply did NOT meet the rules:\n- "
            + "\n- ".join(problems)
            + "\n\nGenerate the entire reply again from scratch, fixing every "
            "issue above. Output only the reply text — no preamble, no "
            "explanation, no sign-off."
        )
        messages.append({"role": "assistant", "content": response_text})
        messages.append({"role": "user", "content": feedback})
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(1)

    response_text = response_text[:char_limit]
    # Final validator pass after potential truncation
    errors = _validate(response_text, review, coupon_str)
    return response_text, errors


def generate_and_save(review: dict, config: dict) -> dict:
    """Generate an AI response and persist to PostgreSQL. Returns generation outcome."""
    platform = review.get("platform", "")
    platform_configs = config.get("platform_configs", {})
    platform_config = platform_configs.get(platform, {})

    if platform_config and platform_config.get("coupon_type"):
        # DB stores the type as lowercase ("fixed") today; .upper() makes us
        # tolerant of either casing in case the config UI ever writes "FIXED".
        coupon_value = (
            platform_config.get("fixed_value", 0.0)
            if platform_config["coupon_type"].upper() == "FIXED"
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
