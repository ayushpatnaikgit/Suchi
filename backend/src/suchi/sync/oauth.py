"""Google OAuth 2.0 for desktop/CLI apps using localhost redirect (Method 1).

Flow:
1. Start a temporary HTTP server on localhost:8085
2. Open browser to Google consent screen
3. User clicks Allow → Google redirects to localhost:8085/callback?code=XYZ
4. Exchange code for access + refresh tokens
5. Save tokens to ~/.config/suchi/gdrive-token.json
6. Shut down temp server

No hosted server needed — the "server" runs on the user's machine for ~30 seconds.
"""

import json
import os
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

from ..config import CONFIG_DIR

# OAuth credentials — shipped with the app (public for desktop OAuth, like rclone does).
# Users can override via env vars for self-hosted/enterprise use.
def _load_oauth_credentials() -> tuple[str, str]:
    """Load OAuth client credentials from env vars or config file.

    Desktop OAuth credentials are NOT secrets (Google documents this),
    but GitHub's push protection flags them. So we load from:
    1. Environment variables (highest priority)
    2. ~/.config/suchi/oauth-credentials.json (user-provided)

    To set up: download your OAuth credentials from Google Cloud Console
    and save as ~/.config/suchi/oauth-credentials.json with format:
    {"client_id": "...", "client_secret": "..."}
    """
    client_id = os.environ.get("SUCHI_GDRIVE_CLIENT_ID", "")
    client_secret = os.environ.get("SUCHI_GDRIVE_CLIENT_SECRET", "")

    if client_id and client_secret:
        return client_id, client_secret

    # Try config file
    creds_file = CONFIG_DIR / "oauth-credentials.json"
    if creds_file.exists():
        try:
            import json
            creds = json.loads(creds_file.read_text())
            return creds["client_id"], creds["client_secret"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    raise RuntimeError(
        "Google OAuth credentials not found.\n"
        "Set up sync by saving your credentials:\n"
        f"  echo '{{\"client_id\": \"YOUR_ID\", \"client_secret\": \"YOUR_SECRET\"}}' > {creds_file}\n"
        "Or set env vars: SUCHI_GDRIVE_CLIENT_ID and SUCHI_GDRIVE_CLIENT_SECRET\n"
        "Get credentials at: https://console.cloud.google.com/apis/credentials"
    )


# Lazy-loaded — only resolved when login() is called
GDRIVE_CLIENT_ID = ""
GDRIVE_CLIENT_SECRET = ""


def _ensure_credentials():
    global GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET
    if not GDRIVE_CLIENT_ID:
        GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET = _load_oauth_credentials()

REDIRECT_PORT = 8085
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
TOKEN_FILE = CONFIG_DIR / "gdrive-token.json"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Scopes: manage only files created by Suchi + see user email for display
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/userinfo.email",
]


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth redirect callback on localhost."""

    auth_code: str | None = None
    error: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            self._respond(
                "<html><body style='font-family:system-ui;text-align:center;padding:60px'>"
                "<h2>✓ Signed in to Suchi</h2>"
                "<p>You can close this tab and return to the terminal.</p>"
                "</body></html>"
            )
        elif "error" in params:
            _OAuthCallbackHandler.error = params["error"][0]
            self._respond(
                "<html><body style='font-family:system-ui;text-align:center;padding:60px'>"
                f"<h2>Authentication failed</h2><p>{params['error'][0]}</p>"
                "</body></html>"
            )
        else:
            self._respond("Waiting for OAuth callback...")

    def _respond(self, html: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # Suppress HTTP logs


def login() -> dict:
    """Run the full OAuth flow. Returns the token data dict.

    Opens the browser for Google consent, catches the callback on localhost,
    exchanges the code for tokens, and saves them to disk.
    """
    _ensure_credentials()

    # Build the authorization URL
    auth_params = {
        "client_id": GDRIVE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",      # Get a refresh token
        "prompt": "consent",            # Always show consent to get refresh token
    }
    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(auth_params)}"

    # Start temporary localhost server
    _OAuthCallbackHandler.auth_code = None
    _OAuthCallbackHandler.error = None
    server = HTTPServer(("localhost", REDIRECT_PORT), _OAuthCallbackHandler)
    server.timeout = 120  # 2 minute timeout

    # Open browser
    webbrowser.open(auth_url)

    # Wait for callback (blocks until request received or timeout)
    while _OAuthCallbackHandler.auth_code is None and _OAuthCallbackHandler.error is None:
        server.handle_request()

    server.server_close()

    if _OAuthCallbackHandler.error:
        raise RuntimeError(f"OAuth failed: {_OAuthCallbackHandler.error}")
    if not _OAuthCallbackHandler.auth_code:
        raise RuntimeError("No authorization code received (timed out?)")

    # Exchange code for tokens
    token_data = _exchange_code(_OAuthCallbackHandler.auth_code)

    # Get user email for display
    email = _get_user_email(token_data["access_token"])
    token_data["email"] = email

    # Save tokens
    _save_tokens(token_data)

    return token_data


def logout():
    """Clear saved tokens."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


def get_credentials() -> dict | None:
    """Load saved tokens, refreshing if expired. Returns None if not logged in."""
    token_data = _load_tokens()
    if not token_data:
        return None

    # Check if access token is expired
    expires_at = token_data.get("expires_at", 0)
    if time.time() >= expires_at - 60:  # Refresh 60s before expiry
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            return None
        try:
            token_data = _refresh_access_token(refresh_token)
            # Preserve email from original login
            old = _load_tokens()
            if old:
                token_data["email"] = old.get("email", "")
            _save_tokens(token_data)
        except Exception:
            return None

    return token_data


def get_access_token() -> str | None:
    """Get a valid access token, refreshing if needed. Returns None if not logged in."""
    creds = get_credentials()
    return creds["access_token"] if creds else None


def get_user_email() -> str | None:
    """Get the logged-in user's email. Returns None if not logged in."""
    token_data = _load_tokens()
    return token_data.get("email") if token_data else None


def is_logged_in() -> bool:
    """Check if the user is logged in (has saved tokens)."""
    return TOKEN_FILE.exists()


def _exchange_code(code: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    _ensure_credentials()
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": GDRIVE_CLIENT_ID,
            "client_secret": GDRIVE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {resp.text}")

    data = resp.json()
    data["expires_at"] = time.time() + data.get("expires_in", 3600)
    return data


def _refresh_access_token(refresh_token: str) -> dict:
    """Use refresh token to get a new access token."""
    _ensure_credentials()
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": GDRIVE_CLIENT_ID,
            "client_secret": GDRIVE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token refresh failed: {resp.text}")

    data = resp.json()
    data["refresh_token"] = refresh_token  # Google doesn't always return it on refresh
    data["expires_at"] = time.time() + data.get("expires_in", 3600)
    return data


def _get_user_email(access_token: str) -> str:
    """Fetch the user's email from Google."""
    resp = httpx.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if resp.status_code == 200:
        return resp.json().get("email", "")
    return ""


def _save_tokens(token_data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
    # Restrict permissions (tokens are sensitive)
    TOKEN_FILE.chmod(0o600)


def _load_tokens() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        return json.loads(TOKEN_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
