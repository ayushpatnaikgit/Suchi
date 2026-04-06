"""Unified identifier resolver — detects type and dispatches to the right translator."""

import re
from enum import Enum

from .crossref import resolve_doi
from .arxiv import resolve_arxiv, extract_arxiv_id
from .openlibrary import resolve_isbn


class IdentifierType(Enum):
    DOI = "doi"
    ARXIV = "arxiv"
    ISBN = "isbn"
    URL = "url"
    UNKNOWN = "unknown"


DOI_PATTERN = re.compile(r"^10\.\d{4,9}/[^\s]+$|^https?://doi\.org/10\.\d{4,9}/[^\s]+$")
ISBN_PATTERN = re.compile(r"^(?:978|979)?[\d\-\s]{9,17}[\dXx]$")


def detect_identifier_type(identifier: str) -> IdentifierType:
    identifier = identifier.strip()

    if DOI_PATTERN.match(identifier):
        return IdentifierType.DOI

    if extract_arxiv_id(identifier):
        return IdentifierType.ARXIV

    cleaned_isbn = identifier.replace("-", "").replace(" ", "")
    if ISBN_PATTERN.match(identifier) or (cleaned_isbn.isdigit() and len(cleaned_isbn) in (10, 13)):
        return IdentifierType.ISBN

    if identifier.startswith("http://") or identifier.startswith("https://"):
        # Check if it's a DOI URL
        if "doi.org/" in identifier:
            return IdentifierType.DOI
        # Check if it's an arXiv URL
        if "arxiv.org/" in identifier:
            return IdentifierType.ARXIV
        return IdentifierType.URL

    return IdentifierType.UNKNOWN


async def resolve_identifier(identifier: str) -> dict | None:
    """Detect identifier type and resolve to metadata."""
    id_type = detect_identifier_type(identifier)

    if id_type == IdentifierType.DOI:
        return await resolve_doi(identifier)
    elif id_type == IdentifierType.ARXIV:
        return await resolve_arxiv(identifier)
    elif id_type == IdentifierType.ISBN:
        return await resolve_isbn(identifier)
    elif id_type == IdentifierType.URL:
        # Try DOI extraction from URL, then fall back
        # For now, attempt CrossRef search by URL
        return None

    return None
