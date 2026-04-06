"""Entry CRUD routes."""

import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File

from .. import library
from ..models import EntryCreate, EntryResponse, AddByIdentifier
from ..translators.pdf_extract import (
    extract_metadata_from_pdf,
    parse_raw_authors,
)
from ..translators.resolver import resolve_identifier
from ..translators.crossref import search_by_title as crossref_title_search
from ..translators.semantic_scholar import search_by_title as s2_title_search
from ..translators.grobid import extract_header as grobid_extract_header, is_available as grobid_available

# Patterns to filter out from tags
_JEL_PATTERN = re.compile(r"^JEL:\s*[A-Z]\d", re.IGNORECASE)
_JUNK_TAG_PATTERNS = [
    _JEL_PATTERN,
    re.compile(r"^\d+$"),                    # Pure numbers
    re.compile(r"^[A-Z]\d{1,2}$"),           # Single JEL codes like "H2", "Q4"
    re.compile(r"^(?:JEL|MSC|PACS)\b", re.IGNORECASE),  # Classification prefixes
]


def _filter_tags(tags: list[str]) -> list[str]:
    """Filter out JEL codes, classification numbers, and other non-useful tags."""
    filtered = []
    for tag in tags:
        tag = tag.strip()
        if not tag or len(tag) < 2:
            continue
        # Skip any tag matching junk patterns
        if any(p.match(tag) for p in _JUNK_TAG_PATTERNS):
            continue
        filtered.append(tag)
    return filtered

router = APIRouter(prefix="/api/entries", tags=["entries"])


def _to_response(entry: dict) -> EntryResponse:
    authors = entry.get("author", [])
    return EntryResponse(
        id=entry.get("id", ""),
        type=entry.get("type", "article"),
        title=entry.get("title", ""),
        author=[{"family": a.get("family", ""), "given": a.get("given", "")} for a in authors],
        doi=entry.get("doi"),
        isbn=entry.get("isbn"),
        date=entry.get("date"),
        journal=entry.get("journal"),
        volume=entry.get("volume"),
        issue=entry.get("issue"),
        pages=entry.get("pages"),
        publisher=entry.get("publisher"),
        abstract=entry.get("abstract"),
        tags=entry.get("tags", []),
        collections=entry.get("collections", []),
        url=entry.get("url"),
        files=entry.get("files", []),
        added=entry.get("added"),
        modified=entry.get("modified"),
    )


@router.get("", response_model=list[EntryResponse])
def list_entries(
    tag: str | None = None,
    collection: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    entries = library.list_entries(tag=tag, collection=collection, limit=limit, offset=offset)
    return [_to_response(e) for e in entries]


@router.get("/{entry_id}", response_model=EntryResponse)
def get_entry(entry_id: str):
    entry = library.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    return _to_response(entry)


@router.post("", response_model=EntryResponse)
def create_entry_manual(data: EntryCreate):
    metadata = data.model_dump(exclude_none=True)
    metadata["author"] = [a.model_dump() for a in data.author]
    entry = library.add_entry_manual(metadata)
    return _to_response(entry)


@router.post("/resolve", response_model=EntryResponse)
async def add_by_identifier(data: AddByIdentifier):
    entry = await library.add_entry_by_identifier(
        data.identifier,
        tags=data.tags or None,
        collections=data.collections or None,
    )
    if not entry:
        raise HTTPException(400, f"Could not resolve identifier: {data.identifier}")
    return _to_response(entry)


@router.put("/{entry_id}", response_model=EntryResponse)
def update_entry(entry_id: str, updates: dict):
    entry = library.update_entry(entry_id, updates)
    if not entry:
        raise HTTPException(404, "Entry not found")
    return _to_response(entry)


@router.delete("/{entry_id}")
def delete_entry(entry_id: str):
    if not library.delete_entry(entry_id):
        raise HTTPException(404, "Entry not found")
    return {"ok": True}


@router.post("/{entry_id}/tags")
def add_tags(entry_id: str, tags: list[str]):
    entry = library.add_tags(entry_id, tags)
    if not entry:
        raise HTTPException(404, "Entry not found")
    return _to_response(entry)


@router.delete("/{entry_id}/tags")
def remove_tags(entry_id: str, tags: list[str]):
    entry = library.remove_tags(entry_id, tags)
    if not entry:
        raise HTTPException(404, "Entry not found")
    return _to_response(entry)


@router.get("/{entry_id}/pdf")
def serve_pdf(entry_id: str, filename: str = "document.pdf"):
    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        raise HTTPException(404, "Entry not found")

    pdf_path = entry_dir / filename
    if not pdf_path.exists():
        raise HTTPException(404, f"File not found: {filename}")

    from fastapi.responses import FileResponse
    return FileResponse(pdf_path, media_type="application/pdf")


@router.post("/{entry_id}/attach")
async def attach_file(entry_id: str, file: UploadFile = File(...)):
    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        raise HTTPException(404, "Entry not found")

    # Save uploaded file
    dest = entry_dir / file.filename
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)

    entry = library.attach_file(entry_id, dest)
    return _to_response(entry)


