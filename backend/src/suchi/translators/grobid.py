"""GROBID integration for ML-based PDF metadata and reference extraction.

GROBID produces vastly superior results compared to regex-based extraction.
It uses machine learning to parse academic PDFs and returns structured TEI XML.

Requires GROBID running locally via Docker:
    docker run --rm --init -d -p 8070:8070 grobid/grobid:0.8.2
"""

import re
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

GROBID_URL = "http://localhost:8070"
TEI_NS = "http://www.tei-c.org/ns/1.0"


async def is_available() -> bool:
    """Check if GROBID is running and reachable."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{GROBID_URL}/api/isalive", timeout=3)
            return resp.status_code == 200
    except Exception:
        return False


async def extract_header(pdf_path: Path) -> dict | None:
    """Extract document header metadata (title, authors, abstract, etc.) via GROBID.

    Returns dict with: title, author, abstract, doi, date, journal, volume, pages, etc.
    """
    try:
        async with httpx.AsyncClient() as client:
            with open(pdf_path, "rb") as f:
                resp = await client.post(
                    f"{GROBID_URL}/api/processHeaderDocument",
                    files={"input": (pdf_path.name, f, "application/pdf")},
                    data={"consolidateHeader": "1"},  # Cross-check with CrossRef
                    timeout=60,
                )
            if resp.status_code != 200:
                return None
            return _parse_tei_header(resp.text)
    except Exception:
        return None


async def extract_references(pdf_path: Path) -> list[dict]:
    """Extract all bibliographic references from a PDF via GROBID.

    Returns list of dicts with: title, authors, date, journal, doi, etc.
    """
    try:
        async with httpx.AsyncClient() as client:
            with open(pdf_path, "rb") as f:
                resp = await client.post(
                    f"{GROBID_URL}/api/processReferences",
                    files={"input": (pdf_path.name, f, "application/pdf")},
                    data={"consolidateCitations": "1"},  # Cross-check with CrossRef
                    timeout=120,
                )
            if resp.status_code != 200:
                return []
            return _parse_tei_references(resp.text)
    except Exception:
        return []


async def extract_full(pdf_path: Path) -> dict | None:
    """Extract full document structure (header + body + references) via GROBID.

    Returns dict with: header (metadata), references (list), and body_text.
    """
    try:
        async with httpx.AsyncClient() as client:
            with open(pdf_path, "rb") as f:
                resp = await client.post(
                    f"{GROBID_URL}/api/processFulltextDocument",
                    files={"input": (pdf_path.name, f, "application/pdf")},
                    data={
                        "consolidateHeader": "1",
                        "consolidateCitations": "1",
                    },
                    timeout=120,
                )
            if resp.status_code != 200:
                return None

            header = _parse_tei_header(resp.text)
            refs = _parse_tei_references(resp.text)
            return {
                "header": header,
                "references": refs,
            }
    except Exception:
        return None


def _parse_tei_header(tei_xml: str) -> dict | None:
    """Parse GROBID's TEI XML header into a clean metadata dict."""
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError:
        return None

    ns = {"tei": TEI_NS}

    # Title
    title_el = root.find(".//tei:titleStmt/tei:title[@type='main']", ns)
    if title_el is None:
        title_el = root.find(".//tei:titleStmt/tei:title", ns)
    title = _get_text(title_el) if title_el is not None else ""

    # Authors
    authors = []
    for author_el in root.findall(".//tei:sourceDesc//tei:author/tei:persName", ns):
        given_el = author_el.find("tei:forename[@type='first']", ns)
        middle_el = author_el.find("tei:forename[@type='middle']", ns)
        family_el = author_el.find("tei:surname", ns)

        given = _get_text(given_el) or ""
        middle = _get_text(middle_el) or ""
        family = _get_text(family_el) or ""

        if middle:
            given = f"{given} {middle}".strip()

        if family:
            authors.append({"given": given, "family": family})

    # Abstract
    abstract_el = root.find(".//tei:profileDesc/tei:abstract", ns)
    abstract = ""
    if abstract_el is not None:
        abstract_parts = []
        for p in abstract_el.findall(".//tei:p", ns):
            text = _get_all_text(p)
            if text:
                abstract_parts.append(text)
        abstract = " ".join(abstract_parts).strip()
        if not abstract:
            abstract = _get_all_text(abstract_el).strip()

    # DOI
    doi = None
    for idno in root.findall(".//tei:sourceDesc//tei:idno[@type='DOI']", ns):
        doi = _get_text(idno)
        break

    # Date
    date = None
    date_el = root.find(".//tei:sourceDesc//tei:date[@type='published']", ns)
    if date_el is not None:
        date = date_el.get("when", "") or _get_text(date_el) or ""

    # Journal/venue
    journal = None
    journal_el = root.find(".//tei:sourceDesc//tei:title[@level='j']", ns)
    if journal_el is not None:
        journal = _get_text(journal_el)

    # Volume, issue, pages
    volume = None
    issue = None
    pages = None
    for bibl_scope in root.findall(".//tei:sourceDesc//tei:biblScope", ns):
        unit = bibl_scope.get("unit", "")
        val = _get_text(bibl_scope) or bibl_scope.get("from", "") or ""
        to_val = bibl_scope.get("to", "")
        if unit == "volume":
            volume = val
        elif unit == "issue":
            issue = val
        elif unit == "page":
            if to_val:
                pages = f"{val}-{to_val}"
            else:
                pages = val

    # Publisher
    publisher = None
    pub_el = root.find(".//tei:sourceDesc//tei:publisher", ns)
    if pub_el is not None:
        publisher = _get_text(pub_el)

    # Keywords
    keywords = []
    for kw in root.findall(".//tei:profileDesc//tei:keywords//tei:term", ns):
        text = _get_text(kw)
        if text:
            keywords.append(text.strip())

    result = {
        "type": "article",
        "title": title,
        "author": authors,
        "abstract": abstract,
        "doi": doi,
        "date": date,
        "journal": journal,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "publisher": publisher,
        "tags": keywords,
    }

    # Remove None values
    return {k: v for k, v in result.items() if v is not None}


