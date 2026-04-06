"""Hierarchical collections (folder tree) for the library.

Collections are stored in a single `collections.yaml` at the library root.
Each collection has an id, name, optional parent_id, and a color.
Entries reference collections by id in their info.yaml `collections` field.

Structure:
  - id: "thesis"
    name: "Thesis References"
    parent_id: null
    color: "#3b82f6"
    children:
      - id: "thesis/chapter-1"
        name: "Chapter 1 - Introduction"
        parent_id: "thesis"
        color: null
"""

from pathlib import Path
from datetime import datetime, timezone

import yaml

from .config import get_config


def _collections_file() -> Path:
    config = get_config()
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config.library_dir / "collections.yaml"


def _load_collections() -> list[dict]:
    f = _collections_file()
    if not f.exists():
        return []
    with open(f) as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, list) else []


def _save_collections(collections: list[dict]) -> None:
    f = _collections_file()
    with open(f, "w") as fh:
        yaml.dump(collections, fh, default_flow_style=False, allow_unicode=True, sort_keys=False)


def get_collection_tree() -> list[dict]:
    """Return collections as a nested tree structure."""
    flat = _load_collections()
    return _build_tree(flat)


def get_collections_flat() -> list[dict]:
    """Return all collections as a flat list."""
    return _load_collections()


def get_collection(collection_id: str) -> dict | None:
    """Get a single collection by id."""
    for col in _load_collections():
        if col["id"] == collection_id:
            return col
    return None


def create_collection(
    name: str,
    parent_id: str | None = None,
    color: str | None = None,
) -> dict:
    """Create a new collection. Returns the created collection."""
    collections = _load_collections()

    # Generate id from name, scoped under parent
    base_id = _slugify(name)
    if parent_id:
        # Verify parent exists
        if not any(c["id"] == parent_id for c in collections):
            raise ValueError(f"Parent collection not found: {parent_id}")
        col_id = f"{parent_id}/{base_id}"
    else:
        col_id = base_id

    # Handle id collision
    existing_ids = {c["id"] for c in collections}
    final_id = col_id
    counter = 2
    while final_id in existing_ids:
        final_id = f"{col_id}-{counter}"
        counter += 1

    collection = {
        "id": final_id,
        "name": name,
        "parent_id": parent_id,
        "color": color,
        "created": datetime.now(timezone.utc).isoformat(),
    }

    collections.append(collection)
    _save_collections(collections)
    return collection


def rename_collection(collection_id: str, new_name: str) -> dict | None:
    """Rename a collection."""
    collections = _load_collections()
    for col in collections:
        if col["id"] == collection_id:
            col["name"] = new_name
            _save_collections(collections)
            return col
    return None


def move_collection(collection_id: str, new_parent_id: str | None) -> dict | None:
    """Move a collection under a new parent (or to root if None)."""
    collections = _load_collections()

    # Prevent moving to own descendant
    if new_parent_id and _is_descendant(collections, new_parent_id, collection_id):
        raise ValueError("Cannot move a collection into its own descendant")

    for col in collections:
        if col["id"] == collection_id:
            col["parent_id"] = new_parent_id
            _save_collections(collections)
            return col
    return None


def delete_collection(collection_id: str, delete_children: bool = False) -> bool:
    """Delete a collection. If delete_children, also delete all descendants."""
    collections = _load_collections()
    original_len = len(collections)

    if delete_children:
        # Remove the collection and all descendants
        to_remove = {collection_id}
        changed = True
        while changed:
            changed = False
            for col in collections:
                if col.get("parent_id") in to_remove and col["id"] not in to_remove:
                    to_remove.add(col["id"])
                    changed = True
        collections = [c for c in collections if c["id"] not in to_remove]
    else:
        # Remove just this collection, re-parent children to this collection's parent
        target = None
        for col in collections:
            if col["id"] == collection_id:
                target = col
                break
        if not target:
            return False

        parent_of_deleted = target.get("parent_id")
        collections = [c for c in collections if c["id"] != collection_id]

        # Re-parent orphans
        for col in collections:
            if col.get("parent_id") == collection_id:
                col["parent_id"] = parent_of_deleted

    _save_collections(collections)
    return len(collections) < original_len


def get_collection_path(collection_id: str) -> list[dict]:
    """Get the full path (breadcrumbs) from root to this collection."""
    collections = _load_collections()
    col_map = {c["id"]: c for c in collections}

    path = []
    current_id = collection_id
    while current_id and current_id in col_map:
        path.insert(0, col_map[current_id])
        current_id = col_map[current_id].get("parent_id")

    return path


def _build_tree(flat: list[dict]) -> list[dict]:
    """Convert flat list to nested tree."""
    col_map = {c["id"]: {**c, "children": []} for c in flat}

    roots = []
    for col in flat:
        node = col_map[col["id"]]
        parent_id = col.get("parent_id")
        if parent_id and parent_id in col_map:
            col_map[parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots


def _is_descendant(collections: list[dict], candidate_id: str, ancestor_id: str) -> bool:
    """Check if candidate_id is a descendant of ancestor_id."""
    col_map = {c["id"]: c for c in collections}
    current = candidate_id
    while current:
        if current == ancestor_id:
            return True
        col = col_map.get(current)
        current = col.get("parent_id") if col else None
    return False


def _slugify(text: str) -> str:
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")[:40]
