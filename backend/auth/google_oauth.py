"""Google OAuth code exchange."""

import requests

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


from typing import Optional

def exchange_google_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> Optional[dict]:
    """Exchange Google auth code for user info. Returns {email, name} or None."""
    token_resp = requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    if token_resp.status_code != 200:
        return None
    access_token = token_resp.json().get("access_token")
    if not access_token:
        return None
    user_resp = requests.get(GOOGLE_USERINFO_URL, headers={
        "Authorization": f"Bearer {access_token}",
    })
    if user_resp.status_code != 200:
        return None
    info = user_resp.json()
    return {"email": info.get("email", ""), "name": info.get("name", "")}
