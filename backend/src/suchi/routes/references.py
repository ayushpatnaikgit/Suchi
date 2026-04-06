"""Reference extraction and resolution routes."""

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from .. import library
from ..translators.references import extract_references as regex_extract_references
from ..translators.grobid import extract_references as grobid_extract_references, is_available as grobid_available
from ..translators.resolver import resolve_identifier
from ..translators.crossref import search_by_title as crossref_search
from ..translators.openalex import resolve_reference as openalex_resolve, search_by_title as openalex_search
from ..translators.semantic_scholar import search_by_title as s2_search, get_abstract_by_doi as s2_get_abstract

router = APIRouter(prefix="/api/references", tags=["references"])


# Bump whenever the extraction/enrichment logic changes so old caches are invalidated.
CACHE_VERSION = 2
CACHE_FILENAME = ".references-cache.json"


def _cache_path(entry_dir: Path) -> Path:
    return entry_dir / CACHE_FILENAME


def _load_cache(entry_dir: Path, pdf_path: Path) -> dict | None:
    """Load cached enriched refs if cache is valid (version matches and newer than PDF)."""
    cache_file = _cache_path(entry_dir)
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("version") != CACHE_VERSION:
        return None
    # Invalidate if PDF has been modified since cache was written
    try:
        if cache_file.stat().st_mtime < pdf_path.stat().st_mtime:
            return None
    except OSError:
        return None
    return data


def _save_cache(entry_dir: Path, refs: list[dict], source: str) -> None:
    cache_file = _cache_path(entry_dir)
    try:
        cache_file.write_text(json.dumps({
            "version": CACHE_VERSION,
            "source": source,
            "references": refs,
        }, ensure_ascii=False))
    except OSError:
        pass


class AddReferenceRequest(BaseModel):
    """Add a reference to the library, optionally to the same collections."""
    doi: str | None = None
    title: str | None = None
    collections: list[str] = []
    tags: list[str] = []


@router.get("/{entry_id}")
async def get_references(entry_id: str, refresh: bool = False):
    """Extract references from a paper's PDF.

    Uses GROBID (ML-based) when available, falls back to regex parser.
    Enriched references are cached per-entry to avoid re-hitting external APIs.
    Pass ?refresh=true to rebuild the cache.
    """
    entry = library.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")

    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        raise HTTPException(404, "Entry directory not found")

    pdfs = [f for f in entry.get("files", []) if f.endswith(".pdf")]
    if not pdfs:
        raise HTTPException(404, "No PDF attached to this entry")

    pdf_path = entry_dir / pdfs[0]

    # Return cached enriched references if available and valid
    if not refresh:
        cached = _load_cache(entry_dir, pdf_path)
        if cached:
            refs = cached.get("references", [])
            # Re-compute in_library status (library may have changed since cache was written)
            _mark_in_library(refs)
            return {
                "entry_id": entry_id,
                "count": len(refs),
                "source": cached.get("source", "cached") + "+cached",
                "references": refs,
            }

    # Try GROBID first (much better quality)
    refs = []
    source = "regex"
    if await grobid_available():
        grobid_refs = await grobid_extract_references(pdf_path)
        if grobid_refs:
            refs = grobid_refs
            source = "grobid"

    # Fall back to regex parser
    if not refs:
        refs = regex_extract_references(pdf_path)
        source = "regex"

    # Enrich references via OpenAlex (resolve titles/DOIs to full metadata)
    # Process in parallel batches for speed
    def _merge_result(ref: dict, result: dict) -> dict:
        """Merge OpenAlex result into the reference dict."""
        ref["title"] = result.get("title") or ref.get("title")
        ref["authors_raw"] = ", ".join(
            f"{a['given']} {a['family']}" for a in result.get("author", [])
        ) or ref.get("authors_raw")
        ref["year"] = result.get("date", "").split("-")[0] or ref.get("year")
        ref["doi"] = result.get("doi") or ref.get("doi")
        ref["url"] = result.get("url") or ref.get("url")
        ref["cited_by_count"] = result.get("cited_by_count", 0)
        ref["abstract"] = result.get("abstract") or ref.get("abstract")
        ref["journal"] = result.get("journal") or ref.get("journal")
        ref["tags"] = result.get("tags", []) or ref.get("tags", [])
        ref["pdf_url"] = result.get("pdf_url") or ref.get("pdf_url")
        ref["resolved"] = True
        return ref

    async def enrich_ref(ref: dict) -> dict:
        """Resolve a reference via OpenAlex → CrossRef → Semantic Scholar.

        OpenAlex is the primary source (richest metadata), but it has a strict
        daily credit limit. CrossRef has looser limits and also returns citation
        counts via is-referenced-by-count. Semantic Scholar fills in abstracts.
        """
        from ..translators.crossref import resolve_doi as crossref_resolve_doi

        try:
            resolved_ref = None

            # 1. Try OpenAlex by DOI first (richest metadata + tags)
            if ref.get("doi"):
                from ..translators.openalex import search_by_doi
                result = await search_by_doi(ref["doi"])
                if result:
                    resolved_ref = _merge_result(ref, result)

            # 2. Try OpenAlex from raw text
            if not resolved_ref:
                raw = ref.get("raw_text", "")
                if raw:
                    result = await openalex_resolve(raw)
                    if result:
                        resolved_ref = _merge_result(ref, result)

            # 3. CrossRef fallback — by DOI
            if not resolved_ref and ref.get("doi"):
                try:
                    cr_result = await crossref_resolve_doi(ref["doi"])
                    if cr_result:
                        resolved_ref = _merge_result(ref, cr_result)
                except Exception:
                    pass

            # 4. CrossRef fallback — by parsed title (works when OpenAlex circuit is open)
            if not resolved_ref and ref.get("title"):
                try:
                    cr_result = await crossref_search(ref["title"])
                    if cr_result:
                        resolved_ref = _merge_result(ref, cr_result)
                except Exception:
                    pass

            # 5. If resolved via OpenAlex but missing citation count, ask CrossRef
            if resolved_ref and resolved_ref.get("doi") and not resolved_ref.get("cited_by_count"):
                try:
                    cr_result = await crossref_resolve_doi(resolved_ref["doi"])
                    if cr_result and cr_result.get("cited_by_count"):
                        resolved_ref["cited_by_count"] = cr_result["cited_by_count"]
                except Exception:
                    pass

            # 6. If resolved but no abstract, try Semantic Scholar
            if resolved_ref and not resolved_ref.get("abstract") and resolved_ref.get("doi"):
                try:
                    s2_abstract = await s2_get_abstract(resolved_ref["doi"])
                    if s2_abstract:
                        resolved_ref["abstract"] = s2_abstract
                except Exception:
                    pass

            if resolved_ref:
                return resolved_ref

        except Exception:
            pass
        ref["resolved"] = False
        return ref

    # Resolve refs sequentially in small batches. OpenAlex is credit-rate-limited
    # (10k/day on the free polite pool) so we stay conservative.
    batch_size = 4
    enriched = []
    for i in range(0, min(len(refs), 60), batch_size):
        batch = refs[i:i + batch_size]
        results = await asyncio.gather(*[enrich_ref(r) for r in batch])
        enriched.extend(results)
    # Add remaining refs as-is (cap enrichment at 60 to bound API spend per paper)
    enriched.extend(refs[60:])
    refs = enriched

    # Persist the enriched refs to disk so future reads are instant and API-free
    _save_cache(entry_dir, refs, source)

    # Check which references are already in our library (always recompute — library state changes)
    _mark_in_library(refs)

    return {
        "entry_id": entry_id,
        "count": len(refs),
        "source": source,
        "references": refs,
    }


