"""Extract references/bibliography from PDF text."""

import re
from pathlib import Path
import fitz


def extract_references(pdf_path: Path) -> list[dict]:
    """Extract references from the bibliography section of a PDF.

    Returns a list of dicts with: raw_text, title (if parseable), authors, year, doi.
    """
    doc = fitz.open(str(pdf_path))
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
    doc.close()

    # Find the references/bibliography section
    ref_text = _find_references_section(full_text)
    if not ref_text:
        return []

    # Split into individual references
    raw_refs = _split_references(ref_text)

    # Parse each reference
    results = []
    for raw in raw_refs:
        parsed = _parse_reference(raw)
        if parsed.get("title") or parsed.get("raw_text"):
            results.append(parsed)

    return results


def _find_references_section(text: str) -> str | None:
    """Find the references/bibliography section in the text.

    Handles:
    1. Explicit headers: "References", "Bibliography", "Works Cited"
    2. Papers without headers but with numbered references [1], 1., etc.
    """
    # Look for section headers (with optional section number prefix like "7 References")
    patterns = [
        r"\n\s*(?:\d+\.?\s+)?References\s*\n",
        r"\n\s*(?:\d+\.?\s+)?REFERENCES\s*\n",
        r"\n\s*(?:\d+\.?\s+)?Bibliography\s*\n",
        r"\n\s*(?:\d+\.?\s+)?BIBLIOGRAPHY\s*\n",
        r"\n\s*(?:\d+\.?\s+)?Works Cited\s*\n",
        r"\n\s*(?:\d+\.?\s+)?Literature Cited\s*\n",
        r"\n\s*(?:\d+\.?\s+)?Cited References\s*\n",
    ]

    best_pos = -1
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            pos = match.end()
            if pos > best_pos:
                best_pos = pos

    if best_pos != -1:
        ref_text = text[best_pos:]
        # Trim at appendix/footnotes/supplementary if present
        for end_pattern in [
            r"\n\s*(?:\d+\.?\s+)?Appendix",
            r"\n\s*(?:\d+\.?\s+)?APPENDIX",
            r"\n\s*(?:\d+\.?\s+)?Footnotes",
            r"\n\s*(?:\d+\.?\s+)?Supplementary",
            r"\n\s*(?:\d+\.?\s+)?Supporting Information",
            r"\n\s*(?:\d+\.?\s+)?Acknowledgements",
            r"\n\s*(?:\d+\.?\s+)?Acknowledgments",
        ]:
            end_match = re.search(end_pattern, ref_text, re.IGNORECASE)
            if end_match:
                ref_text = ref_text[:end_match.start()]
        return ref_text.strip()

    # Fallback: Look for numbered reference patterns without a header
    # Find the first occurrence of [1] or "1." followed by author-like text
    # that appears after the main body (typically in the last 40% of the document)
    text_len = len(text)
    search_start = int(text_len * 0.5)  # Only search in the back half

    # Pattern: numbered refs like "1. Author, F. ..." at start of lines
    numbered_start = re.search(
        r"\n\s*(?:\[1\]|1\.)\s+[A-Z][a-z]+",
        text[search_start:]
    )
    if numbered_start:
        ref_start = search_start + numbered_start.start()
        ref_text = text[ref_start:]

        # Trim at appendix/supplementary
        for end_pattern in [r"\n\s*Appendix", r"\n\s*Supplementary", r"\n\s*Extended Data"]:
            end_match = re.search(end_pattern, ref_text, re.IGNORECASE)
            if end_match:
                ref_text = ref_text[:end_match.start()]

        # Verify it actually has enough references (at least 3 numbered entries)
        ref_count = len(re.findall(r"\n\s*(?:\[\d+\]|\d+\.)\s+[A-Z]", ref_text))
        if ref_count >= 3:
            return ref_text.strip()

    return None


def _split_references(text: str) -> list[str]:
    """Split reference section into individual references."""
    refs = []

    # Try numbered references: [1], [2], ... (number may be followed by newline)
    numbered = re.split(r"\n\s*\[(\d+)\]\s*\n?", text)
    if len(numbered) > 3:
        for i in range(2, len(numbered), 2):
            ref = numbered[i].strip().replace("\n", " ")
            ref = re.sub(r"\s+", " ", ref)
            if ref and len(ref) > 20:
                refs.append(ref)
        if refs:
            return refs

    # Try dot-numbered: 1. Author... 2. Author...
    # Only accept if the numbers are sequential starting from 1 (avoids false positives
    # from volume/page numbers like "10, 1100-1120." appearing at start of lines)
    dot_numbered = re.split(r"\n\s*(\d+)\.\s+", text)
    if len(dot_numbered) > 5:  # Need at least 3 refs (preamble + 3*(num+text))
        # Verify sequential numbering: extract the captured numbers
        captured_nums = [int(dot_numbered[i]) for i in range(1, len(dot_numbered), 2)]
        if captured_nums and captured_nums[0] == 1 and all(
            captured_nums[i] == captured_nums[i-1] + 1 for i in range(1, min(5, len(captured_nums)))
        ):
            for i in range(2, len(dot_numbered), 2):
                ref = dot_numbered[i].strip()
                if ref and len(ref) > 20:
                    refs.append(ref)
            if refs:
                return refs

    # Author-date format: split when a line starts with "Surname Initial... (YYYY)."
    # Handles: "Lastname, I. (YYYY)", "Lastname INITIALS, Lastname I (YYYY)", "Lastname I (YYYY)"
    new_ref_pattern = re.compile(
        r"^[A-Z][A-Za-z\-'À-ÿ]+[\s,]+[A-Z]"  # Surname followed by space/comma then uppercase
        r".*?"                                   # Anything in between
        r"\(\s*(?:\w+\s+)?\d{4}[a-z]?\s*\)"    # Contains (YYYY) or (Month YYYY) or (2015a)
    )

    lines = text.split("\n")
    current = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if this line starts a new reference
        if current and new_ref_pattern.match(line):
            merged = re.sub(r"\s+", " ", current.strip())
            if len(merged) > 30:
                refs.append(merged)
            current = line
        else:
            current += " " + line if current else line

    if current:
        merged = re.sub(r"\s+", " ", current.strip())
        if len(merged) > 30:
            refs.append(merged)

    if refs:
        return refs

    # Final fallback: blank-line separated blocks
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        block = re.sub(r"\s+", " ", block.strip())
        if block and len(block) > 30:
            refs.append(block)

    return refs


