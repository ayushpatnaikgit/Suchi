"""Extract metadata (DOI, title, authors) from PDF files using PyMuPDF."""

import re
from pathlib import Path

import fitz  # PyMuPDF


# DOI patterns found in PDFs
DOI_PATTERNS = [
    re.compile(r"(?:doi|DOI)[:\s]*\s*(10\.\d{4,9}/[^\s,;\"'<>\]]+)", re.IGNORECASE),
    re.compile(r"(10\.\d{4,9}/[^\s,;\"'<>\]]+)"),
    re.compile(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s,;\"'<>\]]+)"),
]

# arXiv pattern
ARXIV_PATTERN = re.compile(r"arXiv:\s*([\d]{4}\.[\d]{4,5}(?:v\d+)?)", re.IGNORECASE)


def extract_text_from_pdf(pdf_path: Path, max_pages: int = 5) -> str:
    """Extract text from the first N pages of a PDF."""
    doc = fitz.open(str(pdf_path))
    text = ""
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        text += page.get_text() + "\n"
    doc.close()
    return text


def extract_doi_from_pdf(pdf_path: Path) -> str | None:
    """Try to find a DOI in the PDF text or metadata."""
    doc = fitz.open(str(pdf_path))

    # Check PDF metadata first
    meta = doc.metadata or {}
    for key in ["subject", "keywords", "title"]:
        val = meta.get(key, "") or ""
        for pattern in DOI_PATTERNS:
            match = pattern.search(val)
            if match:
                doc.close()
                return _clean_doi(match.group(1))

    # Check first 3 pages of text
    for i, page in enumerate(doc):
        if i >= 3:
            break
        text = page.get_text()
        for pattern in DOI_PATTERNS:
            match = pattern.search(text)
            if match:
                doc.close()
                return _clean_doi(match.group(1))

    doc.close()
    return None


def extract_arxiv_from_pdf(pdf_path: Path) -> str | None:
    """Try to find an arXiv ID in the PDF."""
    doc = fitz.open(str(pdf_path))

    for i, page in enumerate(doc):
        if i >= 3:
            break
        text = page.get_text()
        match = ARXIV_PATTERN.search(text)
        if match:
            doc.close()
            return match.group(1)

    doc.close()
    return None


def extract_metadata_from_pdf(pdf_path: Path) -> dict:
    """Extract all available metadata from a PDF.

    Returns a dict with any of: doi, arxiv_id, title, author, date, and the raw text.
    """
    result: dict = {}

    doc = fitz.open(str(pdf_path))
    meta = doc.metadata or {}

    # PDF embedded metadata
    if meta.get("title") and len(meta["title"].strip()) > 3:
        result["title"] = meta["title"].strip()

    if meta.get("author"):
        result["raw_author"] = meta["author"].strip()

    if meta.get("creationDate"):
        # Format: D:20230115120000+00'00'
        date_str = meta["creationDate"]
        if date_str.startswith("D:"):
            date_str = date_str[2:]
        if len(date_str) >= 8:
            try:
                result["date"] = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            except (ValueError, IndexError):
                pass

    # Extract text from first page for title heuristic
    first_page_text = ""
    if doc.page_count > 0:
        first_page_text = doc[0].get_text()

    doc.close()

    # Try to find DOI
    doi = extract_doi_from_pdf(pdf_path)
    if doi:
        result["doi"] = doi

    # Try to find arXiv ID
    arxiv_id = extract_arxiv_from_pdf(pdf_path)
    if arxiv_id:
        result["arxiv_id"] = arxiv_id

    # If no title from metadata, try first large text on first page
    if "title" not in result and first_page_text:
        result["title"] = _guess_title_from_text(first_page_text)

    # Try to extract authors, abstract, and keywords from first page text
    if first_page_text:
        parsed = _parse_first_page(first_page_text, result.get("title"))
        if parsed.get("authors") and "raw_author" not in result:
            result["raw_author"] = "; ".join(parsed["authors"])
        if parsed.get("abstract") and "abstract" not in result:
            result["abstract"] = parsed["abstract"]
        if parsed.get("keywords"):
            result["keywords"] = parsed["keywords"]

    # Also check PDF metadata keywords field
    if not result.get("keywords"):
        doc = fitz.open(str(pdf_path))
        meta = doc.metadata or {}
        doc.close()
        kw = meta.get("keywords", "")
        if kw and kw.strip():
            result["keywords"] = [k.strip().lower() for k in re.split(r"[,;]", kw) if k.strip()]

    return result


def _guess_title_from_text(text: str) -> str | None:
    """Heuristic: the title is usually the first non-trivial line of text."""
    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        # Skip very short lines, page numbers, headers
        if len(line) < 10:
            continue
        # Skip lines that look like author names (contain @, university, etc.)
        if "@" in line or "university" in line.lower() or "department" in line.lower():
            continue
        # Skip lines that are all uppercase and very short (section headers)
        if line.isupper() and len(line) < 30:
            continue
        # This is likely the title
        return line[:200]
    return None