def _parse_tei_references(tei_xml: str) -> list[dict]:
    """Parse GROBID's TEI XML into a list of reference dicts."""
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError:
        return []

    ns = {"tei": TEI_NS}
    refs = []

    for bibl in root.findall(".//tei:listBibl/tei:biblStruct", ns):
        ref = _parse_bibl_struct(bibl, ns)
        if ref and ref.get("title"):
            refs.append(ref)

    return refs


def _parse_bibl_struct(bibl: ET.Element, ns: dict) -> dict:
    """Parse a single biblStruct element into a reference dict."""
    # Title - check analytic (article) then monogr (book)
    title = ""
    title_el = bibl.find(".//tei:analytic/tei:title[@type='main']", ns)
    if title_el is None:
        title_el = bibl.find(".//tei:analytic/tei:title", ns)
    if title_el is None:
        title_el = bibl.find(".//tei:monogr/tei:title[@type='main']", ns)
    if title_el is None:
        title_el = bibl.find(".//tei:monogr/tei:title", ns)
    if title_el is not None:
        title = _get_all_text(title_el)

    # Authors - check analytic first, then monogr
    authors = []
    author_section = bibl.find("tei:analytic", ns)
    if author_section is None:
        author_section = bibl.find("tei:monogr", ns)
    if author_section is not None:
        for author_el in author_section.findall("tei:author/tei:persName", ns):
            given_el = author_el.find("tei:forename[@type='first']", ns)
            family_el = author_el.find("tei:surname", ns)
            given = _get_text(given_el) or ""
            family = _get_text(family_el) or ""
            if family:
                authors.append({"given": given, "family": family})

    authors_raw = ", ".join(
        f"{a['given']} {a['family']}".strip() for a in authors
    ) if authors else ""

    # Date
    year = None
    date_el = bibl.find(".//tei:monogr//tei:date[@type='published']", ns)
    if date_el is None:
        date_el = bibl.find(".//tei:date", ns)
    if date_el is not None:
        when = date_el.get("when", "")
        if when:
            year = when[:4]
        else:
            text = _get_text(date_el) or ""
            year_match = re.search(r"(\d{4})", text)
            if year_match:
                year = year_match.group(1)

    # Journal
    journal = None
    journal_el = bibl.find(".//tei:monogr/tei:title[@level='j']", ns)
    if journal_el is not None:
        journal = _get_all_text(journal_el)

    # DOI
    doi = None
    for idno in bibl.findall(".//tei:idno[@type='DOI']", ns):
        doi = _get_text(idno)
        break

    # Volume, pages
    volume = None
    pages = None
    for scope in bibl.findall(".//tei:monogr//tei:biblScope", ns):
        unit = scope.get("unit", "")
        if unit == "volume":
            volume = _get_text(scope) or scope.get("from", "")
        elif unit == "page":
            from_p = scope.get("from", "")
            to_p = scope.get("to", "")
            if from_p and to_p:
                pages = f"{from_p}-{to_p}"
            elif from_p:
                pages = from_p
            else:
                pages = _get_text(scope)

    # URL
    url = None
    for ptr in bibl.findall(".//tei:ptr", ns):
        target = ptr.get("target", "")
        if target.startswith("http"):
            url = target
            break

    # Raw text for display
    raw_text = title
    if authors_raw:
        raw_text = f"{authors_raw}. {raw_text}"
    if year:
        raw_text += f" ({year})"
    if journal:
        raw_text += f". {journal}"

    return {
        "title": title.strip(),
        "authors": authors,
        "authors_raw": authors_raw,
        "year": year,
        "journal": journal,
        "doi": doi,
        "volume": volume,
        "pages": pages,
        "url": url,
        "raw_text": raw_text.strip(),
    }


def _get_text(el: ET.Element | None) -> str | None:
    """Get direct text content of an element."""
    if el is None:
        return None
    return (el.text or "").strip() or None


def _get_all_text(el: ET.Element) -> str:
    """Get all text content including children (like itertext)."""
    return " ".join(el.itertext()).strip()
