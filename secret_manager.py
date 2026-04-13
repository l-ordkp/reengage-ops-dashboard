"""
Fetch secrets from Google Cloud Secret Manager.
Falls back to env vars or Streamlit secrets for local dev.
"""

import os
import streamlit as st


def get_openai_api_key() -> str:
    """Get OpenAI API key — from env var, Streamlit secrets, or GCP Secret Manager."""
    # Check env var first (Cloud Run with --set-secrets)
    env_key = os.environ.get("OPENAI_API_KEY")
    if env_key:
        return env_key

    # Check Streamlit secrets (local dev)
    if "openai_api_key" in st.secrets:
        return st.secrets["openai_api_key"]

    # Fall back to GCP Secret Manager
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = "projects/arboreal-vision-339901/secrets/openai-api-key/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        raise RuntimeError(f"Could not fetch OpenAI API key: {e}")
