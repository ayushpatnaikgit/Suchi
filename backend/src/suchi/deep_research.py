"""Deep Research — autonomous web research powered by Gemini 3.1 Pro.

Uses Google's Interactions API (Deep Research agent) to browse 80-160 web
sources and produce comprehensive research reports with citations.

Two tiers:
  - Quick: ~80 sources, 2-3 min, ~$1-3
  - Max:   ~160 sources, 5-15 min, ~$3-7

Flow in Suchi:
  1. First answer from the user's library (PageIndex RAG — free, instant)
  2. If the user wants more, trigger Deep Research with library context
  3. Parse discovered papers from the report → resolve via OpenAlex/CrossRef
  4. Return report + "Add to Library" buttons for each new paper

Inspired by the flow: library-first, web-second.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from .config import get_config
from . import library
from . import collections as col_service

logger = logging.getLogger("suchi.deep-research")

# Agent IDs for the two tiers
AGENT_QUICK = "deep-research-preview-04-2026"
AGENT_MAX = "deep-research-max-preview-04-2026"


@dataclass
class DeepResearchResult:
    """Result from a Deep Research query."""
    report: str                           # Full markdown report
    sources_count: int = 0                # Number of web sources consulted
    discovered_papers: list[dict] = field(default_factory=list)  # Papers found
    duration_seconds: float = 0.0
    interaction_id: str = ""              # For follow-up queries
    tier: str = "quick"                   # "quick" or "max"


def _get_client():
    """Get a Google GenAI client using the configured API key."""
    config = get_config()
    api_key = config.ai.gemini_api_key
    if not api_key:
        raise ValueError("Gemini API key not configured. Set it in Settings or via: suchi config set ai.gemini_api_key YOUR_KEY")

    from google import genai
    return genai.Client(api_key=api_key)


def _build_library_context(
    collection_id: str | None = None,
    entry_id: str | None = None,
    max_papers: int = 30,
) -> str:
    """Build context from the user's library to send with the research query."""
    context_parts = []

    if entry_id:
        # Context from a single paper
        entry = library.get_entry(entry_id)
        if entry:
            authors = ", ".join(f"{a.get('given', '')} {a.get('family', '')}".strip() for a in entry.get("author", []))
            context_parts.append(f"The user is looking at this paper:")
            context_parts.append(f"  Title: {entry.get('title', '')}")
            context_parts.append(f"  Authors: {authors}")
            if entry.get("date"): context_parts.append(f"  Date: {entry['date']}")
            if entry.get("journal"): context_parts.append(f"  Journal: {entry['journal']}")
            if entry.get("doi"): context_parts.append(f"  DOI: {entry['doi']}")
            if entry.get("abstract"): context_parts.append(f"  Abstract: {entry['abstract'][:500]}")
            context_parts.append("")

    if collection_id:
        # Context from a collection
        flat = col_service.get_collections_flat()
        # Get all entries in this collection + subcollections
        descendant_ids = {collection_id}
        changed = True
        while changed:
            changed = False
            for c in flat:
                if c.get("parent_id") in descendant_ids and c["id"] not in descendant_ids:
                    descendant_ids.add(c["id"])
                    changed = True

        all_entries = library.list_entries(limit=10000)
        col_entries = [e for e in all_entries if any(c in descendant_ids for c in e.get("collections", []))]

        col = col_service.get_collection(collection_id)
        col_name = col["name"] if col else collection_id

        context_parts.append(f"The user's collection '{col_name}' contains {len(col_entries)} papers:")
        for e in col_entries[:max_papers]:
            authors = ", ".join(a.get("family", "") for a in e.get("author", [])[:3])
            year = (e.get("date", "") or "").split("-")[0]
            context_parts.append(f"  - {e.get('title', '')} ({authors}, {year})")
            if e.get("abstract"):
                context_parts.append(f"    Abstract: {e['abstract'][:200]}")
        if len(col_entries) > max_papers:
            context_parts.append(f"  ... and {len(col_entries) - max_papers} more papers")
        context_parts.append("")

    if not context_parts:
        # No specific context — provide a general library summary
        entries = library.list_entries(limit=10000)
        tags = library.get_all_tags()
        collections = library.get_all_collections()
        context_parts.append(f"The user's library has {len(entries)} papers across {len(collections)} collections.")
        if tags:
            context_parts.append(f"Top topics: {', '.join(tags[:15])}")
        context_parts.append("")

    return "\n".join(context_parts)


