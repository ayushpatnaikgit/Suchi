"""Collection (folder) CRUD routes.

Collection IDs contain slashes (e.g. "thesis/chapter-1/key-papers"),
so we use query params instead of path params for IDs.
"""

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query

from .. import collections as col_service
from .. import library

router = APIRouter(prefix="/api/collections", tags=["collections"])


class CollectionCreate(BaseModel):
    name: str
    parent_id: str | None = None
    color: str | None = None


class CollectionUpdate(BaseModel):
    id: str
    name: str | None = None
    parent_id: str | None = "__unchanged__"  # sentinel


class AddEntryToCollection(BaseModel):
    collection_id: str
    entry_id: str


class RemoveEntryFromCollection(BaseModel):
    collection_id: str
    entry_id: str


@router.get("/tree")
def get_tree():
    """Get collections as a nested tree."""
    return col_service.get_collection_tree()


@router.get("/flat")
def list_flat():
    """Get all collections as a flat list."""
    return col_service.get_collections_flat()


@router.get("/get")
def get_collection(id: str = Query(...)):
    col = col_service.get_collection(id)
    if not col:
        raise HTTPException(404, "Collection not found")
    return col


@router.get("/path")
def get_path(id: str = Query(...)):
    """Get breadcrumb path for a collection."""
    return col_service.get_collection_path(id)


@router.get("/entries")
def get_entries(id: str = Query(...)):
    """Get all entries in a collection (including subcollections)."""
    flat = col_service.get_collections_flat()
    descendant_ids = _get_descendant_ids(flat, id)
    descendant_ids.add(id)

    entries = library.list_entries(limit=10000)
    return [
        e for e in entries
        if any(c in descendant_ids for c in e.get("collections", []))
    ]


@router.post("/create")
def create(data: CollectionCreate):
    try:
        return col_service.create_collection(
            name=data.name,
            parent_id=data.parent_id,
            color=data.color,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/update")
def update(data: CollectionUpdate):
    """Rename and/or move a collection."""
    if data.name is not None:
        result = col_service.rename_collection(data.id, data.name)
        if not result:
            raise HTTPException(404, "Collection not found")

    if data.parent_id != "__unchanged__":
        try:
            result = col_service.move_collection(data.id, data.parent_id)
            if not result:
                raise HTTPException(404, "Collection not found")
        except ValueError as e:
            raise HTTPException(400, str(e))

    col = col_service.get_collection(data.id)
    return col


@router.delete("/delete")
def delete(id: str = Query(...), delete_children: bool = False):
    if not col_service.delete_collection(id, delete_children):
        raise HTTPException(404, "Collection not found")
    return {"ok": True}


@router.post("/add-entry")
def add_entry(data: AddEntryToCollection):
    """Add an entry to a collection."""
    col = col_service.get_collection(data.collection_id)
    if not col:
        raise HTTPException(404, "Collection not found")

    entry = library.get_entry(data.entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")

    current_collections = entry.get("collections", [])
    if data.collection_id not in current_collections:
        current_collections.append(data.collection_id)
        library.update_entry(data.entry_id, {"collections": current_collections})

    return {"ok": True}


@router.post("/remove-entry")
def remove_entry(data: RemoveEntryFromCollection):
    """Remove an entry from a collection."""
    entry = library.get_entry(data.entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")

    current_collections = entry.get("collections", [])
    if data.collection_id in current_collections:
        current_collections.remove(data.collection_id)
        library.update_entry(data.entry_id, {"collections": current_collections})

    return {"ok": True}


def _get_descendant_ids(flat: list[dict], parent_id: str) -> set[str]:
    """Get all descendant collection ids."""
    descendants = set()
    queue = [parent_id]
    while queue:
        current = queue.pop()
        for col in flat:
            if col.get("parent_id") == current and col["id"] not in descendants:
                descendants.add(col["id"])
                queue.append(col["id"])
    return descendants
