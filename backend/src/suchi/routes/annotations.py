"""Annotation CRUD routes — highlights and notes on PDFs."""

import json
from pathlib import Path
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException

from .. import library

router = APIRouter(prefix="/api/entries", tags=["annotations"])

ANNOTATIONS_FILE = "annotations.json"


def _annotations_path(entry_id: str) -> Path | None:
    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        return None
    return entry_dir / ANNOTATIONS_FILE


def _load_annotations(entry_id: str) -> list[dict]:
    path = _annotations_path(entry_id)
    if not path or not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_annotations(entry_id: str, annotations: list[dict]) -> None:
    path = _annotations_path(entry_id)
    if path:
        path.write_text(json.dumps(annotations, ensure_ascii=False, indent=2))


class AnnotationCreate(BaseModel):
    id: str
    page: int
    type: str  # "highlight" or "note"
    color: str
    text: str
    rects: list[dict] = []
    created: str


class LastPageUpdate(BaseModel):
    page: int


@router.get("/{entry_id}/annotations")
def get_annotations(entry_id: str):
    """Get all annotations for an entry."""
    entry = library.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    return _load_annotations(entry_id)


@router.post("/{entry_id}/annotations")
def add_annotation(entry_id: str, annotation: AnnotationCreate):
    """Add an annotation to an entry."""
    entry = library.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")

    annotations = _load_annotations(entry_id)

    # Avoid duplicates
    if any(a.get("id") == annotation.id for a in annotations):
        return {"ok": True, "id": annotation.id}

    annotations.append(annotation.model_dump())
    _save_annotations(entry_id, annotations)
    return {"ok": True, "id": annotation.id}


@router.delete("/{entry_id}/annotations/{annotation_id}")
def delete_annotation(entry_id: str, annotation_id: str):
    """Delete an annotation."""
    annotations = _load_annotations(entry_id)
    annotations = [a for a in annotations if a.get("id") != annotation_id]
    _save_annotations(entry_id, annotations)
    return {"ok": True}


@router.put("/{entry_id}/last-page")
def update_last_page(entry_id: str, data: LastPageUpdate):
    """Save the last viewed page for an entry (for resume on next open)."""
    entry = library.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    library.update_entry(entry_id, {"last_page": data.page})
    return {"ok": True, "page": data.page}


@router.get("/{entry_id}/last-page")
def get_last_page(entry_id: str):
    """Get the last viewed page for an entry."""
    entry = library.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    return {"page": entry.get("last_page", 1)}