async def deep_research(
    query: str,
    collection_id: str | None = None,
    entry_id: str | None = None,
    tier: str = "quick",
    previous_interaction_id: str | None = None,
) -> DeepResearchResult:
    """Run a Deep Research query using Google's Interactions API.

    Args:
        query: The research question.
        collection_id: Scope the research to a specific collection.
        entry_id: Scope the research to a specific paper.
        tier: "quick" (~$1-3, 80 sources) or "max" (~$3-7, 160 sources).
        previous_interaction_id: For follow-up questions on a previous research.

    Returns:
        DeepResearchResult with the full report, discovered papers, and metadata.
    """
    client = _get_client()
    agent = AGENT_MAX if tier == "max" else AGENT_QUICK

    # Build the prompt with library context
    library_context = _build_library_context(collection_id, entry_id)

    full_prompt = f"""You are a research assistant. The user has a reference library and needs help finding more relevant academic papers and research.

{library_context}

IMPORTANT INSTRUCTIONS:
- When you find relevant papers, include the full citation: authors, title, year, journal, and DOI if available.
- Clearly distinguish between papers already in the user's library vs newly discovered papers.
- Structure the report with clear sections and headings.
- At the end, include a section called "## Discovered Papers" with a list of new papers not in the user's library, each with:
  - Title
  - Authors
  - Year
  - DOI (if available)
  - One-line relevance note

USER'S RESEARCH QUESTION:
{query}"""

    start_time = time.time()

    try:
        # Create the interaction
        kwargs = {
            "input": full_prompt,
            "agent": agent,
            "background": True,
        }
        if previous_interaction_id:
            kwargs["previous_interaction_id"] = previous_interaction_id

        interaction = client.interactions.create(**kwargs)
        interaction_id = interaction.id
        logger.info(f"Deep Research started: {interaction_id} (tier={tier})")

        # Poll for completion
        max_wait = 900  # 15 minutes max
        poll_interval = 10
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            interaction = client.interactions.get(interaction_id)
            status = interaction.status

            if status == "completed":
                report = ""
                for output in interaction.outputs:
                    if hasattr(output, "text") and output.text is not None:
                        report += output.text
                    elif hasattr(output, "content") and output.content is not None:
                        report += str(output.content)

                duration = time.time() - start_time
                logger.info(f"Deep Research completed: {interaction_id} ({duration:.0f}s)")

                # Parse discovered papers from the report
                discovered = _parse_discovered_papers(report)

                # Resolve discovered papers via OpenAlex/CrossRef
                resolved = await _resolve_discovered_papers(discovered)

                return DeepResearchResult(
                    report=report,
                    sources_count=_count_sources(report),
                    discovered_papers=resolved,
                    duration_seconds=duration,
                    interaction_id=interaction_id,
                    tier=tier,
                )

            elif status == "failed":
                error_msg = getattr(interaction, "error", "Unknown error")
                logger.error(f"Deep Research failed: {error_msg}")
                raise RuntimeError(f"Deep Research failed: {error_msg}")

            logger.debug(f"Deep Research polling... ({elapsed}s, status={status})")

        raise TimeoutError(f"Deep Research timed out after {max_wait}s")

    except ImportError:
        raise ImportError(
            "google-genai package is required for Deep Research. "
            "Install it with: pip install google-genai"
        )


async def research_gaps(
    collection_id: str,
    tier: str = "quick",
) -> DeepResearchResult:
    """Analyze gaps in a collection and find missing papers.

    This is a specialized Deep Research query that focuses on identifying
    what's missing from the user's collection.
    """
    col = col_service.get_collection(collection_id)
    col_name = col["name"] if col else collection_id

    query = f"""Analyze the collection '{col_name}' and identify gaps:

1. What major topics or methodologies are well-covered?
2. What important subtopics, seminal papers, or methodological approaches are MISSING?
3. Are there recent papers (2023-2026) that should be included?
4. Are there foundational/classic papers that every collection on this topic should have?
5. What interdisciplinary connections are being missed?

For each gap, suggest specific papers with full citations (authors, title, year, DOI).
Be specific — don't just say "more papers on X", name the actual papers."""

    return await deep_research(
        query=query,
        collection_id=collection_id,
        tier=tier,
    )


