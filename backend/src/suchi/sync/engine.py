"""Sync engine — diffs local vs Drive, pushes/pulls changes per-collection.

Only shared collections are synced. Private collections stay local.
Each shared collection gets its own Drive folder under "Suchi Library/".
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_config
from . import gdrive

SYNC_STATE_FILE = ".sync-state.json"


def _library_dir() -> Path:
    return get_config().library_dir


def _load_sync_state(collection_dir: Path) -> dict:
    state_file = collection_dir / SYNC_STATE_FILE
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"files": {}, "last_sync": None, "drive_folder_id": None}


def _save_sync_state(collection_dir: Path, state: dict):
    state_file = collection_dir / SYNC_STATE_FILE
    state_file.write_text(json.dumps(state, indent=2))


def _file_checksum(path: Path) -> str:
    """Compute MD5 checksum of a file."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _scan_local_entries(lib_dir: Path, collection_name: str) -> dict[str, dict]:
    """Scan local entries belonging to a collection. Returns {entry_id: {files: {name: checksum}}}."""
    import yaml

    entries = {}
    for entry_dir in lib_dir.iterdir():
        if not entry_dir.is_dir() or entry_dir.name.startswith("."):
            continue
        info_file = entry_dir / "info.yaml"
        if not info_file.exists():
            continue

        try:
            info = yaml.safe_load(info_file.read_text()) or {}
        except Exception:
            continue

        collections = info.get("collections", [])
        # Check if this entry belongs to the collection (or a subcollection)
        if not any(c == collection_name or c.startswith(f"{collection_name}/") for c in collections):
            continue

        files = {}
        for f in entry_dir.iterdir():
            if f.is_file() and not f.name.startswith("."):
                files[f.name] = _file_checksum(f)

        entries[entry_dir.name] = {"files": files, "dir": str(entry_dir)}

    return entries


async def ensure_collection_on_drive(collection_name: str) -> str:
    """Ensure a collection folder exists on Drive. Returns the folder ID."""
    root_id = await gdrive.get_suchi_root_folder()
    folder_id = await gdrive.find_or_create_folder(collection_name, parent_id=root_id)
    return folder_id


async def run_sync(
    collection_name: str | None = None,
    push_only: bool = False,
    pull_only: bool = False,
    status_only: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run the sync cycle for one or all shared collections.

    Returns stats: {pushed, pulled, conflicts, errors}
    """
    from .. import collections as col_service

    lib_dir = _library_dir()
    stats = {"pushed": 0, "pulled": 0, "conflicts": 0, "errors": 0}

    # Get collections to sync
    if collection_name:
        collections_to_sync = [collection_name]
    else:
        # Find all collections that have been shared (have a drive_folder_id in sync state)
        collections_to_sync = []
        flat = col_service.get_collections_flat()
        for col in flat:
            state = _load_sync_state(lib_dir / ".sync" / col["id"])
            if state.get("drive_folder_id"):
                collections_to_sync.append(col["id"])

    for col_name in collections_to_sync:
        try:
            col_stats = await _sync_collection(
                col_name, lib_dir,
                push_only=push_only,
                pull_only=pull_only,
                status_only=status_only,
                dry_run=dry_run,
            )
            for k in ("pushed", "pulled", "conflicts", "errors"):
                stats[k] += col_stats.get(k, 0)
        except Exception:
            stats["errors"] += 1

    return stats


async def _sync_collection(
    collection_name: str,
    lib_dir: Path,
    push_only: bool = False,
    pull_only: bool = False,
    status_only: bool = False,
    dry_run: bool = False,
) -> dict:
    """Sync a single collection with Drive."""
    sync_dir = lib_dir / ".sync"
    sync_dir.mkdir(exist_ok=True)
    state_dir = sync_dir / collection_name.replace("/", "_")
    state_dir.mkdir(exist_ok=True)

    state = _load_sync_state(state_dir)

    # Ensure Drive folder exists
    folder_id = state.get("drive_folder_id")
    if not folder_id:
        folder_id = await ensure_collection_on_drive(collection_name)
        state["drive_folder_id"] = folder_id
        _save_sync_state(state_dir, state)

    stats = {"pushed": 0, "pulled": 0, "conflicts": 0, "errors": 0}

    # Scan local entries in this collection
    local_entries = _scan_local_entries(lib_dir, collection_name)

    # Scan remote entries on Drive
    remote_files = await gdrive.list_folder(folder_id)
    remote_folders = {f["name"]: f for f in remote_files if f["mimeType"] == "application/vnd.google-apps.folder"}

    last_synced = state.get("files", {})  # {entry_id: {files: {name: checksum}}}

    # ── PUSH: local → Drive ──
    if not pull_only:
        for entry_id, local_data in local_entries.items():
            prev = last_synced.get(entry_id, {}).get("files", {})
            local_files = local_data["files"]

            # Check what changed locally since last sync
            new_files = {k: v for k, v in local_files.items() if k not in prev}
            modified_files = {k: v for k, v in local_files.items() if k in prev and prev[k] != v}
            changed = {**new_files, **modified_files}

            if not changed and entry_id in last_synced:
                continue  # Nothing changed

            if status_only:
                stats["pushed"] += len(changed) or 1
                continue

            if dry_run:
                stats["pushed"] += len(changed) or 1
                continue

            # Get or create entry folder on Drive
            if entry_id in remote_folders:
                entry_folder_id = remote_folders[entry_id]["id"]
            else:
                entry_folder_id = await gdrive.find_or_create_folder(entry_id, parent_id=folder_id)

            # Upload changed files
            entry_dir = Path(local_data["dir"])
            for filename in changed:
                file_path = entry_dir / filename
                if file_path.exists():
                    await gdrive.upload_file(file_path, entry_folder_id)

            # Update sync state
            last_synced[entry_id] = {"files": local_files}
            stats["pushed"] += 1

    # ── PULL: Drive → local ──
    if not push_only:
        for folder_name, folder_meta in remote_folders.items():
            if folder_name in local_entries:
                # Entry exists locally — check for remote modifications
                # TODO: compare timestamps/checksums for conflict detection
                continue

            if folder_name.startswith("."):
                continue

            if status_only:
                stats["pulled"] += 1
                continue

            if dry_run:
                stats["pulled"] += 1
                continue

            # New entry on Drive — download it
            entry_dir = lib_dir / folder_name
            entry_dir.mkdir(exist_ok=True)

            remote_entry_files = await gdrive.list_folder(folder_meta["id"])
            for rf in remote_entry_files:
                if rf["mimeType"] != "application/vnd.google-apps.folder":
                    await gdrive.download_file(rf["id"], entry_dir / rf["name"])

            # Update sync state
            local_files = {}
            for f in entry_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    local_files[f.name] = _file_checksum(f)
            last_synced[folder_name] = {"files": local_files}
            stats["pulled"] += 1

    # Save sync state
    state["files"] = last_synced
    state["last_sync"] = datetime.now(timezone.utc).isoformat()
    _save_sync_state(state_dir, state)

    return stats
