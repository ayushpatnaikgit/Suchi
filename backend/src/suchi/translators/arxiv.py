"""arXiv API translator for arXiv ID resolution."""

import re
import httpx
from xml.etree import ElementTree as ET


ARXIV_API = "http://export.arxiv.org/api/query"
ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"

# Matches: 2301.12345, arxiv:2301.12345, https://arxiv.org/abs/2301.12345
ARXIV_PATTERN = re.compile(
    r"(?:arxiv:?|https?://arxiv\.org/(?:abs|pdf)/)?([\d]{4}\.[\d]{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)


def extract_arxiv_id(identifier: str) -> str | None:
    match = ARXIV_PATTERN.search(identifier)
    return match.group(1) if match else None


async def resolve_arxiv(arxiv_id: str) -> dict | None:
    """Resolve an arXiv ID to bibliographic metadata."""
    arxiv_id = extract_arxiv_id(arxiv_id) or arxiv_id

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(
            ARXIV_API,
            params={"id_list": arxiv_id},
            timeout=15,
        )
        if resp.status_code != 200:
            return None

    root = ET.fromstring(resp.text)
    entries = root.findall(f"{{{ATOM_NS}}}entry")
    if not entries:
        return None

    entry = entries[0]

    title = _text(entry, f"{{{ATOM_NS}}}title", "").replace("\n", " ").strip()
    abstract = _text(entry, f"{{{ATOM_NS}}}summary", "").strip()
    published = _text(entry, f"{{{ATOM_NS}}}published", "")

    authors = []
    for author_el in entry.findall(f"{{{ATOM_NS}}}author"):
        name = _text(author_el, f"{{{ATOM_NS}}}name", "")
        parts = name.rsplit(" ", 1)
        if len(parts) == 2:
            authors.append({"given": parts[0], "family": parts[1]})
        else:
            authors.append({"given": "", "family": name})

    doi_el = entry.find(f"{{{ARXIV_NS}}}doi")
    doi = doi_el.text.strip() if doi_el is not None and doi_el.text else None

    # Get PDF link
    pdf_url = None
    for link in entry.findall(f"{{{ATOM_NS}}}link"):
        if link.get("title") == "pdf":
            pdf_url = link.get("href")
            break

    date = published[:10] if published else None

    # Extract arXiv categories as tags
    tags = []
    for cat_el in entry.findall(f"{{{ATOM_NS}}}category"):
        term = cat_el.get("term", "")
        scheme = cat_el.get("scheme", "")
        if term and "arxiv" in scheme.lower():
            tags.append(term)
    # Also check primary category
    primary = entry.find(f"{{{ARXIV_NS}}}primary_category")
    if primary is not None:
        pterm = primary.get("term", "")
        if pterm and pterm not in tags:
            tags.insert(0, pterm)

    return {
        "type": "article",
        "title": title,
        "author": authors,
        "doi": doi,
        "date": date,
        "abstract": abstract,
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "arxiv_id": arxiv_id,
        "pdf_url": pdf_url,
        "tags": tags,
    }


def _text(el: ET.Element, tag: str, default: str) -> str:
    child = el.find(tag)
    return child.text if child is not None and child.text else default