def _parse_discovered_papers(report: str) -> list[dict]:
    """Extract paper references from the Deep Research report.

    Looks for the "Discovered Papers" section and parses individual papers.
    Also scans the full report for DOI patterns and paper-like references.
    """
    papers = []

    # Extract DOIs from the entire report
    doi_pattern = re.compile(r"10\.\d{4,9}/[^\s,;\"'<>\]\)]+")
    dois_found = set()
    for match in doi_pattern.finditer(report):
        doi = match.group().rstrip(".")
        if doi not in dois_found:
            dois_found.add(doi)
            papers.append({"doi": doi})

    # Try to parse structured paper entries from "Discovered Papers" section
    discovered_section = re.search(
        r"##\s*Discovered Papers.*?\n(.*?)(?:\n##|\Z)",
        report,
        re.DOTALL | re.IGNORECASE,
    )
    if discovered_section:
        section_text = discovered_section.group(1)
        # Parse each bullet/numbered item
        items = re.split(r"\n[-*•]\s+|\n\d+\.\s+", section_text)
        for item in items:
            item = item.strip()
            if len(item) < 20:
                continue

            paper = {}
            # Extract DOI if present
            doi_match = doi_pattern.search(item)
            if doi_match:
                paper["doi"] = doi_match.group().rstrip(".")

            # Extract title (often in bold or quotes)
            title_match = re.search(r"\*\*(.+?)\*\*|\"(.+?)\"", item)
            if title_match:
                paper["title"] = (title_match.group(1) or title_match.group(2)).strip()

            # Extract year
            year_match = re.search(r"\((\d{4})\)|\b(20[12]\d)\b", item)
            if year_match:
                paper["year"] = year_match.group(1) or year_match.group(2)

            if paper.get("title") or paper.get("doi"):
                paper["raw_text"] = item[:300]
                papers.append(paper)

    # Deduplicate by DOI
    seen_dois = set()
    unique = []
    for p in papers:
        doi = p.get("doi", "")
        if doi and doi in seen_dois:
            continue
        if doi:
            seen_dois.add(doi)
        unique.append(p)

    return unique


async def _resolve_discovered_papers(papers: list[dict]) -> list[dict]:
    """Resolve discovered papers via OpenAlex/CrossRef to get full metadata."""
    from .translators.openalex import search_by_doi as openalex_doi, search_by_title as openalex_title
    from .translators.crossref import resolve_doi as crossref_doi

    resolved = []
    for paper in papers[:20]:  # Cap at 20 to avoid rate limits
        try:
            result = None

            # Try DOI first
            if paper.get("doi"):
                result = await openalex_doi(paper["doi"])
                if not result:
                    result = await crossref_doi(paper["doi"])

            # Try title search
            if not result and paper.get("title"):
                result = await openalex_title(paper["title"])

            if result:
                # Check if already in library
                existing = library.search_entries(result.get("title", ""), limit=1)
                in_library = bool(existing and existing[0].get("title", "").lower().strip() == result.get("title", "").lower().strip())

                result["in_library"] = in_library
                result["library_id"] = existing[0]["id"] if in_library and existing else None
                result["raw_text"] = paper.get("raw_text", "")
                resolved.append(result)
            else:
                # Couldn't resolve — keep the raw data
                paper["in_library"] = False
                paper["resolved"] = False
                resolved.append(paper)

        except Exception as e:
            logger.debug(f"Failed to resolve paper: {e}")
            paper["in_library"] = False
            paper["resolved"] = False
            resolved.append(paper)

        # Small delay to avoid rate limiting
        await asyncio.sleep(0.2)

    return resolved


def _count_sources(report: str) -> int:
    """Estimate how many sources were consulted by counting URLs and citations."""
    urls = re.findall(r"https?://[^\s\)\"]+", report)
    return len(set(urls))
