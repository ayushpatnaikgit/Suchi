"""Search routes — powered by Tantivy + RapidFuzz."""

from fastapi import APIRouter

from .. import library
from ..search import search as engine_search, SearchFilters, rebuild_index
from ..models import EntryResponse
from .entries import _to_response

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=list[EntryResponse])
def search(
    q: str = "",
    limit: int = 50,
    year: str | None = None,
    author: str | None = None,
    tag: str | None = None,
    collection: str | None = None,
    journal: str | None = None,
    fuzzy: bool = True,
):
    """Search with full-text + fuzzy matching + faceted filters."""
    filters = SearchFilters(
        year=year,
        author=author,
        tag=tag,
        collection=collection,
        journal=journal,
    )
    results = engine_search(q, filters=filters, limit=limit, fuzzy=fuzzy)
    return [_to_response(r) for r in results]


@router.post("/reindex")
def reindex():
    """Rebuild the search index from all entries."""
    count = rebuild_index()
    return {"indexed": count}


@router.get("/tags")
def list_tags():
    return library.get_all_tags()


@router.get("/collections")
def list_collections():
    return library.get_all_collections()
