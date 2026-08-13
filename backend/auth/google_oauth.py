"""Google OAuth code exchange."""

import requests

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
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


def verify_google_access_token(access_token: str, expected_client_id: str) -> Optional[dict]:
    """Verify a Google OAuth access token server-side and return {email, name}.

    Checks with Google's tokeninfo endpoint that the token is valid, was issued
    to our OAuth client (audience check, so tokens minted for other apps are
    rejected), and that the email is verified — then fetches the profile.
    Returns None on any failure.
    """
    info_resp = requests.get(GOOGLE_TOKENINFO_URL, params={"access_token": access_token})
    if info_resp.status_code != 200:
        return None
    token_info = info_resp.json()
    if expected_client_id and token_info.get("aud") != expected_client_id:
        return None
    if str(token_info.get("email_verified")).lower() != "true":
        return None
    email = token_info.get("email", "")
    if not email:
        return None
    user_resp = requests.get(GOOGLE_USERINFO_URL, headers={
        "Authorization": f"Bearer {access_token}",
    })
    name = user_resp.json().get("name", "") if user_resp.status_code == 200 else ""
    return {"email": email, "name": name}
