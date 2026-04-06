"""CrossRef API translator for DOI resolution."""

import httpx


CROSSREF_API = "https://api.crossref.org/works"


async def resolve_doi(doi: str) -> dict | None:
    """Resolve a DOI to bibliographic metadata via CrossRef."""
    doi = doi.strip()
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]
    elif doi.startswith("http://dx.doi.org/"):
        doi = doi[len("http://dx.doi.org/"):]

    url = f"{CROSSREF_API}/{doi}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={"User-Agent": "Suchi/0.1 (https://github.com/ayushpatnaikgit/Suchi)"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("message", {})

    authors = []
    for a in data.get("author", []):
        authors.append({
            "family": a.get("family", ""),
            "given": a.get("given", ""),
        })

    title_list = data.get("title", [])
    title = title_list[0] if title_list else ""

    date_parts = data.get("issued", {}).get("date-parts", [[]])
    date = "-".join(str(p) for p in date_parts[0]) if date_parts[0] else None

    container = data.get("container-title", [])
    journal = container[0] if container else None

    # Extract keywords/subjects
    keywords = []
    for subj in data.get("subject", []):
        keywords.append(subj.strip().lower())

    return {
        "type": _map_type(data.get("type", "article")),
        "title": title,
        "author": authors,
        "doi": doi,
        "date": date,
        "journal": journal,
        "volume": data.get("volume"),
        "issue": data.get("issue"),
        "pages": data.get("page"),
        "publisher": data.get("publisher"),
        "abstract": _clean_abstract(data.get("abstract")),
        "url": data.get("URL"),
        "tags": keywords,
        "cited_by_count": data.get("is-referenced-by-count", 0),
    }


async def search_by_title(title: str) -> dict | None:
    """Search CrossRef by title and return the best match if confident."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            CROSSREF_API,
            params={
                "query.title": title,
                "rows": 3,
                "select": "DOI,title,author,issued,container-title,volume,issue,page,publisher,abstract,URL,type",
            },
            headers={"User-Agent": "Suchi/0.1 (https://github.com/ayushpatnaikgit/Suchi)"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None

        items = resp.json().get("message", {}).get("items", [])
        if not items:
            return None

    # Check if the top result is a good match
    best = items[0]
    best_title_list = best.get("title", [])
    best_title = best_title_list[0] if best_title_list else ""

    # Simple similarity: check if most words match
    if not _titles_match(title, best_title):
        return None

    # Good match — resolve the DOI for full metadata
    doi = best.get("DOI")
    if doi:
        return await resolve_doi(doi)

    return None


def _titles_match(query: str, candidate: str) -> bool:
    """Check if two titles are similar enough to be the same paper."""
    def normalize(s: str) -> set[str]:
        import re
        s = s.lower()
        s = re.sub(r"[^\w\s]", "", s)
        words = set(s.split())
        # Remove common stop words
        stop = {"the", "a", "an", "in", "of", "and", "for", "to", "on", "with", "by", "is", "at", "from"}
        return words - stop

    q_words = normalize(query)
    c_words = normalize(candidate)

    if not q_words or not c_words:
        return False

    overlap = len(q_words & c_words)
    # At least 60% of query words must appear in candidate
    return overlap / len(q_words) >= 0.6 and overlap / len(c_words) >= 0.4


def _map_type(crossref_type: str) -> str:
    mapping = {
        "journal-article": "article",
        "book": "book",
        "book-chapter": "inbook",
        "proceedings-article": "inproceedings",
        "dissertation": "thesis",
        "report": "report",
        "dataset": "dataset",
    }
    return mapping.get(crossref_type, "article")


def _clean_abstract(abstract: str | None) -> str | None:
    if not abstract:
        return None
    # CrossRef abstracts often have JATS XML tags
    import re
    return re.sub(r"<[^>]+>", "", abstract).strip()
