"""Citation formatter using citeproc-py with CSL styles.

Supports 10,000+ CSL citation styles. Ships with the most common ones;
users can add more .csl files to the styles directory.

Usage:
    from suchi.citations.processor import format_citation, format_bibliography, list_styles

    # Format a single entry
    citation = format_citation(entry, style="apa")

    # Format a bibliography from multiple entries
    bib = format_bibliography(entries, style="chicago-author-date")

    # List available styles
    styles = list_styles()
"""

from pathlib import Path

from citeproc import CitationStylesStyle, CitationStylesBibliography
from citeproc import Citation, CitationItem
from citeproc.source.json import CiteProcJSON


STYLES_DIR = Path(__file__).parent / "styles"


def list_styles() -> list[dict]:
    """List available citation styles."""
    styles = []
    for f in sorted(STYLES_DIR.glob("*.csl")):
        styles.append({
            "id": f.stem,
            "name": f.stem.replace("-", " ").title(),
            "file": f.name,
        })
    return styles


def _entry_to_csl(entry: dict) -> dict:
    """Convert a Suchi entry dict to CSL-JSON format for citeproc."""
    csl = {
        "id": entry.get("id", "unknown"),
        "type": _map_to_csl_type(entry.get("type", "article")),
        "title": entry.get("title", ""),
    }

    # Authors
    authors = entry.get("author", [])
    if authors:
        csl["author"] = [
            {"family": a.get("family", ""), "given": a.get("given", "")}
            for a in authors
        ]

    # Date
    date = entry.get("date", "")
    if date:
        parts = date.split("-")
        date_parts = []
        for p in parts:
            try:
                date_parts.append(int(p))
            except ValueError:
                break
        if date_parts:
            csl["issued"] = {"date-parts": [date_parts]}

    # Other fields
    field_map = {
        "doi": "DOI",
        "isbn": "ISBN",
        "url": "URL",
        "abstract": "abstract",
        "volume": "volume",
        "issue": "issue",
        "pages": "page",
        "publisher": "publisher",
    }
    for src, dst in field_map.items():
        val = entry.get(src)
        if val:
            csl[dst] = str(val)

    if entry.get("journal"):
        csl["container-title"] = entry["journal"]

    return csl


def format_citation(entry: dict, style: str = "apa") -> str:
    """Format a single entry as an inline citation (e.g., '(Smith, 2024)')."""
    csl_data = [_entry_to_csl(entry)]
    source = CiteProcJSON(csl_data)

    style_path = STYLES_DIR / f"{style}.csl"
    if not style_path.exists():
        raise ValueError(f"Style not found: {style}. Available: {[s['id'] for s in list_styles()]}")

    bib_style = CitationStylesStyle(str(style_path), validate=False)
    bibliography = CitationStylesBibliography(bib_style, source)

    citation = Citation([CitationItem(entry.get("id", "unknown"))])
    bibliography.register(citation)

    # Get inline citation
    result = bibliography.cite(citation, lambda _: None)
    return str(result)


def format_bibliography(entries: list[dict], style: str = "apa") -> str:
    """Format multiple entries as a formatted bibliography."""
    if not entries:
        return ""

    csl_data = [_entry_to_csl(e) for e in entries]
    source = CiteProcJSON(csl_data)

    style_path = STYLES_DIR / f"{style}.csl"
    if not style_path.exists():
        raise ValueError(f"Style not found: {style}. Available: {[s['id'] for s in list_styles()]}")

    bib_style = CitationStylesStyle(str(style_path), validate=False)
    bibliography = CitationStylesBibliography(bib_style, source)

    # Register all citations
    for entry in entries:
        citation = Citation([CitationItem(entry.get("id", "unknown"))])
        bibliography.register(citation)

    # Render bibliography
    bib_items = bibliography.bibliography()
    if not bib_items:
        return ""

    lines = []
    for item in bib_items:
        text = str(item).strip()
        if text:
            lines.append(text)

    return "\n\n".join(lines)


def format_entry_full(entry: dict, style: str = "apa") -> dict:
    """Format both inline citation and bibliography entry for a single entry."""
    return {
        "citation": format_citation(entry, style),
        "bibliography": format_bibliography([entry], style),
    }


def _map_to_csl_type(entry_type: str) -> str:
    return {
        "article": "article-journal",
        "book": "book",
        "inbook": "chapter",
        "inproceedings": "paper-conference",
        "thesis": "thesis",
        "report": "report",
        "dataset": "dataset",
    }.get(entry_type, "article")
