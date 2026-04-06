"""Find and download available PDFs for papers.

Checks sources in order (like Zotero):
1. Unpaywall API (open access database covering 50k+ repositories)
2. arXiv (if arXiv ID is available)
3. DOI redirect (follow DOI to publisher, check for PDF link)
4. Semantic Scholar (has some open access PDFs)

Unpaywall covers: PubMed Central, institutional repositories, DOAJ,
Gold OA journals, hybrid journals, disciplinary repositories.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class PdfSource:
    url: str
    source: str  # "unpaywall", "arxiv", "doi", "semantic_scholar"
    version: str  # "publishedVersion", "acceptedVersion", "submittedVersion", "unknown"


async def find_pdf(
    doi: str | None = None,
    arxiv_id: str | None = None,
    title: str | None = None,
    url: str | None = None,
) -> list[PdfSource]:
    """Find available PDF URLs for a paper. Returns list sorted by preference."""
    sources: list[PdfSource] = []

    # 1. Unpaywall (needs DOI)
    if doi:
        unpaywall = await _check_unpaywall(doi)
        sources.extend(unpaywall)

    # 2. arXiv
    if arxiv_id:
        sources.append(PdfSource(
            url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            source="arxiv",
            version="submittedVersion",
        ))
    elif doi:
        # Check if this DOI resolves to an arXiv paper
        aid = await _doi_to_arxiv(doi)
        if aid:
            sources.append(PdfSource(
                url=f"https://arxiv.org/pdf/{aid}.pdf",
                source="arxiv",
                version="submittedVersion",
            ))

    # 3. Semantic Scholar
    if doi or title:
        s2 = await _check_semantic_scholar(doi=doi, title=title)
        if s2:
            sources.extend(s2)

    # 4. DOI redirect — follow the DOI URL and look for PDF links
    if doi and not sources:
        doi_pdf = await _check_doi_redirect(doi)
        if doi_pdf:
            sources.append(doi_pdf)

    # Sort: publishedVersion > acceptedVersion > submittedVersion
    version_priority = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2, "unknown": 3}
    sources.sort(key=lambda s: version_priority.get(s.version, 3))

    return sources


async def download_pdf(url: str, dest: Path) -> bool:
    """Download a PDF from a URL. Returns True if successful."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Suchi/0.1 (research reference manager)",
                "Accept": "application/pdf, */*",
            })
            if resp.status_code != 200:
                return False

            # Verify it's actually a PDF (not an HTML login page)
            content_type = resp.headers.get("content-type", "")
            content = resp.content
            if b"%PDF" not in content[:20] and "pdf" not in content_type.lower():
                return False

            with open(dest, "wb") as f:
                f.write(content)
            return True
    except Exception:
        return False


async def _check_unpaywall(doi: str) -> list[PdfSource]:
    """Check Unpaywall for open access PDFs."""
    # Clean DOI
    doi = doi.strip()
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]

    url = f"https://api.unpaywall.org/v2/{doi}"
    try:
        from ..config import get_config
        cfg = get_config()
        # Unpaywall requires a real email — use configured or a reasonable default
        email = "suchi-user@users.noreply.github.com"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params={"email": email})
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception:
        return []

    sources = []
    for loc in data.get("oa_locations", []) or []:
        pdf_url = loc.get("url_for_pdf")
        if not pdf_url:
            pdf_url = loc.get("url_for_landing_page")
        if not pdf_url:
            continue

        # Force HTTPS
        pdf_url = pdf_url.replace("http://", "https://")

        version = loc.get("version", "unknown") or "unknown"
        sources.append(PdfSource(url=pdf_url, source="unpaywall", version=version))

    return sources


async def _doi_to_arxiv(doi: str) -> str | None:
    """Check if a DOI corresponds to an arXiv paper."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            resp = await client.head(f"https://doi.org/{doi}")
            final_url = str(resp.url)
            if "arxiv.org" in final_url:
                match = re.search(r"(\d{4}\.\d{4,5})", final_url)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return None


async def _check_semantic_scholar(doi: str | None = None, title: str | None = None) -> list[PdfSource]:
    """Check Semantic Scholar for open access PDFs."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if doi:
                resp = await client.get(
                    f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
                    params={"fields": "openAccessPdf"},
                )
            elif title:
                resp = await client.get(
                    "https://api.semanticscholar.org/graph/v1/paper/search",
                    params={"query": title, "limit": 1, "fields": "openAccessPdf"},
                )
            else:
                return []

            if resp.status_code != 200:
                return []

            data = resp.json()

            # Handle search results
            if "data" in data:
                data = data["data"][0] if data["data"] else {}

            oa_pdf = data.get("openAccessPdf")
            if oa_pdf and oa_pdf.get("url"):
                return [PdfSource(
                    url=oa_pdf["url"],
                    source="semantic_scholar",
                    version="unknown",
                )]
    except Exception:
        pass
    return []


async def _check_doi_redirect(doi: str) -> PdfSource | None:
    """Follow DOI redirect and look for PDF link on the landing page."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            # Try appending .pdf to the DOI URL (works for some publishers)
            resp = await client.head(f"https://doi.org/{doi}")
            final_url = str(resp.url)

            # Some publishers have a /pdf or /full/pdf variant
            for suffix in [".pdf", "/pdf", "/full/pdf"]:
                pdf_url = final_url.rstrip("/") + suffix
                try:
                    check = await client.head(pdf_url, timeout=10)
                    ct = check.headers.get("content-type", "")
                    if check.status_code == 200 and "pdf" in ct.lower():
                        return PdfSource(url=pdf_url, source="doi", version="publishedVersion")
                except Exception:
                    continue
    except Exception:
        pass
    return None
