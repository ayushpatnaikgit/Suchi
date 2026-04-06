"""OpenAlex API for scholarly work lookup — 250M+ works, free, no auth."""

import asyncio
import time
import httpx


OPENALEX_API = "https://api.openalex.org"
MAILTO = "suchi@ayushpatnaik.com"  # Polite pool gets better rate limits

# Serialize all OpenAlex requests through a semaphore to stay under the polite-pool
# rate limit. Cap at 4 in-flight + minimum inter-request delay.
_openalex_semaphore = asyncio.Semaphore(4)
_MIN_INTERVAL = 0.12
_last_request_time = 0.0

# Circuit breaker: when OpenAlex returns 429, back off globally for the Retry-After
# period so subsequent calls short-circuit immediately instead of each paying the
# retry cost. This matters when we're enriching dozens of references in a row.
_disabled_until = 0.0  # unix timestamp; 0 means enabled
_MAX_DISABLE_SECONDS = 3600  # cap disable time so a 67000s Retry-After doesn't pin us indefinitely


def _is_disabled() -> bool:
    return time.time() < _disabled_until


def _disable_for(seconds: float) -> None:
    global _disabled_until
    cooloff = min(max(seconds, 5.0), _MAX_DISABLE_SECONDS)
    _disabled_until = time.time() + cooloff


