"""Paper discovery routes — citing papers, related works, more by same authors."""

from fastapi import APIRouter, HTTPException

from .. import library
from ..translators.discovery import (
    get_citing_papers,
    get_referenced_papers,
    get_related_papers,
    get_author_papers,
    discover_all,
)

router = APIRouter(prefix="/api/discover", tags=["discovery"])


def _require_doi(entry_id: str) -> str:
    """Get the DOI for an entry, raising 404 if not found."""
    entry = library.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    doi = entry.get("doi")
    if not doi:
        raise HTTPException(400, f"Entry '{entry.get('title', entry_id)[:50]}' has no DOI. Discovery requires a DOI.")
    return doi


@router.get("/{entry_id}")
async def discover(entry_id: str):
    """Get all discovery results for an entry: citing, related, and same-author papers."""
    doi = _require_doi(entry_id)

    # Check which results are already in our library
    results = await discover_all(doi)

    all_entries = library.list_entries(limit=100_000)
    existing_dois = {e.get("doi", "").lower(): e.get("id", "") for e in all_entries if e.get("doi")}

    for category in ["citing", "related"]:
        for paper in results.get(category, []):
            paper_doi = (paper.get("doi") or "").lower()
            paper["in_library"] = paper_doi in existing_dois if paper_doi else False
            paper["library_id"] = existing_dois.get(paper_doi)

    for paper in results.get("author", {}).get("papers", []):
        paper_doi = (paper.get("doi") or "").lower()
        paper["in_library"] = paper_doi in existing_dois if paper_doi else False
        paper["library_id"] = existing_dois.get(paper_doi)

    return results


@router.get("/{entry_id}/citing")
async def citing_papers(entry_id: str, limit: int = 20):
    """Papers that cite this one (downstream — who built on this work?)."""
    doi = _require_doi(entry_id)
    papers = await get_citing_papers(doi, limit=limit)
    return {"count": len(papers), "papers": papers}


@router.get("/{entry_id}/references")
async def referenced_papers(entry_id: str, limit: int = 20):
    """Papers this one cites (upstream — what does it build on?)."""
    doi = _require_doi(entry_id)
    papers = await get_referenced_papers(doi, limit=limit)
    return {"count": len(papers), "papers": papers}


@router.get("/{entry_id}/related")
async def related_papers(entry_id: str, limit: int = 10):
    """Similar papers (may not cite each other directly)."""
    doi = _require_doi(entry_id)
    papers = await get_related_papers(doi, limit=limit)
    return {"count": len(papers), "papers": papers}


@router.get("/{entry_id}/by-author")
async def by_author(entry_id: str, author: str | None = None, limit: int = 20):
    """More papers by the same author(s)."""
    doi = _require_doi(entry_id)
    result = await get_author_papers(doi, author_name=author, limit=limit)
    return result
