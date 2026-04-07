"""Reasoning-based retrieval using tree indices.

Instead of vector similarity, the LLM reasons over the document tree to find
relevant sections for a query. This mimics how a human expert would navigate
a document: look at the table of contents, pick the most relevant sections,
then read those pages.

Inspired by VectifyAI/PageIndex (https://github.com/VectifyAI/PageIndex).
"""

import json
from pathlib import Path

import fitz  # PyMuPDF

from .indexer import _call_gemini, _extract_json_from_response, get_cached_index


def retrieve_pages(
    query: str,
    pdf_path: Path,
    tree_index: dict | None = None,
    max_pages: int = 5,
) -> list[dict]:
    """Retrieve the most relevant pages from a PDF for a query using tree reasoning.

    Args:
        query: The user's question.
        pdf_path: Path to the PDF file.
        tree_index: Pre-loaded tree index (if None, loads from cache or builds).
        max_pages: Maximum number of pages to retrieve.

    Returns:
        List of dicts with: page_num, text, relevance_reason
    """
    # Load or build tree index
    if tree_index is None:
        tree_index = get_cached_index(pdf_path.parent)
    if tree_index is None:
        from .indexer import build_tree_index
        tree_index = build_tree_index(pdf_path)

    tree = tree_index.get("tree", [])
    total_pages = tree_index.get("total_pages", 0)

    if not tree:
        # Fallback: return first few pages
        return _extract_page_texts(pdf_path, list(range(1, min(6, total_pages + 1))))

    # Step 1: Ask LLM to pick relevant sections from the tree
    tree_summary = json.dumps(tree, indent=2, ensure_ascii=False)

    prompt = f"""Given this document structure (table of contents with summaries):

{tree_summary}

A user is asking: "{query}"

Which sections are most relevant to answer this question? Pick up to {max_pages} pages total.

Return ONLY valid JSON (no markdown) in this format:
{{
  "relevant_sections": [
    {{
      "title": "Section title from the tree",
      "pages": [3, 4, 5],
      "reason": "Brief explanation of why this section is relevant"
    }}
  ]
}}

Pick the most relevant sections. Be precise — only include sections that directly help answer the question."""

    try:
        response = _call_gemini(prompt)
        result = _extract_json_from_response(response)
    except Exception:
        # Fallback: return pages from the largest/first sections
        pages = _fallback_pages(tree, max_pages)
        return _extract_page_texts(pdf_path, pages)

    # Step 2: Collect the page numbers
    selected_pages = set()
    reasons = {}

    for section in result.get("relevant_sections", []):
        for page in section.get("pages", []):
            if isinstance(page, int) and 1 <= page <= total_pages:
                selected_pages.add(page)
                reasons[page] = section.get("reason", "")

    if not selected_pages:
        pages = _fallback_pages(tree, max_pages)
        return _extract_page_texts(pdf_path, pages)

    # Limit to max_pages
    sorted_pages = sorted(selected_pages)[:max_pages]

    # Step 3: Extract the actual text from those pages
    page_texts = _extract_page_texts(pdf_path, sorted_pages)

    # Add relevance reasons
    for pt in page_texts:
        pt["relevance_reason"] = reasons.get(pt["page_num"], "")

    return page_texts


def retrieve_from_collection(
    query: str,
    collection_index: dict,
    library_dir: Path,
    max_papers: int = 3,
    max_pages_per_paper: int = 3,
) -> list[dict]:
    """Retrieve relevant pages from across a collection of papers.

    Two-level reasoning:
    1. Pick the most relevant papers from the collection
    2. For each selected paper, pick the most relevant pages

    Args:
        query: The user's question.
        collection_index: The collection meta-index.
        library_dir: Path to the library root.
        max_papers: Maximum number of papers to select.
        max_pages_per_paper: Maximum pages per paper.

    Returns:
        List of dicts with: entry_id, entry_title, page_num, text, relevance_reason
    """
    papers = collection_index.get("papers", [])
    if not papers:
        return []

    # Step 1: Ask LLM to pick relevant papers
    paper_summaries = []
    for p in papers:
        sections = ", ".join(s.get("title", "") for s in p.get("sections", [])[:5])
        paper_summaries.append({
            "id": p["id"],
            "title": p["title"],
            "authors": p.get("authors", ""),
            "year": p.get("year", ""),
            "abstract": p.get("abstract", "")[:200],
            "sections": sections,
        })

    prompt = f"""Given this collection of {len(papers)} papers:

{json.dumps(paper_summaries, indent=2, ensure_ascii=False)}

A user is asking: "{query}"

Which papers are most relevant? Pick up to {max_papers} papers.

Return ONLY valid JSON:
{{
  "relevant_papers": [
    {{
      "id": "paper-entry-id",
      "reason": "Why this paper is relevant"
    }}
  ]
}}"""

    try:
        response = _call_gemini(prompt)
        result = _extract_json_from_response(response)
    except Exception:
        # Fallback: use first few papers
        result = {"relevant_papers": [{"id": p["id"], "reason": ""} for p in papers[:max_papers]]}

    selected_ids = [p["id"] for p in result.get("relevant_papers", [])][:max_papers]
    if not selected_ids:
        selected_ids = [papers[0]["id"]] if papers else []

    # Step 2: For each selected paper, retrieve relevant pages
    all_pages = []
    for entry_id in selected_ids:
        entry_dir = library_dir / entry_id
        pdfs = list(entry_dir.glob("*.pdf"))
        if not pdfs:
            continue

        # Get the paper's title
        paper_info = next((p for p in papers if p["id"] == entry_id), {})

        try:
            pages = retrieve_pages(
                query,
                pdfs[0],
                max_pages=max_pages_per_paper,
            )
            for page in pages:
                page["entry_id"] = entry_id
                page["entry_title"] = paper_info.get("title", "")
            all_pages.extend(pages)
        except Exception:
            continue

    return all_pages


def _extract_page_texts(pdf_path: Path, page_nums: list[int]) -> list[dict]:
    """Extract text from specific pages of a PDF."""
    doc = fitz.open(str(pdf_path))
    results = []
    for num in page_nums:
        if 1 <= num <= doc.page_count:
            text = doc[num - 1].get_text().strip()
            results.append({
                "page_num": num,
                "text": text[:4000],  # Cap to avoid token overflow
            })
    doc.close()
    return results


def _fallback_pages(tree: list[dict], max_pages: int) -> list[int]:
    """Pick pages from the tree when LLM reasoning fails."""
    pages = set()
    for node in tree:
        start = node.get("start_page", 1)
        end = node.get("end_page", start)
        for p in range(start, min(end + 1, start + 2)):
            pages.add(p)
        if len(pages) >= max_pages:
            break
    return sorted(pages)[:max_pages]