async def _throttled_get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response | None:
    """GET an OpenAlex URL with rate limiting and a circuit breaker on 429.

    Returns None if the circuit is open, if we get rate-limited, or on network error.
    Callers should treat None as "skip OpenAlex, try a fallback".
    """
    global _last_request_time

    # Circuit open: short-circuit without touching the network
    if _is_disabled():
        return None

    async with _openalex_semaphore:
        # Respect minimum interval between requests
        now = asyncio.get_event_loop().time()
        wait = _MIN_INTERVAL - (now - _last_request_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_time = asyncio.get_event_loop().time()

        try:
            resp = await client.get(url, timeout=15, **kwargs)
        except (httpx.TimeoutException, httpx.HTTPError):
            return None

        if resp.status_code == 429:
            # Open the circuit. Honor Retry-After if provided (capped).
            retry_after = resp.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else 60.0
            except ValueError:
                delay = 60.0
            _disable_for(delay)
            return None

        return resp


async def search_by_title(title: str, threshold: float = 0.7) -> dict | None:
    """Search OpenAlex by title and return the best match."""
    async with httpx.AsyncClient() as client:
        resp = await _throttled_get(
            client,
            f"{OPENALEX_API}/works",
            params={
                "search": title,
                "per_page": 3,
                "mailto": MAILTO,
            },
        )
        if not resp or resp.status_code != 200:
            return None

        results = resp.json().get("results", [])
        if not results:
            return None

    # Check best match
    best = results[0]
    best_title = best.get("title", "")
    if not _titles_match(title, best_title):
        return None

    return _parse_work(best)


async def search_by_doi(doi: str) -> dict | None:
    """Look up a work by DOI."""
    doi = doi.strip()
    if not doi.startswith("https://doi.org/"):
        doi_url = f"https://doi.org/{doi}"
    else:
        doi_url = doi

    async with httpx.AsyncClient() as client:
        resp = await _throttled_get(
            client,
            f"{OPENALEX_API}/works/{doi_url}",
            params={"mailto": MAILTO},
        )
        if not resp or resp.status_code != 200:
            return None

        return _parse_work(resp.json())


async def resolve_reference(raw_text: str) -> dict | None:
    """Try to resolve a raw reference string to structured metadata.

    Tries multiple strategies in order of reliability:
    1. Extract DOI from the text and look up directly
    2. Extract title via multiple patterns and search
    3. Strip author names and search remaining text
    """
    import re

    # Pre-process: fix line-break hyphens (e.g., "acceler-\nator" → "accelerator")
    raw_text = re.sub(r"-\s+", "", raw_text)

    # Strategy 1: Extract DOI (most reliable)
    doi_match = re.search(r"10\.\d{4,9}/[^\s,;\"'<>\]]+", raw_text)
    if doi_match:
        result = await search_by_doi(doi_match.group().rstrip("."))
        if result:
            return result

    # Strategy 2: Extract title via patterns
    title_candidates = _extract_title_candidates(raw_text)
    for title in title_candidates:
        if len(title) > 10:
            result = await search_by_title(title)
            if result:
                return result

    # Strategy 3: Strip authors and venue noise, search the remaining text
    cleaned = _strip_authors(raw_text)
    if cleaned and len(cleaned) > 15:
        # Also strip venue/publisher names after the title
        # Remove trailing "Venue.", "Tech. rep.", etc.
        import re
        cleaned_title = re.split(
            r"\.\s+(?:In\s|Proc\.|IEEE|ACM|NeurIPS|ICML|ICLR|AAAI|Nature|Science|Tech\.|arXiv|[A-Z][A-Z])",
            cleaned
        )[0].strip().rstrip(".")

        if cleaned_title and len(cleaned_title) > 10:
            result = await search_by_title(cleaned_title, threshold=0.4)
            if result:
                return result

        # Try the full cleaned text as a last resort
        if cleaned != cleaned_title:
            result = await search_by_title(cleaned, threshold=0.4)
            if result:
                return result

    return None


def _extract_title_candidates(raw_text: str) -> list[str]:
    """Extract possible title strings from a raw reference using multiple patterns."""
    import re
    candidates = []

    # Normalize smart quotes
    text = raw_text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")

    # 1. "Quoted title" (IEEE style)
    m = re.search(r'"([^"]{10,300})"', text)
    if m:
        candidates.append(m.group(1).strip())

    # 2. 'Single-quoted title'
    m = re.search(r"'([^']{10,300})'", text)
    if m:
        candidates.append(m.group(1).strip())

    # 3. Author-date: Author (YYYY). Title. Venue
    m = re.search(
        r"\(\s*(?:\w+\s+)?\d{4}\s*\)\.\s*(.+?)(?:\.\s+(?:In[:\s]|Tech\.|url:|pp\.|[A-Z][a-z]+\s+\d|$))",
        text
    )
    if m and len(m.group(1)) > 10:
        candidates.append(m.group(1).strip().rstrip("."))

    # 4. IEEE/ACM style: Author1, Author2. Title. Venue, Year.
    # After a period that follows an initial or "et al.", grab until the next period+space+Capital
    m = re.search(
        r"(?:(?:[A-Z]\.\s*)+[A-Z][a-z]+|et al\.)\.\s+"  # Author ending
        r"(.+?)"                                          # Title
        r"(?:\.\s+(?:In\s|Proc\.|IEEE|ACM|MICRO|ISCA|arXiv|Tech|[A-Z][A-Z])|,\s*\d{4})",  # Venue/year
        text
    )
    if m and len(m.group(1)) > 10:
        candidates.append(m.group(1).strip().rstrip("."))

    # 5. After "and LastName." — title starts
    m = re.search(
        r"and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\.\s+"     # "and Sanchez."
        r"(.+?)"                                            # Title
        r"(?:\.\s+[A-Z]|,\s*\d{4})",                       # End marker
        text
    )
    if m and len(m.group(1)) > 10:
        candidates.append(m.group(1).strip().rstrip("."))

    # 6. Nature/Science style: "Author et al. Title. Journal Volume, Pages (Year)."
    m = re.search(
        r"(?:et\s+al\.|[A-Z]\.\s*[A-Z]\.)\s+"             # "et al." or "J. K."
        r"(.+?)"                                            # Title
        r"\.\s+[A-Z][a-z]+\.?\s+\d",                       # ". Journal Volume"
        text
    )
    if m and len(m.group(1)) > 10:
        candidates.append(m.group(1).strip().rstrip("."))

    # 7. Simple: "Lastname, I. Title. Journal" or "Lastname, I. et al. Title."
    m = re.search(
        r"[A-Z][a-z]+,\s+[A-Z]\.(?:\s*[A-Z]\.)*\s+"       # "Maze, J."
        r"(?:et\s+al\.\s+)?"                                # optional "et al."
        r"(.+?)"                                            # Title
        r"\.\s+[A-Z]",                                      # ". Journal" or ". Nature"
        text
    )
    if m and len(m.group(1)) > 10:
        candidates.append(m.group(1).strip().rstrip("."))

    return candidates


def _strip_authors(raw_text: str) -> str:
    """Strip likely author names from the beginning, leaving title + venue."""
    import re

    text = raw_text.strip()

    # Remove leading "[N]" or "N."
    text = re.sub(r"^\[\d+\]\s*", "", text)
    text = re.sub(r"^\d+\.\s*", "", text)

    # Remove author block: sequences of "Initial. Lastname," or "Lastname, Initial,"
    # until we hit a period followed by a title-like capital word
    # Find the first sentence after author-like patterns
    m = re.search(
        r"(?:(?:[A-Z]\.\s*)+[A-Z][a-z]+(?:,\s*|\s+and\s+))+(?:[A-Z]\.\s*)*[A-Z][a-z]+\.\s*",
        text
    )
    if m:
        text = text[m.end():]

    # "Lastname, I. et al." style
    m = re.search(r"(?:[A-Z][a-z]+,\s*[A-Z]\.(?:\s*[A-Z]\.)*\s*(?:et\s+al\.)?\s*)", text)
    if m and m.start() == 0:
        text = text[m.end():].lstrip(". ")

    # Also try: "Lastname, Firstname and Lastname, Firstname (YYYY)."
    m = re.search(r"\(\d{4}\)\.\s*", text)
    if m:
        text = text[m.end():]

    # Trim trailing venue/year noise
    text = re.sub(r"\.\s*(?:url|https?):.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r",\s*\d{4}\.\s*$", "", text)

    return text.strip()[:200]


def _parse_work(work: dict) -> dict:
    """Parse an OpenAlex work object into our standard metadata format."""
    authors = []
    for authorship in work.get("authorships", []):
        author = authorship.get("author", {})
        name = author.get("display_name", "")
        if name:
            parts = name.rsplit(" ", 1)
            if len(parts) == 2:
                authors.append({"given": parts[0], "family": parts[1]})
            else:
                authors.append({"given": "", "family": name})

    # Extract DOI
    doi = work.get("doi", "")
    if doi and doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]

    # Extract concepts as tags
    tags = []
    for concept in work.get("concepts", []):
        if concept.get("score", 0) > 0.3:  # Only high-relevance concepts
            tags.append(concept["display_name"].lower())

    # Also add topics if available
    for topic in work.get("topics", [])[:3]:
        name = topic.get("display_name", "").lower()
        if name and name not in tags:
            tags.append(name)

    # Journal / venue
    source = work.get("primary_location", {}).get("source", {}) or {}
    journal = source.get("display_name")

    # Abstract reconstruction from inverted index
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))

    # Open access PDF URL
    oa = work.get("open_access", {})
    pdf_url = oa.get("oa_url") if oa.get("is_oa") else None

    return {
        "type": _map_type(work.get("type", "article")),
        "title": work.get("title", ""),
        "author": authors,
        "doi": doi or None,
        "date": str(work.get("publication_year", "")),
        "journal": journal,
        "volume": work.get("biblio", {}).get("volume"),
        "issue": work.get("biblio", {}).get("issue"),
        "pages": _format_pages(work.get("biblio", {})),
        "abstract": abstract,
        "url": work.get("doi") or work.get("id"),
        "tags": tags[:10],  # Limit to top 10
        "pdf_url": pdf_url,
        "cited_by_count": work.get("cited_by_count", 0),
        "openalex_id": work.get("id"),
    }


def _reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Reconstruct abstract text from OpenAlex's inverted index format."""
    if not inverted_index:
        return None

    # inverted_index is {word: [position1, position2, ...]}
    positions = []
    for word, indices in inverted_index.items():
        for idx in indices:
            positions.append((idx, word))

    if not positions:
        return None

    positions.sort()
    return " ".join(word for _, word in positions)


def _format_pages(biblio: dict) -> str | None:
    first = biblio.get("first_page")
    last = biblio.get("last_page")
    if first and last and first != last:
        return f"{first}-{last}"
    return first


def _map_type(openalex_type: str) -> str:
    mapping = {
        "article": "article",
        "journal-article": "article",
        "book": "book",
        "book-chapter": "inbook",
        "proceedings-article": "inproceedings",
        "dissertation": "thesis",
        "report": "report",
        "dataset": "dataset",
        "review": "article",
        "preprint": "article",
    }
    return mapping.get(openalex_type, "article")


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
    return overlap / max(len(q), 1) >= 0.5 and overlap / max(len(c), 1) >= 0.4
