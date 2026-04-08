"""Google Drive API wrapper for Suchi sync.

Handles uploading/downloading entries to a shared Drive folder.
Each collection gets its own Drive folder. Private collections stay local.
"""

import json
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from .oauth import get_access_token

DRIVE_API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"


class DriveError(Exception):
    pass


def _headers() -> dict[str, str]:
    token = get_access_token()
    if not token:
        raise DriveError("Not logged in. Run: suchi login")
    return {"Authorization": f"Bearer {token}"}


async def _get(path: str, params: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{DRIVE_API}/{path}", headers=_headers(), params=params)
        if resp.status_code != 200:
            raise DriveError(f"Drive API error {resp.status_code}: {resp.text[:200]}")
        return resp.json()


async def _post(path: str, json_data: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{DRIVE_API}/{path}", headers=_headers(), json=json_data)
        if resp.status_code not in (200, 201):
            raise DriveError(f"Drive API error {resp.status_code}: {resp.text[:200]}")
        return resp.json()


# ──────────────────────────────────────────────
# Folder Operations
# ──────────────────────────────────────────────

async def find_or_create_folder(name: str, parent_id: str | None = None) -> str:
    """Find a folder by name (under parent), or create it. Returns folder ID."""
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"

    result = await _get("files", params={"q": q, "fields": "files(id,name)", "spaces": "drive"})
    files = result.get("files", [])
    if files:
        return files[0]["id"]

    # Create it
    metadata: dict[str, Any] = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    created = await _post("files", json_data=metadata)
    return created["id"]


async def get_suchi_root_folder() -> str:
    """Get or create the 'SuchiLibrary' root folder on Drive."""
    return await find_or_create_folder("SuchiLibrary")


# ──────────────────────────────────────────────
# File Operations
# ──────────────────────────────────────────────

async def upload_file(local_path: Path, parent_folder_id: str, drive_filename: str | None = None) -> dict:
    """Upload a file to Drive. Returns the file metadata dict."""
    filename = drive_filename or local_path.name
    mime = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"

    # Check if file already exists in this folder
    existing = await _get("files", params={
        "q": f"name='{filename}' and '{parent_folder_id}' in parents and trashed=false",
        "fields": "files(id,name,modifiedTime)",
    })
    existing_files = existing.get("files", [])

    file_content = local_path.read_bytes()

    async with httpx.AsyncClient(timeout=120) as client:
        if existing_files:
            # Update existing file
            file_id = existing_files[0]["id"]
            resp = await client.patch(
                f"{UPLOAD_API}/files/{file_id}",
                headers={**_headers(), "Content-Type": mime},
                params={"uploadType": "media"},
                content=file_content,
            )
        else:
            # Create new file (multipart upload: metadata + content)
            boundary = "suchi_upload_boundary"
            metadata = json.dumps({
                "name": filename,
                "parents": [parent_folder_id],
            })

            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{metadata}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: {mime}\r\n\r\n"
            ).encode() + file_content + f"\r\n--{boundary}--".encode()

            resp = await client.post(
                f"{UPLOAD_API}/files",
                headers={
                    **_headers(),
                    "Content-Type": f"multipart/related; boundary={boundary}",
                },
                params={"uploadType": "multipart"},
                content=body,
            )

        if resp.status_code not in (200, 201):
            raise DriveError(f"Upload failed: {resp.text[:200]}")
        return resp.json()


async def download_file(file_id: str, local_path: Path) -> None:
    """Download a file from Drive to a local path."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(
            f"{DRIVE_API}/files/{file_id}",
            headers=_headers(),
            params={"alt": "media"},
        )
        if resp.status_code != 200:
            raise DriveError(f"Download failed: {resp.text[:200]}")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(resp.content)


async def delete_file(file_id: str) -> None:
    """Move a file to trash on Drive."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"{DRIVE_API}/files/{file_id}",
            headers=_headers(),
            json={"trashed": True},
        )
        if resp.status_code != 200:
            raise DriveError(f"Delete failed: {resp.text[:200]}")


async def list_folder(folder_id: str) -> list[dict]:
    """List all files in a Drive folder."""
    all_files = []
    page_token = None

    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,md5Checksum,size)",
            "pageSize": 100,
        }
        if page_token:
            params["pageToken"] = page_token

        result = await _get("files", params=params)
        all_files.extend(result.get("files", []))

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return all_files


async def get_file_metadata(file_id: str) -> dict:
    """Get metadata for a single file."""
    return await _get(f"files/{file_id}", params={
        "fields": "id,name,mimeType,modifiedTime,md5Checksum,size,parents",
    })


# ──────────────────────────────────────────────
# Sharing
# ──────────────────────────────────────────────

async def share_folder(folder_id: str, email: str, role: str = "writer") -> dict:
    """Share a Drive folder with someone.

    Args:
        folder_id: The Drive folder ID.
        email: Email to share with.
        role: "writer" (editor) or "reader" (viewer).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{DRIVE_API}/files/{folder_id}/permissions",
            headers=_headers(),
            json={
                "type": "user",
                "role": role,
                "emailAddress": email,
            },
            params={"sendNotificationEmail": "true"},
        )
        if resp.status_code not in (200, 201):
            raise DriveError(f"Share failed: {resp.text[:200]}")
        return resp.json()


async def unshare_folder(folder_id: str, email: str) -> None:
    """Remove sharing access for an email."""
    # First find the permission ID
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{DRIVE_API}/files/{folder_id}/permissions",
            headers=_headers(),
            params={"fields": "permissions(id,emailAddress)"},
        )
        if resp.status_code != 200:
            raise DriveError(f"Failed to list permissions: {resp.text[:200]}")

        perms = resp.json().get("permissions", [])
        target = next((p for p in perms if p.get("emailAddress", "").lower() == email.lower()), None)
        if not target:
            raise DriveError(f"No permission found for {email}")

        resp = await client.delete(
            f"{DRIVE_API}/files/{folder_id}/permissions/{target['id']}",
            headers=_headers(),
        )
        if resp.status_code not in (200, 204):
            raise DriveError(f"Unshare failed: {resp.text[:200]}")


async def list_permissions(folder_id: str) -> list[dict]:
    """List who has access to a folder."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{DRIVE_API}/files/{folder_id}/permissions",
            headers=_headers(),
            params={"fields": "permissions(id,emailAddress,role,type)"},
        )
        if resp.status_code != 200:
            raise DriveError(f"Failed to list permissions: {resp.text[:200]}")
        return resp.json().get("permissions", [])


# ──────────────────────────────────────────────
# Change Detection
# ──────────────────────────────────────────────

async def list_changes_in_folder(folder_id: str, since: str | None = None) -> list[dict]:
    """List files modified since a given timestamp in a folder.

    Args:
        folder_id: Drive folder ID.
        since: ISO timestamp (e.g., "2026-04-06T12:00:00Z"). If None, returns all files.

    Returns:
        List of file metadata dicts for changed files.
    """
    q = f"'{folder_id}' in parents and trashed=false"
    if since:
        q += f" and modifiedTime > '{since}'"

    return await list_folder_with_query(folder_id, q)


async def list_folder_with_query(folder_id: str, query: str) -> list[dict]:
    """List files matching a query."""
    all_files = []
    page_token = None

    while True:
        params = {
            "q": query,
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,md5Checksum,size)",
            "pageSize": 100,
        }
        if page_token:
            params["pageToken"] = page_token

        result = await _get("files", params=params)
        all_files.extend(result.get("files", []))

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return all_files
