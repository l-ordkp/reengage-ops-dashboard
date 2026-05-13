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
