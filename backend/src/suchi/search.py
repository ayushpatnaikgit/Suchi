"""Search engine combining Tantivy (full-text) + RapidFuzz (fuzzy) for Suchi.

Index is stored in .cache/tantivy-index/ inside the library directory.
Index is rebuildable — if deleted, it gets rebuilt on next search.

Supports:
  - Full-text search across title, abstract, authors, journal, tags
  - Fuzzy matching for typos in queries
  - Faceted filtering by year, author, tag, collection, journal
  - Ranked results with BM25 scoring
"""

import shutil
from pathlib import Path
from dataclasses import dataclass

import tantivy
from rapidfuzz import fuzz

from .config import get_config
from . import library


# ─── Index Management ───────────────────────────────────────────────

def _index_dir() -> Path:
    config = get_config()
    d = config.library_dir / ".cache" / "tantivy-index"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _build_schema() -> tantivy.Schema:
    builder = tantivy.SchemaBuilder()
    builder.add_text_field("id", stored=True)
    builder.add_text_field("title", stored=True, tokenizer_name="en_stem")
    builder.add_text_field("authors", stored=True, tokenizer_name="en_stem")
    builder.add_text_field("abstract", stored=False, tokenizer_name="en_stem")
    builder.add_text_field("journal", stored=True, tokenizer_name="en_stem")
    builder.add_text_field("tags", stored=True, tokenizer_name="default")
    builder.add_text_field("collections", stored=False, tokenizer_name="default")
    builder.add_text_field("doi", stored=True, tokenizer_name="raw")
    builder.add_text_field("year", stored=True, tokenizer_name="raw")
    builder.add_text_field("all_text", stored=False, tokenizer_name="en_stem")
    return builder.build()


_index: tantivy.Index | None = None


def get_index() -> tantivy.Index:
    """Get or create the Tantivy index."""
    global _index
    if _index is not None:
        return _index

    idx_dir = _index_dir()
    schema = _build_schema()

    try:
        _index = tantivy.Index(schema, path=str(idx_dir))
    except Exception:
        # Index corrupted or schema changed — rebuild
        shutil.rmtree(idx_dir, ignore_errors=True)
        idx_dir.mkdir(parents=True, exist_ok=True)
        _index = tantivy.Index(schema, path=str(idx_dir))

    return _index


def rebuild_index() -> int:
    """Rebuild the entire search index from all entries. Returns count indexed."""
    global _index
    _index = None

    idx_dir = _index_dir()
    shutil.rmtree(idx_dir, ignore_errors=True)
    idx_dir.mkdir(parents=True, exist_ok=True)

    index = get_index()
    writer = index.writer(heap_size=50_000_000)

    entries = library.list_entries(limit=100_000)
    count = 0

    for entry in entries:
        _add_entry_to_writer(writer, entry)
        count += 1

    writer.commit()
    index.reload()
    return count


def index_entry(entry: dict) -> None:
    """Add or update a single entry in the index."""
    index = get_index()
    writer = index.writer(heap_size=15_000_000)

    # Delete existing doc with same id
    writer.delete_documents("id", entry.get("id", ""))

    _add_entry_to_writer(writer, entry)
    writer.commit()
    index.reload()


def remove_from_index(entry_id: str) -> None:
    """Remove an entry from the index."""
    index = get_index()
    writer = index.writer(heap_size=15_000_000)
    writer.delete_documents("id", entry_id)
    writer.commit()
    index.reload()


def _add_entry_to_writer(writer, entry: dict) -> None:
    """Add an entry document to a Tantivy writer."""
    entry_id = entry.get("id", "")
    title = entry.get("title", "")
    abstract = entry.get("abstract", "") or ""

    authors = entry.get("author", [])
    author_str = " ".join(
        f"{a.get('given', '')} {a.get('family', '')}".strip()
        for a in authors
    )

    journal = entry.get("journal", "") or ""
    tags = " ".join(entry.get("tags", []))
    collections = " ".join(entry.get("collections", []))
    doi = entry.get("doi", "") or ""

    date = entry.get("date", "") or ""
    year = date.split("-")[0] if date else ""

    # Combined field for catch-all search
    all_text = f"{title} {author_str} {abstract} {journal} {tags} {doi}"

    writer.add_document(tantivy.Document(
        id=entry_id,
        title=title,
        authors=author_str,
        abstract=abstract,
        journal=journal,
        tags=tags,
        collections=collections,
        doi=doi,
        year=year,
        all_text=all_text,
    ))


# ─── Search ─────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    id: str
    score: float
    title: str = ""
    authors: str = ""
    journal: str = ""
    year: str = ""
    tags: str = ""
    match_source: str = ""  # "tantivy", "fuzzy", or "both"


@dataclass
class SearchFilters:
    year: str | None = None
    author: str | None = None
    tag: str | None = None
    collection: str | None = None
    journal: str | None = None


