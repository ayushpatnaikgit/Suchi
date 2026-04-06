"""Build hierarchical tree indices from PDFs using LLM reasoning.

Inspired by VectifyAI/PageIndex. Instead of vector embeddings, we:
1. Extract text from each PDF page
2. Ask the LLM to generate a hierarchical table-of-contents tree
3. Each tree node has: title, summary, page range
4. Store as .pageindex.json per entry

For collections, we build a meta-index: a tree of paper summaries + their section trees.
"""

import json
import re
from pathlib import Path

import fitz  # PyMuPDF
import httpx

from ..config import get_config

INDEX_FILENAME = ".pageindex.json"
COLLECTION_INDEX_FILENAME = ".collection-index.json"
INDEX_VERSION = 1

# Max tokens per LLM call — we chunk the document if it's too large
MAX_PAGES_PER_CHUNK = 15


def _gemini_url(model: str = "") -> str:
    config = get_config()
    model = model or config.ai.model or "gemini-2.5-flash"
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _gemini_key() -> str:
    config = get_config()
    return config.ai.gemini_api_key


def _extract_pages(pdf_path: Path) -> list[dict]:
    """Extract text from each page of a PDF."""
    doc = fitz.open(str(pdf_path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        if text:
            pages.append({
                "page_num": i + 1,
                "text": text[:3000],  # Cap per-page text to avoid token overflow
                "char_count": len(text),
            })
    doc.close()
    return pages


def _call_gemini(prompt: str, system: str = "") -> str:
    """Call Gemini API synchronously."""
    key = _gemini_key()
    if not key:
        raise ValueError("Gemini API key not configured. Set it in Settings or config.yaml.")

    contents = []
    if system:
        contents.append({"role": "user", "parts": [{"text": system}]})
        contents.append({"role": "model", "parts": [{"text": "Understood."}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})

    resp = httpx.post(
        _gemini_url(),
        params={"key": key},
        json={
            "contents": contents,
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 8000,
            },
        },
        timeout=120,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API error {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    return candidates[0]["content"]["parts"][0]["text"]


def _extract_json_from_response(text: str) -> dict | list:
    """Extract JSON from a Gemini response that may contain markdown fences."""
    # Try to find JSON in code blocks
    m = re.search(r"```(?:json)?\s*\n?([\s\S]+?)\n?```", text)
    if m:
        return json.loads(m.group(1))
    # Try parsing the whole response as JSON
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    raise ValueError(f"Could not extract JSON from response: {text[:200]}")


def build_tree_index(pdf_path: Path, force: bool = False) -> dict:
    """Build a hierarchical tree index for a PDF document.

    The tree captures the document's structure (sections, subsections) with
    page ranges and summaries. This enables reasoning-based retrieval without
    vector embeddings.

    Args:
        pdf_path: Path to the PDF file.
        force: If True, rebuild even if a cached index exists.

    Returns:
        The tree index dict, also saved to .pageindex.json alongside the PDF.
    """
    index_path = pdf_path.parent / INDEX_FILENAME

    # Return cached index if valid
    if not force and index_path.exists():
        try:
            cached = json.loads(index_path.read_text())
            if cached.get("version") == INDEX_VERSION:
                return cached
        except (json.JSONDecodeError, OSError):
            pass

    # Extract page text
    pages = _extract_pages(pdf_path)
    if not pages:
        raise ValueError(f"No text extracted from {pdf_path}")

    total_pages = len(pages)

    # Build the tree in chunks if the document is large
    if total_pages <= MAX_PAGES_PER_CHUNK:
        tree = _build_tree_single_pass(pages)
    else:
        tree = _build_tree_chunked(pages)

    # Construct the index
    index = {
        "version": INDEX_VERSION,
        "total_pages": total_pages,
        "tree": tree,
    }

    # Save to disk
    try:
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    except OSError:
        pass

    return index


def _build_tree_single_pass(pages: list[dict]) -> list[dict]:
    """Build the tree from all pages in a single LLM call (for short documents)."""
    # Format pages for the prompt
    page_texts = []
    for p in pages:
        page_texts.append(f"=== PAGE {p['page_num']} ===\n{p['text'][:2000]}")

    document_text = "\n\n".join(page_texts)

    prompt = f"""Analyze this academic document and generate a hierarchical table of contents tree structure.

For each section, provide:
- "title": The section/subsection heading
- "start_page": First page number of this section
- "end_page": Last page number of this section
- "summary": A 1-2 sentence summary of what this section covers
- "children": Array of subsections (same format, can be empty)

The tree should capture the document's logical structure: Introduction, Methods, Results, Discussion, etc.
Include subsections where they exist. Every page should be covered by at least one section.

Return ONLY valid JSON (no markdown, no explanation) in this format:
[
  {{
    "title": "Section Title",
    "start_page": 1,
    "end_page": 3,
    "summary": "Brief summary of this section",
    "children": [
      {{
        "title": "Subsection",
        "start_page": 1,
        "end_page": 2,
        "summary": "Brief summary",
        "children": []
      }}
    ]
  }}
]

DOCUMENT ({len(pages)} pages):

{document_text}"""

    response = _call_gemini(prompt)
    return _extract_json_from_response(response)


def _build_tree_chunked(pages: list[dict]) -> list[dict]:
    """Build the tree in chunks for large documents, then merge."""
    chunks = []
    for i in range(0, len(pages), MAX_PAGES_PER_CHUNK):
        chunk_pages = pages[i:i + MAX_PAGES_PER_CHUNK]
        chunks.append(chunk_pages)

    # Build partial trees for each chunk
    partial_trees = []
    for chunk in chunks:
        try:
            tree = _build_tree_single_pass(chunk)
            partial_trees.extend(tree)
        except Exception:
            # If a chunk fails, add a flat entry
            partial_trees.append({
                "title": f"Pages {chunk[0]['page_num']}-{chunk[-1]['page_num']}",
                "start_page": chunk[0]["page_num"],
                "end_page": chunk[-1]["page_num"],
                "summary": "Section structure could not be determined.",
                "children": [],
            })

    # Merge overlapping sections
    return _merge_partial_trees(partial_trees)


def _merge_partial_trees(trees: list[dict]) -> list[dict]:
    """Merge partial trees from chunked processing, removing duplicates."""
    if not trees:
        return []

    merged = []
    seen_titles = set()

    for node in trees:
        title = node.get("title", "").lower().strip()
        start = node.get("start_page", 0)
        key = f"{title}:{start}"

        if key not in seen_titles:
            seen_titles.add(key)
            merged.append(node)

    # Sort by start_page
    merged.sort(key=lambda n: n.get("start_page", 0))
    return merged


def build_collection_index(
    collection_name: str,
    entries: list[dict],
    library_dir: Path,
    force: bool = False,
) -> dict:
    """Build a meta-index for a collection: paper summaries + their section trees.

    This enables reasoning over multiple papers in a collection — the LLM can
    first pick which papers are relevant, then drill into their sections.

    Args:
        collection_name: Name of the collection.
        entries: List of entry dicts from the library.
        library_dir: Path to the library directory.
        force: If True, rebuild even if cached.

    Returns:
        The collection index dict.
    """
    index_path = library_dir / ".collections" / f"{collection_name}{COLLECTION_INDEX_FILENAME}"

    if not force and index_path.exists():
        try:
            cached = json.loads(index_path.read_text())
            if cached.get("version") == INDEX_VERSION:
                return cached
        except (json.JSONDecodeError, OSError):
            pass

    papers = []
    for entry in entries:
        entry_id = entry.get("id", "")
        entry_dir = library_dir / entry_id
        pdf_files = [f for f in entry.get("files", []) if f.endswith(".pdf")]

        # Get or build the paper's tree index
        paper_tree = None
        if pdf_files:
            pdf_path = entry_dir / pdf_files[0]
            if pdf_path.exists():
                try:
                    paper_index = build_tree_index(pdf_path)
                    paper_tree = paper_index.get("tree", [])
                except Exception:
                    pass

        # Build paper summary for the meta-index
        sections = []
        if paper_tree:
            for node in paper_tree:
                sections.append({
                    "title": node.get("title", ""),
                    "pages": f"{node.get('start_page', '?')}-{node.get('end_page', '?')}",
                    "summary": node.get("summary", ""),
                })

        papers.append({
            "id": entry_id,
            "title": entry.get("title", ""),
            "authors": ", ".join(
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in entry.get("author", [])[:3]
            ),
            "year": (entry.get("date") or "").split("-")[0],
            "abstract": (entry.get("abstract") or "")[:300],
            "sections": sections,
            "has_pdf": bool(pdf_files),
        })

    index = {
        "version": INDEX_VERSION,
        "collection": collection_name,
        "paper_count": len(papers),
        "papers": papers,
    }

    # Save to disk
    index_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2))
    except OSError:
        pass

    return index


def get_cached_index(entry_dir: Path) -> dict | None:
    """Load a cached tree index for an entry if it exists."""
    index_path = entry_dir / INDEX_FILENAME
    if not index_path.exists():
        return None
    try:
        data = json.loads(index_path.read_text())
        if data.get("version") == INDEX_VERSION:
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None
