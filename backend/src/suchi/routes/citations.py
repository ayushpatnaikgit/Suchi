"""Citation formatting routes."""

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from .. import library
from ..citations.processor import format_bibliography, format_entry_full, list_styles

router = APIRouter(prefix="/api/cite", tags=["citations"])


class CiteRequest(BaseModel):
    entry_ids: list[str]
    style: str = "apa"


@router.get("/styles")
def get_styles():
    """List available citation styles."""
    return list_styles()


@router.post("")
def cite(req: CiteRequest):
    """Format citations for one or more entries."""
    entries = []
    for eid in req.entry_ids:
        entry = library.get_entry(eid)
        if not entry:
            raise HTTPException(404, f"Entry not found: {eid}")
        entries.append(entry)

    results = []
    for entry in entries:
        try:
            formatted = format_entry_full(entry, req.style)
            results.append({
                "id": entry["id"],
                "citation": formatted["citation"],
                "bibliography": formatted["bibliography"],
            })
        except ValueError as e:
            raise HTTPException(400, str(e))

    return results


@router.post("/bibliography")
def bibliography(req: CiteRequest):
    """Generate a formatted bibliography for multiple entries."""
    entries = []
    for eid in req.entry_ids:
        entry = library.get_entry(eid)
        if not entry:
            raise HTTPException(404, f"Entry not found: {eid}")
        entries.append(entry)

    try:
        bib = format_bibliography(entries, req.style)
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {"bibliography": bib, "style": req.style, "count": len(entries)}