def search(
    query: str,
    filters: SearchFilters | None = None,
    limit: int = 50,
    fuzzy: bool = True,
) -> list[dict]:
    """Search the library using Tantivy + RapidFuzz.

    Returns full entry dicts (not just IDs), ranked by relevance.
    """
    if not query.strip() and not filters:
        return library.list_entries(limit=limit)

    # Ensure index exists
    index = get_index()
    searcher = index.searcher()

    # Check if index has documents; if not, rebuild
    if searcher.num_docs == 0:
        count = rebuild_index()
        if count > 0:
            index.reload()
            searcher = index.searcher()

    results: dict[str, SearchResult] = {}

    if query.strip():
        # 1. Tantivy full-text search
        tantivy_results = _tantivy_search(searcher, query, limit=limit * 2)
        for r in tantivy_results:
            results[r.id] = r

        # 2. RapidFuzz fuzzy search (catches typos)
        if fuzzy:
            fuzzy_results = _fuzzy_search(query, limit=limit)
            for r in fuzzy_results:
                if r.id in results:
                    results[r.id].score = max(results[r.id].score, r.score)
                    results[r.id].match_source = "both"
                else:
                    results[r.id] = r
    else:
        # No query text — start with all entries for filter-only search
        for entry in library.list_entries(limit=100_000):
            results[entry["id"]] = SearchResult(
                id=entry["id"],
                score=1.0,
                title=entry.get("title", ""),
                match_source="filter",
            )

    # 3. Apply facet filters
    if filters:
        results = _apply_filters(results, filters)

    # Sort by score, get full entries
    sorted_ids = sorted(results.values(), key=lambda r: r.score, reverse=True)
    sorted_ids = sorted_ids[:limit]

    # Fetch full entry data
    output = []
    for r in sorted_ids:
        entry = library.get_entry(r.id)
        if entry:
            entry["_search_score"] = r.score
            entry["_match_source"] = r.match_source
            output.append(entry)

    return output


def _tantivy_search(searcher, query: str, limit: int = 100) -> list[SearchResult]:
    """Run a Tantivy full-text search."""
    index = get_index()
    results = []

    # Search across all text fields
    try:
        parsed_query = index.parse_query(query, ["title", "authors", "abstract", "journal", "tags", "doi", "all_text"])
        hits = searcher.search(parsed_query, limit).hits
    except Exception:
        # If query parsing fails, try simpler approach
        try:
            parsed_query = index.parse_query(query, ["all_text"])
            hits = searcher.search(parsed_query, limit).hits
        except Exception:
            return []

    for score, doc_address in hits:
        doc = searcher.doc(doc_address)
        results.append(SearchResult(
            id=doc.get_first("id") or "",
            score=float(score),
            title=doc.get_first("title") or "",
            authors=doc.get_first("authors") or "",
            journal=doc.get_first("journal") or "",
            year=doc.get_first("year") or "",
            tags=doc.get_first("tags") or "",
            match_source="tantivy",
        ))

    return results


def _fuzzy_search(query: str, limit: int = 50) -> list[SearchResult]:
    """Fuzzy search using RapidFuzz — catches typos in author names and titles."""
    entries = library.list_entries(limit=100_000)
    results = []

    for entry in entries:
        # Build searchable text for this entry
        title = entry.get("title", "")
        authors = " ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in entry.get("author", [])
        )
        tags = " ".join(entry.get("tags", []))
        journal = entry.get("journal", "") or ""

        # Compute fuzzy scores against different fields
        title_score = fuzz.partial_ratio(query.lower(), title.lower())
        author_score = fuzz.partial_ratio(query.lower(), authors.lower())
        tag_score = fuzz.token_set_ratio(query.lower(), tags.lower()) if tags else 0
        journal_score = fuzz.partial_ratio(query.lower(), journal.lower()) if journal else 0

        # Weighted combination
        best_score = max(
            title_score * 1.0,
            author_score * 0.9,
            tag_score * 0.7,
            journal_score * 0.6,
        )

        # Only include if score is reasonably high (above typo threshold)
        if best_score >= 65:
            results.append(SearchResult(
                id=entry.get("id", ""),
                score=best_score / 100.0 * 5.0,  # Normalize to roughly match Tantivy scores
                title=title,
                authors=authors,
                journal=journal,
                year=(entry.get("date", "") or "").split("-")[0],
                tags=tags,
                match_source="fuzzy",
            ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:limit]


def _apply_filters(
    results: dict[str, SearchResult],
    filters: SearchFilters,
) -> dict[str, SearchResult]:
    """Apply facet filters to search results."""
    if not any([filters.year, filters.author, filters.tag, filters.collection, filters.journal]):
        return results

    filtered = {}
    for entry_id, result in results.items():
        entry = library.get_entry(entry_id)
        if not entry:
            continue

        if filters.year:
            date = entry.get("date", "") or ""
            if not date.startswith(filters.year):
                continue

        if filters.author:
            authors = entry.get("author", [])
            author_names = [
                f"{a.get('given', '')} {a.get('family', '')}".strip().lower()
                for a in authors
            ]
            if not any(filters.author.lower() in name for name in author_names):
                continue

        if filters.tag:
            if filters.tag not in entry.get("tags", []):
                continue

        if filters.collection:
            if filters.collection not in entry.get("collections", []):
                continue

        if filters.journal:
            journal = (entry.get("journal", "") or "").lower()
            if filters.journal.lower() not in journal:
                continue

        filtered[entry_id] = result

    return filtered
