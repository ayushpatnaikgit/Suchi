"""Library engine — manages entries on disk using directory-per-entry with YAML metadata."""

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx
import yaml

# Callbacks for search index updates (set by search module to avoid circular imports)
_on_entry_added: Callable[[dict], None] | None = None
_on_entry_removed: Callable[[str], None] | None = None


def set_index_hooks(
    on_added: Callable[[dict], None],
    on_removed: Callable[[str], None],
) -> None:
    global _on_entry_added, _on_entry_removed
    _on_entry_added = on_added
    _on_entry_removed = on_removed

from .config import get_config
from .translators import resolve_identifier


def _library_dir() -> Path:
    config = get_config()
    config.library_dir.mkdir(parents=True, exist_ok=True)
    return config.library_dir


def _slugify(text: str, max_len: int = 60) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len]


def _make_entry_id(metadata: dict) -> str:
    """Generate a unique directory name from metadata."""
    parts = []

    authors = metadata.get("author", [])
    if authors:
        parts.append(authors[0].get("family", "unknown").lower())

    date = metadata.get("date", "")
    if date:
        year = date.split("-")[0]
        parts.append(year)

    title = metadata.get("title", "untitled")
    title_slug = _slugify(title, max_len=40)
    parts.append(title_slug)

    base_id = "-".join(parts)
    entry_dir = _library_dir() / base_id

    # Handle collisions
    if entry_dir.exists():
        i = 2
        while (_library_dir() / f"{base_id}-{i}").exists():
            i += 1
        base_id = f"{base_id}-{i}"

    return base_id


def _read_info(entry_dir: Path) -> dict:
    info_file = entry_dir / "info.yaml"
    if not info_file.exists():
        return {}
    with open(info_file) as f:
        return yaml.safe_load(f) or {}


