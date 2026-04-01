from __future__ import annotations

"""Wikipedia OAuth 2.0 authentication for ClanDi 2.0.

Uses MediaWiki's OAuth 2.0 endpoints to authenticate users
with their Wikipedia accounts.

Setup:
1. Register an OAuth consumer at https://meta.wikimedia.org/wiki/Special:OAuthConsumerRegistration/propose
2. Set environment variables: WIKI_CLIENT_ID, WIKI_CLIENT_SECRET, CLANDI_BASE_URL
"""

import os
import secrets

import httpx

# OAuth config from environment
CLIENT_ID = os.environ.get("WIKI_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("WIKI_CLIENT_SECRET", "")
BASE_URL = os.environ.get("CLANDI_BASE_URL", "http://localhost:8000")
CALLBACK_PATH = "/auth/callback"

# MediaWiki OAuth 2.0 endpoints (Meta-Wiki)
WIKI_BASE = "https://meta.wikimedia.org"
AUTHORIZE_URL = f"{WIKI_BASE}/w/rest.php/oauth2/authorize"
TOKEN_URL = f"{WIKI_BASE}/w/rest.php/oauth2/access_token"
PROFILE_URL = f"{WIKI_BASE}/w/rest.php/oauth2/resource/profile"

HEADERS = {
    "User-Agent": "ClanDi/2.0 (Wikipedia Editor Training; contact: wikibridge@example.com)",
}


def get_callback_url() -> str:
    return f"{BASE_URL}{CALLBACK_PATH}"


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def get_authorize_url(state: str) -> str:
    """Build the OAuth authorization URL to redirect the user to."""
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": get_callback_url(),
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{AUTHORIZE_URL}?{query}"


async def exchange_code(code: str) -> dict | None:
    """Exchange authorization code for access + refresh tokens.

    Returns dict with access_token, refresh_token, expires_in
    or None on failure.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": get_callback_url(),
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
            headers=HEADERS,
        )
        if resp.status_code == 200:
            return resp.json()
    return None


async def get_user_profile(access_token: str) -> dict | None:
    """Fetch the authenticated user's profile from MediaWiki.

    Returns dict with username, editcount, sub (user ID), etc.
    or None on failure.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            PROFILE_URL,
            headers={
                **HEADERS,
                "Authorization": f"Bearer {access_token}",
            },
        )
        if resp.status_code == 200:
            return resp.json()
    return None


async def refresh_access_token(refresh_token: str) -> dict | None:
    """Use refresh token to get a new access token."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
            headers=HEADERS,
        )
        if resp.status_code == 200:
            return resp.json()
    return None


def is_configured() -> bool:
    """Check if OAuth credentials are set."""
    return bool(CLIENT_ID and CLIENT_SECRET)
