"""Find and download available PDFs for entries."""

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .. import library
from ..translators.pdf_finder import find_pdf, download_pdf

router = APIRouter(prefix="/api/pdf", tags=["pdf"])


@router.get("/find/{entry_id}")
async def find_available_pdf(entry_id: str):
    """Find available PDF sources for an entry."""
    entry = library.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")

    # Already has a PDF?
    has_pdf = any(f.endswith(".pdf") for f in entry.get("files", []))

    sources = await find_pdf(
        doi=entry.get("doi"),
        arxiv_id=entry.get("arxiv_id"),
        title=entry.get("title"),
        url=entry.get("url"),
    )

    return {
        "entry_id": entry_id,
        "has_pdf": has_pdf,
        "sources": [{"url": s.url, "source": s.source, "version": s.version} for s in sources],
    }


@router.post("/download/{entry_id}")
async def download_available_pdf(entry_id: str, source_url: str | None = None):
    """Download a PDF for an entry. If source_url not provided, uses the best available source."""
    entry = library.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")

    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        raise HTTPException(404, "Entry directory not found")

    if source_url:
        # Download from specific URL
        dest = entry_dir / "document.pdf"
        success = await download_pdf(source_url, dest)
        if not success:
            raise HTTPException(400, "Failed to download PDF from the provided URL")
        library.attach_file(entry_id, dest)
        return {"ok": True, "source": source_url}

    # Auto-find and download best available
    sources = await find_pdf(
        doi=entry.get("doi"),
        arxiv_id=entry.get("arxiv_id"),
        title=entry.get("title"),
        url=entry.get("url"),
    )

    if not sources:
        raise HTTPException(404, "No PDF sources found for this entry")

    # Try each source until one works
    dest = entry_dir / "document.pdf"
    for src in sources:
        success = await download_pdf(src.url, dest)
        if success:
            library.attach_file(entry_id, dest)
            return {"ok": True, "source": src.url, "provider": src.source, "version": src.version}

    raise HTTPException(404, "Found PDF sources but none could be downloaded")
