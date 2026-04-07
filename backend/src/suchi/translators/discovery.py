"""Paper discovery — find citing papers, related works, and more by same authors.

Uses Semantic Scholar API (free, 100 req/5min without key, 1000 with key).
"""

import httpx
from typing import Optional


S2_API = "https://api.semanticscholar.org/graph/v1"
S2_RECO = "https://api.semanticscholar.org/recommendations/v1"
PAPER_FIELDS = "title,year,citationCount,authors,externalIds,abstract,venue,url"
AUTHOR_FIELDS = "name,paperCount,citationCount,hIndex"


async def _s2_get(url: str, params: dict | None = None) -> dict | None:
    """Make a Semantic Scholar API request with error handling."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                url,
                params=params or {},
                headers={"User-Agent": "Suchi/0.1 (research reference manager)"},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except (httpx.TimeoutException, httpx.HTTPError):
            return None


def _format_paper(paper: dict) -> dict:
    """Format a Semantic Scholar paper into our standard format."""
    authors = []
    for a in paper.get("authors", []):
        name = a.get("name", "")
        parts = name.rsplit(" ", 1)
        if len(parts) == 2:
            authors.append({"given": parts[0], "family": parts[1]})
        else:
            authors.append({"given": "", "family": name})

    ext_ids = paper.get("externalIds", {}) or {}

    return {
        "title": paper.get("title", ""),
        "author": authors,
        "year": paper.get("year"),
        "cited_by_count": paper.get("citationCount", 0),
        "doi": ext_ids.get("DOI"),
        "arxiv_id": ext_ids.get("ArXiv"),
        "abstract": paper.get("abstract"),
        "venue": paper.get("venue"),
        "url": paper.get("url"),
        "s2_id": paper.get("paperId"),
    }


async def get_citing_papers(doi: str, limit: int = 20) -> list[dict]:
    """Find papers that cite the given paper (downstream citations).

    These are newer papers that build on, extend, or reference this work.
    """
    data = await _s2_get(
        f"{S2_API}/paper/DOI:{doi}/citations",
        params={"fields": PAPER_FIELDS, "limit": limit},
    )
    if not data:
        return []

    results = []
    for item in data.get("data", []):
        paper = item.get("citingPaper", {})
        if paper.get("title"):
            results.append(_format_paper(paper))

    # Sort by citation count (most impactful first)
    results.sort(key=lambda p: p.get("cited_by_count", 0), reverse=True)
    return results


async def get_referenced_papers(doi: str, limit: int = 20) -> list[dict]:
    """Find papers that this paper cites (upstream references).

    These are the foundational works this paper builds upon.
    """
    data = await _s2_get(
        f"{S2_API}/paper/DOI:{doi}/references",
        params={"fields": PAPER_FIELDS, "limit": limit},
    )
    if not data:
        return []

    results = []
    for item in data.get("data", []):
        paper = item.get("citedPaper", {})
        if paper.get("title"):
            results.append(_format_paper(paper))

    results.sort(key=lambda p: p.get("cited_by_count", 0), reverse=True)
    return results


async def get_related_papers(doi: str, limit: int = 10) -> list[dict]:
    """Find related/similar papers using Semantic Scholar's recommendation engine.

    These are papers on similar topics that may not directly cite each other.
    """
    data = await _s2_get(
        f"{S2_RECO}/papers/forpaper/DOI:{doi}",
        params={"fields": PAPER_FIELDS, "limit": limit},
    )
    if not data:
        return []

    results = []
    for paper in data.get("recommendedPapers", []):
        if paper.get("title"):
            results.append(_format_paper(paper))

    return results


async def get_author_papers(
    doi: str,
    author_name: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Find more papers by the same author(s).

    If author_name is provided, finds that specific author's papers.
    Otherwise, uses the first author of the given DOI.

    Returns: {"author": {name, paper_count, h_index, ...}, "papers": [...]}
    """
    # Get the paper's authors first
    paper_data = await _s2_get(
        f"{S2_API}/paper/DOI:{doi}",
        params={"fields": "authors"},
    )
    if not paper_data:
        return {"author": None, "papers": []}

    authors = paper_data.get("authors", [])
    if not authors:
        return {"author": None, "papers": []}

    # Find the matching author or use the first one
    target_author = None
    if author_name:
        name_lower = author_name.lower()
        for a in authors:
            if name_lower in a.get("name", "").lower():
                target_author = a
                break
    if not target_author:
        target_author = authors[0]

    author_id = target_author.get("authorId")
    if not author_id:
        return {"author": {"name": target_author.get("name", "")}, "papers": []}

    # Get author details
    author_info = await _s2_get(
        f"{S2_API}/author/{author_id}",
        params={"fields": AUTHOR_FIELDS},
    )

    # Get author's papers
    papers_data = await _s2_get(
        f"{S2_API}/author/{author_id}/papers",
        params={"fields": PAPER_FIELDS, "limit": limit},
    )

    papers = []
    if papers_data:
        for item in papers_data.get("data", []):
            if item.get("title"):
                papers.append(_format_paper(item))
        papers.sort(key=lambda p: p.get("cited_by_count", 0), reverse=True)

    author_result = {
        "name": (author_info or {}).get("name", target_author.get("name", "")),
        "paper_count": (author_info or {}).get("paperCount", 0),
        "citation_count": (author_info or {}).get("citationCount", 0),
        "h_index": (author_info or {}).get("hIndex", 0),
        "s2_id": author_id,
    }

    return {"author": author_result, "papers": papers}


async def discover_all(doi: str, limits: Optional[dict] = None) -> dict:
    """Run all discovery queries in parallel for a given DOI.

    Returns a dict with all discovery results.
    """
    import asyncio

    lim = limits or {}
    citing_limit = lim.get("citing", 10)
    related_limit = lim.get("related", 10)
    author_limit = lim.get("author", 10)

    citing, related, author = await asyncio.gather(
        get_citing_papers(doi, limit=citing_limit),
        get_related_papers(doi, limit=related_limit),
        get_author_papers(doi, limit=author_limit),
        return_exceptions=True,
    )

    return {
        "citing": citing if isinstance(citing, list) else [],
        "related": related if isinstance(related, list) else [],
        "author": author if isinstance(author, dict) else {"author": None, "papers": []},
    }
