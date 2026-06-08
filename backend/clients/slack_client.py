"""Slack chat.postMessage wrapper."""
from __future__ import annotations

import requests

from backend.clients.secret_manager import get_slack_bot_token


_SLACK_API = "https://slack.com/api/chat.postMessage"


def post_message(channel: str, text: str, blocks: list | None = None) -> None:
    """Post to Slack. `text` is the fallback/notification string; `blocks` is the
    rich body. Raises RuntimeError on auth/transport/Slack-API failure so callers
    can decide whether to swallow."""
    token = get_slack_bot_token()
    if not token:
        raise RuntimeError("Slack bot token not configured")

    payload: dict = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks

    resp = requests.post(
        _SLACK_API,
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"Slack API error: {body.get('error', 'unknown')}")