@router.post("/upload-pdf", response_model=EntryResponse)
async def upload_pdf(file: UploadFile = File(...)):
    """Upload a PDF, extract metadata (DOI/arXiv/title), resolve via APIs, and create an entry."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # Strategy: GROBID (ML) → regex + API resolution → raw PDF metadata
        resolved = None
        pdf_meta = {}
        grobid_meta = None

        # Step 1: Try GROBID for ML-based extraction (best quality)
        if await grobid_available():
            grobid_meta = await grobid_extract_header(tmp_path)

        # Step 2: Also run regex extraction for DOI/arXiv identifiers
        pdf_meta = extract_metadata_from_pdf(tmp_path)

        # Step 3: Use best available DOI to resolve full metadata from CrossRef
        doi = (grobid_meta or {}).get("doi") or pdf_meta.get("doi")
        arxiv_id = pdf_meta.get("arxiv_id")

        if doi:
            resolved = await resolve_identifier(doi)
        if not resolved and arxiv_id:
            resolved = await resolve_identifier(arxiv_id)

        # Step 4: Title-based search if no identifier found
        title = (grobid_meta or {}).get("title") or pdf_meta.get("title")
        if not resolved and title:
            resolved = await crossref_title_search(title)
        if not resolved and title:
            try:
                resolved = await s2_title_search(title)
            except Exception:
                pass

        # Build final metadata from best source
        if resolved:
            resolved.pop("pdf_url", None)
            api_tags = resolved.pop("tags", []) or []
            pdf_keywords = pdf_meta.get("keywords", [])
            grobid_keywords = (grobid_meta or {}).get("tags", [])
            all_tags = _filter_tags(list(dict.fromkeys(api_tags + grobid_keywords + pdf_keywords)))
            metadata = {
                **resolved,
                "tags": all_tags,
                "collections": [],
            }
        elif grobid_meta:
            # GROBID gave us structured data but we couldn't resolve via API
            metadata = {
                "type": grobid_meta.get("type", "article"),
                "title": grobid_meta.get("title", ""),
                "author": grobid_meta.get("author", []),
                "abstract": grobid_meta.get("abstract", ""),
                "doi": grobid_meta.get("doi"),
                "date": grobid_meta.get("date"),
                "journal": grobid_meta.get("journal"),
                "volume": grobid_meta.get("volume"),
                "issue": grobid_meta.get("issue"),
                "pages": grobid_meta.get("pages"),
                "publisher": grobid_meta.get("publisher"),
                "tags": _filter_tags(grobid_meta.get("tags", []) + pdf_meta.get("keywords", [])),
                "collections": [],
            }
        else:
            # Pure regex fallback
            metadata = {
                "type": "article",
                "title": pdf_meta.get("title") or file.filename.replace(".pdf", ""),
                "author": [],
                "tags": _filter_tags(pdf_meta.get("keywords", [])),
                "collections": [],
            }
            if pdf_meta.get("raw_author"):
                metadata["author"] = parse_raw_authors(pdf_meta["raw_author"])
            if pdf_meta.get("doi"):
                metadata["doi"] = pdf_meta["doi"]
            if pdf_meta.get("date"):
                metadata["date"] = pdf_meta["date"]
            if pdf_meta.get("abstract"):
                metadata["abstract"] = pdf_meta["abstract"]

        # Remove None values
        metadata = {k: v for k, v in metadata.items() if v is not None}

        entry = library.add_entry_manual(metadata)
        renamed = tmp_path.parent / "document.pdf"
        tmp_path.rename(renamed)
        tmp_path = renamed
        entry = library.attach_file(entry["id"], tmp_path)
        return _to_response(entry)

    finally:
        # Clean up temp file (it's been copied into the entry dir)
        try:
            tmp_path.unlink()
        except OSError:
            pass
