"""Semantic Scholar API for title-based paper lookup."""

import httpx


S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_DOI_API = "https://api.semanticscholar.org/graph/v1/paper"


async def get_by_doi(doi: str) -> dict | None:
    """Look up a paper by DOI and return metadata (including abstract if available)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{S2_DOI_API}/DOI:{doi}",
            params={
                "fields": "title,authors,year,abstract,externalIds,venue,publicationDate,fieldsOfStudy,citationCount",
            },
            headers={"User-Agent": "Suchi/0.1"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return _paper_to_metadata(resp.json())


async def get_abstract_by_doi(doi: str) -> str | None:
    """Lightweight: fetch only the abstract for a given DOI."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{S2_DOI_API}/DOI:{doi}",
                params={"fields": "abstract"},
                headers={"User-Agent": "Suchi/0.1"},
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            return resp.json().get("abstract")
        except Exception:
            return None


async def search_by_title(title: str) -> dict | None:
    """Search Semantic Scholar by title and return the best match."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            S2_API,
            params={
                "query": title,
                "limit": 3,
                "fields": "title,authors,year,abstract,externalIds,venue,publicationDate,fieldsOfStudy",
            },
            headers={"User-Agent": "Suchi/0.1"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        data = resp.json().get("data", [])
        if not data:
            return None

    # Find best match
    for paper in data:
        if _titles_match(title, paper.get("title", "")):
            return _paper_to_metadata(paper)

    return None


def _paper_to_metadata(paper: dict) -> dict:
    authors = []
    for a in paper.get("authors", []):
        name = a.get("name", "")
        parts = name.rsplit(" ", 1)
        if len(parts) == 2:
            authors.append({"given": parts[0], "family": parts[1]})
        else:
            authors.append({"given": "", "family": name})

    ext_ids = paper.get("externalIds", {}) or {}
    doi = ext_ids.get("DOI")
    arxiv_id = ext_ids.get("ArXiv")

    date = paper.get("publicationDate")
    if not date and paper.get("year"):
        date = str(paper["year"])

    result = {
        "type": "article",
        "title": paper.get("title", ""),
        "author": authors,
        "date": date,
        "abstract": paper.get("abstract"),
        "journal": paper.get("venue") or None,
    }

    if doi:
        result["doi"] = doi
        result["url"] = f"https://doi.org/{doi}"
    if arxiv_id:
        result["arxiv_id"] = arxiv_id

    # Extract fields of study as tags
    tags = []
    for field in paper.get("fieldsOfStudy", []) or []:
        tags.append(field.lower())
    result["tags"] = tags

    return result


def _titles_match(query: str, candidate: str) -> bool:
    """Check if two titles are similar enough."""
    import re

    def normalize(s: str) -> set[str]:
        s = s.lower()
        s = re.sub(r"[^\w\s]", "", s)
        words = set(s.split())
        stop = {"the", "a", "an", "in", "of", "and", "for", "to", "on", "with", "by", "is", "at", "from"}
        return words - stop

    q = normalize(query)
    c = normalize(candidate)
    if not q or not c:
        return False

    overlap = len(q & c)
    return overlap / len(q) >= 0.6 and overlap / len(c) >= 0.4
