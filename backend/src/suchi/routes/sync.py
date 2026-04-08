"""Sync routes — Google Drive OAuth + sync status for the UI."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
def sync_status():
    """Get current sync status — logged in? last sync? pending changes?"""
    from ..sync.oauth import is_logged_in, get_user_email

    if not is_logged_in():
        return {
            "logged_in": False,
            "email": None,
            "last_sync": None,
            "pending": 0,
        }

    return {
        "logged_in": True,
        "email": get_user_email(),
        "last_sync": None,  # TODO: read from sync state
        "pending": 0,
    }


@router.post("/login")
def start_login():
    """Start the OAuth flow — opens browser for Google consent.

    Call this from the UI. The OAuth callback happens on localhost:8085
    which the Python backend handles. Once complete, /api/sync/status
    will show logged_in=true.
    """
    from ..sync.oauth import login as oauth_login

    try:
        token_data = oauth_login()
        return {
            "ok": True,
            "email": token_data.get("email", ""),
        }
    except Exception as e:
        raise HTTPException(500, f"Login failed: {e}")


@router.post("/logout")
def do_logout():
    """Sign out — clear stored tokens."""
    from ..sync.oauth import logout as oauth_logout
    oauth_logout()
    return {"ok": True}


class SyncRequest(BaseModel):
    collection: str | None = None
    push_only: bool = False
    pull_only: bool = False


@router.post("/run")
async def run_sync(req: SyncRequest):
    """Trigger a sync cycle."""
    from ..sync.oauth import is_logged_in
    from ..sync.engine import run_sync as do_sync

    if not is_logged_in():
        raise HTTPException(401, "Not signed in. Click 'Sign in with Google' in Settings.")

    try:
        stats = await do_sync(
            collection_name=req.collection,
            push_only=req.push_only,
            pull_only=req.pull_only,
        )
        return stats
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {e}")


class ShareRequest(BaseModel):
    collection: str
    email: str
    role: str = "editor"  # "editor" or "viewer"


@router.post("/share")
async def share_collection(req: ShareRequest):
    """Share a collection via Google Drive."""
    from ..sync.oauth import is_logged_in
    from ..sync.engine import ensure_collection_on_drive
    from ..sync import gdrive

    if not is_logged_in():
        raise HTTPException(401, "Not signed in")

    drive_role = "writer" if req.role == "editor" else "reader"

    try:
        folder_id = await ensure_collection_on_drive(req.collection)
        await gdrive.share_folder(folder_id, req.email, role=drive_role)
        return {"ok": True, "folder_id": folder_id}
    except Exception as e:
        raise HTTPException(500, f"Share failed: {e}")
