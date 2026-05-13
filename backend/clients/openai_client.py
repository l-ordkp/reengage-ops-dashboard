"""OpenAI client singleton."""
from __future__ import annotations

from openai import OpenAI

from backend.clients.secret_manager import get_openai_api_key

_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=get_openai_api_key())
    return _client