def _mark_in_library(refs: list[dict]) -> None:
    """Set in_library/library_id on each reference by matching against current library."""
    all_entries = library.list_entries(limit=100_000)
    existing_titles = {e.get("title", "").lower().strip(): e.get("id", "") for e in all_entries}
    existing_dois = {e.get("doi", "").lower(): e.get("id", "") for e in all_entries if e.get("doi")}

    for ref in refs:
        ref["in_library"] = False
        ref["library_id"] = None

        ref_doi = ref.get("doi") or ""
        if ref_doi and ref_doi.lower() in existing_dois:
            ref["in_library"] = True
            ref["library_id"] = existing_dois[ref_doi.lower()]
            continue

        ref_title = (ref.get("title") or "").lower().strip()
        if ref_title and ref_title in existing_titles:
            ref["in_library"] = True
            ref["library_id"] = existing_titles[ref_title]


@router.post("/add")
async def add_reference(req: AddReferenceRequest):
    """Resolve a reference and add it to the library.

    Resolution chain: DOI lookup → OpenAlex title → CrossRef title → Semantic Scholar title → raw fallback.
    """
    resolved = None

    # 1. Try DOI first (most reliable)
    if req.doi:
        resolved = await resolve_identifier(req.doi)

    # 2. Try OpenAlex title search (best coverage — 250M+ works)
    if not resolved and req.title:
        try:
            resolved = await openalex_search(req.title)
        except Exception:
            pass

    # 3. Try CrossRef title search
    if not resolved and req.title:
        try:
            resolved = await crossref_search(req.title)
        except Exception:
            pass

    # 4. Try Semantic Scholar title search
    if not resolved and req.title:
        try:
            resolved = await s2_search(req.title)
        except Exception:
            pass

    if resolved:
        resolved.pop("pdf_url", None)
        api_tags = resolved.pop("tags", []) or []
        metadata = {
            **resolved,
            "tags": list(dict.fromkeys(api_tags + req.tags)),
            "collections": req.collections,
        }
        entry = library.add_entry_manual(metadata)
        return {"ok": True, "entry": entry}

    # 5. Fallback — create with whatever we have
    if req.title:
        metadata = {
            "type": "article",
            "title": req.title,
            "author": [],
            "tags": req.tags,
            "collections": req.collections,
        }
        if req.doi:
            metadata["doi"] = req.doi
        entry = library.add_entry_manual(metadata)
        return {"ok": True, "entry": entry}

    raise HTTPException(400, "Need at least a DOI or title to add a reference")
