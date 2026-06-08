"""Fetch secrets — env vars first, then GCP Secret Manager."""
from __future__ import annotations

import os


def get_openai_api_key() -> str:
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        return env_key

    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = "projects/983150008719/secrets/openai-del-intel/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        raise RuntimeError(f"Could not fetch OpenAI API key: {e}")


def _get_secret(env_var: str, secret_name: str) -> str:
    """Env var first, then GCP Secret Manager. Returns "" if neither resolves."""
    val = os.environ.get(env_var)
    if val:
        return val
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/983150008719/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception:
        return ""


def get_google_oauth_client_id() -> str:
    return _get_secret("GOOGLE_OAUTH_CLIENT_ID", "reengage-v2-google-oauth-client-id")


def get_google_oauth_client_secret() -> str:
    return _get_secret("GOOGLE_OAUTH_CLIENT_SECRET", "reengage-v2-google-oauth-client-secret")


def get_jwt_secret_key() -> str:
    val = _get_secret("JWT_SECRET_KEY", "reengage-v2-jwt-secret")
    return val or "dev-secret-change-in-prod"


def get_slack_bot_token() -> str:
    return _get_secret("SLACK_BOT_TOKEN", "reengage-slack-bot")