def _parse_reference(raw: str) -> dict:
    """Parse a raw reference string into structured data."""
    result = {"raw_text": raw.replace("\n", " ").strip()[:500]}

    # Clean up — normalize smart quotes to straight quotes
    text = raw.replace("\n", " ").strip()
    text = text.replace("\u201c", '"').replace("\u201d", '"')  # " " → "
    text = text.replace("\u2018", "'").replace("\u2019", "'")  # ' ' → '
    text = text.replace("\u2013", "-").replace("\u2014", "-")  # en/em dash

    # Extract DOI
    doi_match = re.search(r"(?:doi[:\s]*|https?://doi\.org/)(10\.\d{4,9}/[^\s,;\"'<>\]]+)", text, re.IGNORECASE)
    if doi_match:
        doi = doi_match.group(1).rstrip(".")
        result["doi"] = doi

    # Extract year — prefer (YYYY) in parentheses, then ", YYYY" or ", YYYY.",
    # avoid matching 4-digit numbers that are part of page ranges like "1134-1138".
    # Years must be between 1900 and current+1.
    year_match = None
    for m in re.finditer(r"\((\d{4})\)", text):
        y = int(m.group(1))
        if 1900 <= y <= 2100:
            year_match = m
            break
    if not year_match:
        for m in re.finditer(r"(?<!\d-)(?<!\d)(\d{4})(?=\s*[.,)])", text):
            y = int(m.group(1))
            if 1900 <= y <= 2100:
                # Skip if immediately preceded by "pp." or page-range-like context
                start = m.start()
                if start >= 2 and text[start - 1] == "-" and text[start - 2].isdigit():
                    continue
                year_match = m
                break
    if year_match:
        result["year"] = year_match.group(1)

    # Extract title — multiple strategies
    title = None

    # Strategy 1: "Title in quotes" (IEEE style)
    m = re.search(r'"([^"]{10,300})"', text)
    if m:
        title = m.group(1)

    # Strategy 2: 'Title in single quotes'
    if not title:
        m = re.search(r"\u2018([^\u2019]{10,300})\u2019", raw)  # smart single quotes from original
        if not m:
            m = re.search(r"'([^']{10,300})'", text)
        if m:
            title = m.group(1)

    # Strategy 3: Author (YEAR). Title. (author-date format)
    # Match text after (YYYY). until the next sentence-ending period followed by
    # a venue keyword, "Tech. rep.", "url:", "In:", or end of text
    if not title:
        m = re.search(
            r"\(\s*(?:\w+\s+)?\d{4}\s*\)\.\s*"  # (YYYY). or (Month YYYY).
            r"(.+?)"                              # Title (non-greedy)
            r"(?:\.\s*(?:Tech\.|In[:\s]|url:|pp\.|[A-Z][a-z]+\s+\d|$))",  # End markers
            text
        )
        if m and len(m.group(1)) > 10:
            title = m.group(1)

    # Strategy 4: Nature/Science style — "Last, I., Last, I. & Last, I. Title. Journal Volume, Pages (Year)."
    # Match the text after the author block up to the next period followed by a
    # capitalized journal word followed by a number.
    if not title:
        m = re.search(
            r"(?:&\s*[A-Z][a-zA-Z'\-]+|et al\.)"    # "& Lastname" or "et al."
            r"(?:,\s*[A-Z]\.(?:\s*[A-Z]\.)*)?"      # optional ", I." or ", I. K."
            r"\.?\s+"                                 # separator (period may already be consumed)
            r"([A-Z][^.]{10,300}?)"                   # Title (starts with capital, no period inside)
            r"\.\s+[A-Z][a-zA-Z\.\s]{2,40}\s+\d",    # ". Journal Name Volume" (journal may have periods)
            text,
        )
        if m:
            title = m.group(1)

    # Strategy 5: After year, comma-separated: ..., YYYY, Title, Venue
    if not title:
        m = re.search(r",\s*\d{4}[.,]\s*([A-Z][^,]{10,200}?)(?:,|\.\s)", text)
        if m:
            title = m.group(1)

    if title:
        # Clean up title
        title = title.strip().rstrip(".").strip()
        # Remove trailing volume/page fragments that leaked in
        title = re.sub(r"\s+\d+\s*$", "", title)
        result["title"] = title

    # Extract authors — text before the year usually
    if year_match:
        author_text = text[:year_match.start()].strip().rstrip(",").rstrip("(")
        # Clean up
        author_text = re.sub(r"^\d+\.\s*", "", author_text)  # Remove leading number
        author_text = author_text.strip().rstrip(",").rstrip(".")
        if author_text and len(author_text) < 300:
            result["authors_raw"] = author_text

    # Extract URL
    url_match = re.search(r"(https?://[^\s,;\"'<>\]]+)", text)
    if url_match and "doi.org" not in url_match.group(1):
        result["url"] = url_match.group(1).rstrip(".")

    return result
