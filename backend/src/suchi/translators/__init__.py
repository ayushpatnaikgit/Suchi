"""Metadata translators for resolving DOIs, ISBNs, arXiv IDs, and URLs."""

from .crossref import resolve_doi
from .arxiv import resolve_arxiv
from .openlibrary import resolve_isbn
from .openalex import search_by_title as openalex_search, resolve_reference as openalex_resolve
from .resolver import resolve_identifier, IdentifierType, detect_identifier_type

__all__ = [
    "resolve_doi",
    "resolve_arxiv",
    "resolve_isbn",
    "resolve_identifier",
    "IdentifierType",
    "detect_identifier_type",
    "openalex_search",
    "openalex_resolve",
]