def _parse_first_page(text: str, known_title: str | None = None) -> dict:
    """Parse authors and abstract from first page text.

    Typical academic paper layout:
        Title
        Author1
        Author2
        ...
        [Date]
        Abstract
        Abstract text...
    """
    lines = text.strip().split("\n")
    result: dict = {"authors": [], "abstract": None, "keywords": []}

    # Find where the title is, then authors come after
    title_idx = -1
    if known_title:
        title_lower = known_title.lower().strip()
        for i, line in enumerate(lines):
            if line.strip().lower().startswith(title_lower[:30]):
                title_idx = i
                break

    # Find abstract section
    abstract_start = -1
    abstract_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() in ("abstract", "abstract.") or stripped.lower().startswith("abstract\n"):
            abstract_start = i + 1
            continue
        if abstract_start > 0 and i >= abstract_start:
            # Stop at keywords, introduction, or other section headers
            if stripped.lower() in ("keywords", "keywords:", "introduction", "1 introduction", "1. introduction"):
                break
            if re.match(r"^\d+\.?\s+[A-Z]", stripped):  # Section number like "1 Introduction"
                break
            if stripped.startswith("JEL") or stripped.startswith("Keywords"):
                break
            if stripped:
                abstract_lines.append(stripped)

    if abstract_lines:
        result["abstract"] = " ".join(abstract_lines).strip()

    # Extract authors: lines between title and abstract/date
    if title_idx >= 0:
        author_region_end = abstract_start if abstract_start > 0 else min(title_idx + 15, len(lines))
        for i in range(title_idx + 1, author_region_end):
            line = lines[i].strip()
            if not line:
                continue
            # Stop at abstract header
            if line.lower() in ("abstract", "abstract."):
                break
            # Stop at date-like patterns
            if re.match(r"^\d{1,2}(st|nd|rd|th)?\s+\w+\s+\d{4}", line):
                break
            # Skip affiliations, emails, footnote markers
            if "@" in line or "university" in line.lower() or "institute" in line.lower():
                continue
            if line.startswith("∗") or line.startswith("*") or line.startswith("†"):
                continue
            if len(line) > 60:  # Too long to be a name
                continue
            # This looks like an author name (short, capitalized words)
            words = line.replace(",", "").replace("∗", "").replace("*", "").strip().split()
            if 1 <= len(words) <= 5 and all(w[0].isupper() or w in ("de", "van", "von", "di", "la", "el") for w in words if w):
                result["authors"].append(line.replace("∗", "").replace("*", "").replace("†", "").strip())

    # Extract keywords: look for "Keywords:" or "JEL classification:" lines
    for i, line in enumerate(lines):
        stripped = line.strip()
        lower = stripped.lower()

        # Match: "Keywords: word1, word2, word3" or "Keywords" on its own line
        kw_text = None
        if lower.startswith("keywords:") or lower.startswith("key words:"):
            kw_text = stripped.split(":", 1)[1].strip()
        elif lower.startswith("keywords") and lower == "keywords":
            # Keywords on next line(s)
            kw_parts = []
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j].strip()
                if not next_line or next_line.lower().startswith("jel") or re.match(r"^\d+\.?\s+[A-Z]", next_line):
                    break
                kw_parts.append(next_line)
            kw_text = " ".join(kw_parts)

        if kw_text:
            # Split by comma, semicolon, or bullet
            keywords = re.split(r"[,;•·]", kw_text)
            for kw in keywords:
                kw = kw.strip().strip(".").lower()
                if not kw or len(kw) < 2 or len(kw) > 60:
                    continue
                # Filter out JEL codes and classification numbers
                if re.match(r"^jel\s*:?\s*[a-z]\d", kw, re.IGNORECASE):
                    continue
                if re.match(r"^[a-z]\d{1,2}$", kw):  # Single codes like "h2", "q4"
                    continue
                result["keywords"].append(kw)
            break  # Found keywords, stop looking

        # Skip JEL classification lines entirely

    return result


def _clean_doi(doi: str) -> str:
    """Clean up a DOI string."""
    doi = doi.strip().rstrip(".")
    # Remove trailing punctuation that got captured
    while doi and doi[-1] in ".,;:)]}":
        doi = doi[:-1]
    return doi


def parse_raw_authors(raw: str) -> list[dict]:
    """Parse a raw author string like 'John Smith, Jane Doe' into structured authors."""
    authors = []
    # Try semicolon-separated first, then comma
    if ";" in raw:
        parts = raw.split(";")
    elif " and " in raw.lower():
        parts = re.split(r"\s+and\s+", raw, flags=re.IGNORECASE)
    else:
        parts = raw.split(",")

    for part in parts:
        part = part.strip()
        if not part:
            continue
        # "Last, First" format
        if "," in part and len(parts) == 1:
            # If only one part with comma, it might be "Last, First"
            subparts = part.split(",", 1)
            authors.append({"family": subparts[0].strip(), "given": subparts[1].strip()})
        else:
            # "First Last" format
            name_parts = part.rsplit(" ", 1)
            if len(name_parts) == 2:
                authors.append({"given": name_parts[0].strip(), "family": name_parts[1].strip()})
            else:
                authors.append({"family": part, "given": ""})

    return authors