def _write_info(entry_dir: Path, metadata: dict) -> None:
    entry_dir.mkdir(parents=True, exist_ok=True)
    with open(entry_dir / "info.yaml", "w") as f:
        yaml.dump(metadata, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def list_entries(
    tag: str | None = None,
    collection: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """List all entries, optionally filtered by tag or collection."""
    lib = _library_dir()
    entries = []

    for entry_dir in sorted(lib.iterdir()):
        if not entry_dir.is_dir() or entry_dir.name.startswith("."):
            continue

        info = _read_info(entry_dir)
        if not info:
            continue

        if tag and tag not in info.get("tags", []):
            continue
        if collection and collection not in info.get("collections", []):
            continue

        info["id"] = entry_dir.name
        info["files"] = [
            f.name for f in entry_dir.iterdir()
            if f.is_file() and f.name != "info.yaml" and f.name != "notes.md" and not f.name.startswith(".")
        ]
        entries.append(info)

    return entries[offset : offset + limit]


def get_entry(entry_id: str) -> dict | None:
    """Get a single entry by its directory name."""
    entry_dir = _library_dir() / entry_id
    if not entry_dir.is_dir():
        return None
    info = _read_info(entry_dir)
    if not info:
        return None
    info["id"] = entry_id
    info["files"] = [
        f.name for f in entry_dir.iterdir()
        if f.is_file() and f.name != "info.yaml" and f.name != "notes.md" and not f.name.startswith(".")
    ]
    return info


def get_entry_dir(entry_id: str) -> Path | None:
    """Get the path to an entry's directory."""
    entry_dir = _library_dir() / entry_id
    return entry_dir if entry_dir.is_dir() else None


async def add_entry_by_identifier(
    identifier: str,
    tags: list[str] | None = None,
    collections: list[str] | None = None,
    download_pdf: bool = True,
) -> dict | None:
    """Add an entry by resolving a DOI, ISBN, arXiv ID, or URL."""
    metadata = await resolve_identifier(identifier)
    if not metadata:
        return None

    # If CrossRef/arXiv didn't return an abstract, try Semantic Scholar
    if not metadata.get("abstract") and metadata.get("doi"):
        try:
            from .translators.semantic_scholar import get_abstract_by_doi
            abstract = await get_abstract_by_doi(metadata["doi"])
            if abstract:
                metadata["abstract"] = abstract
        except Exception:
            pass

    now = datetime.now(timezone.utc).isoformat()
    metadata["added"] = now
    metadata["modified"] = now
    # Merge API-provided tags with user-provided tags
    api_tags = metadata.get("tags", []) or []
    user_tags = tags or []
    metadata["tags"] = list(dict.fromkeys(api_tags + user_tags))
    if collections:
        metadata["collections"] = collections

    entry_id = _make_entry_id(metadata)
    entry_dir = _library_dir() / entry_id
    entry_dir.mkdir(parents=True, exist_ok=True)

    # Download PDF if available
    pdf_url = metadata.pop("pdf_url", None)
    if download_pdf and pdf_url:
        try:
            await _download_pdf(pdf_url, entry_dir / "document.pdf")
            metadata.setdefault("files", [])
            if "document.pdf" not in metadata.get("files", []):
                metadata.setdefault("files", []).append("document.pdf")
        except Exception:
            pass  # Non-fatal: entry still created without PDF

    _write_info(entry_dir, metadata)
    metadata["id"] = entry_id
    return metadata


def add_entry_manual(metadata: dict) -> dict:
    """Add an entry with manually provided metadata."""
    now = datetime.now(timezone.utc).isoformat()
    metadata["added"] = now
    metadata["modified"] = now

    entry_id = _make_entry_id(metadata)
    entry_dir = _library_dir() / entry_id
    _write_info(entry_dir, metadata)

    metadata["id"] = entry_id
    metadata["files"] = []
    if _on_entry_added:
        try:
            _on_entry_added(metadata)
        except Exception:
            pass
    return metadata


def update_entry(entry_id: str, updates: dict) -> dict | None:
    """Update an entry's metadata."""
    entry_dir = _library_dir() / entry_id
    if not entry_dir.is_dir():
        return None

    info = _read_info(entry_dir)
    info.update(updates)
    info["modified"] = datetime.now(timezone.utc).isoformat()
    _write_info(entry_dir, info)

    info["id"] = entry_id
    if _on_entry_added:
        try:
            _on_entry_added(info)
        except Exception:
            pass
    return info


def delete_entry(entry_id: str) -> bool:
    """Delete an entry and all its files."""
    entry_dir = _library_dir() / entry_id
    if not entry_dir.is_dir():
        return False
    shutil.rmtree(entry_dir)
    if _on_entry_removed:
        try:
            _on_entry_removed(entry_id)
        except Exception:
            pass
    return True


def add_tags(entry_id: str, tags: list[str]) -> dict | None:
    """Add tags to an entry."""
    entry_dir = _library_dir() / entry_id
    if not entry_dir.is_dir():
        return None

    info = _read_info(entry_dir)
    existing = set(info.get("tags", []))
    existing.update(tags)
    info["tags"] = sorted(existing)
    info["modified"] = datetime.now(timezone.utc).isoformat()
    _write_info(entry_dir, info)

    info["id"] = entry_id
    return info


def remove_tags(entry_id: str, tags: list[str]) -> dict | None:
    """Remove tags from an entry."""
    entry_dir = _library_dir() / entry_id
    if not entry_dir.is_dir():
        return None

    info = _read_info(entry_dir)
    existing = set(info.get("tags", []))
    existing -= set(tags)
    info["tags"] = sorted(existing)
    info["modified"] = datetime.now(timezone.utc).isoformat()
    _write_info(entry_dir, info)

    info["id"] = entry_id
    return info


def search_entries(query: str, limit: int = 50) -> list[dict]:
    """Search entries by title, author, tags, or abstract."""
    query_lower = query.lower()
    results = []

    for entry in list_entries(limit=10000):
        score = 0
        title = entry.get("title", "").lower()
        if query_lower in title:
            score += 10

        for author in entry.get("author", []):
            name = f"{author.get('given', '')} {author.get('family', '')}".lower()
            if query_lower in name:
                score += 5

        for tag in entry.get("tags", []):
            if query_lower in tag.lower():
                score += 3

        abstract = entry.get("abstract", "") or ""
        if query_lower in abstract.lower():
            score += 2

        doi = entry.get("doi", "") or ""
        if query_lower == doi.lower():
            score += 20

        if score > 0:
            entry["_score"] = score
            results.append(entry)

    results.sort(key=lambda x: x.pop("_score", 0), reverse=True)
    return results[:limit]


def export_entries(entry_ids: list[str] | None = None, fmt: str = "bibtex") -> str:
    """Export entries in the specified format."""
    if entry_ids:
        entries = [get_entry(eid) for eid in entry_ids]
        entries = [e for e in entries if e]
    else:
        entries = list_entries(limit=10000)

    if fmt == "bibtex":
        return _export_bibtex(entries)
    elif fmt == "csl-json":
        return _export_csl_json(entries)
    elif fmt == "ris":
        return _export_ris(entries)
    else:
        raise ValueError(f"Unknown export format: {fmt}")


def _export_bibtex(entries: list[dict]) -> str:
    lines = []
    for entry in entries:
        entry_type = entry.get("type", "article")
        entry_id = entry.get("id", "unknown")

        # Map to BibTeX types
        bibtex_type = {
            "article": "article",
            "book": "book",
            "inbook": "inbook",
            "inproceedings": "inproceedings",
            "thesis": "phdthesis",
            "report": "techreport",
        }.get(entry_type, "misc")

        lines.append(f"@{bibtex_type}{{{entry_id},")

        if entry.get("title"):
            lines.append(f"  title = {{{entry['title']}}},")

        authors = entry.get("author", [])
        if authors:
            author_strs = [
                f"{a.get('family', '')}{',' if a.get('given') else ''} {a.get('given', '')}".strip()
                for a in authors
            ]
            lines.append(f"  author = {{{' and '.join(author_strs)}}},")

        for field in ["journal", "volume", "issue", "pages", "publisher", "doi", "isbn", "url"]:
            val = entry.get(field)
            if val:
                bibtex_field = "number" if field == "issue" else field
                lines.append(f"  {bibtex_field} = {{{val}}},")

        date = entry.get("date", "")
        if date:
            lines.append(f"  year = {{{date.split('-')[0]}}},")

        if entry.get("abstract"):
            lines.append(f"  abstract = {{{entry['abstract']}}},")

        lines.append("}")
        lines.append("")

    return "\n".join(lines)


def _export_csl_json(entries: list[dict]) -> str:
    import json

    csl_items = []
    for entry in entries:
        item = {
            "id": entry.get("id", ""),
            "type": _to_csl_type(entry.get("type", "article")),
            "title": entry.get("title", ""),
        }

        authors = entry.get("author", [])
        if authors:
            item["author"] = [
                {"family": a.get("family", ""), "given": a.get("given", "")}
                for a in authors
            ]

        date = entry.get("date", "")
        if date:
            parts = date.split("-")
            item["issued"] = {"date-parts": [[int(p) for p in parts if p]]}

        for field in ["DOI", "ISBN", "URL", "abstract", "volume", "issue", "page", "publisher"]:
            src_field = field.lower()
            if src_field == "page":
                src_field = "pages"
            val = entry.get(src_field)
            if val:
                item[field] = val

        if entry.get("journal"):
            item["container-title"] = entry["journal"]

        csl_items.append(item)

    return json.dumps(csl_items, indent=2)


def _export_ris(entries: list[dict]) -> str:
    lines = []
    for entry in entries:
        ris_type = {
            "article": "JOUR",
            "book": "BOOK",
            "inbook": "CHAP",
            "inproceedings": "CPAPER",
            "thesis": "THES",
            "report": "RPRT",
        }.get(entry.get("type", "article"), "GEN")

        lines.append(f"TY  - {ris_type}")
        if entry.get("title"):
            lines.append(f"TI  - {entry['title']}")

        for author in entry.get("author", []):
            name = f"{author.get('family', '')}, {author.get('given', '')}".strip(", ")
            lines.append(f"AU  - {name}")

        date = entry.get("date", "")
        if date:
            lines.append(f"PY  - {date.split('-')[0]}")
            lines.append(f"DA  - {date}")

        field_map = {
            "journal": "JO", "volume": "VL", "issue": "IS",
            "pages": "SP", "publisher": "PB", "doi": "DO",
            "isbn": "SN", "url": "UR", "abstract": "AB",
        }
        for src, tag in field_map.items():
            val = entry.get(src)
            if val:
                lines.append(f"{tag}  - {val}")

        lines.append("ER  - ")
        lines.append("")

    return "\n".join(lines)


def _to_csl_type(entry_type: str) -> str:
    return {
        "article": "article-journal",
        "book": "book",
        "inbook": "chapter",
        "inproceedings": "paper-conference",
        "thesis": "thesis",
        "report": "report",
    }.get(entry_type, "article")


async def _download_pdf(url: str, dest: Path) -> None:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url, timeout=60)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)


def attach_file(entry_id: str, file_path: Path) -> dict | None:
    """Copy a file into an entry's directory."""
    entry_dir = _library_dir() / entry_id
    if not entry_dir.is_dir():
        return None

    dest = entry_dir / file_path.name
    # Skip copy if file is already in the entry directory
    if file_path.resolve() != dest.resolve():
        shutil.copy2(file_path, dest)

    info = _read_info(entry_dir)
    files = info.get("files", [])
    if file_path.name not in files:
        files.append(file_path.name)
        info["files"] = files
        info["modified"] = datetime.now(timezone.utc).isoformat()
        _write_info(entry_dir, info)

    info["id"] = entry_id
    return info


def get_all_tags() -> list[str]:
    """Get all unique tags across all entries."""
    tags = set()
    for entry in list_entries(limit=10000):
        tags.update(entry.get("tags", []))
    return sorted(tags)


def get_all_collections() -> list[str]:
    """Get all unique collections across all entries."""
    collections = set()
    for entry in list_entries(limit=10000):
        collections.update(entry.get("collections", []))
    return sorted(collections)
