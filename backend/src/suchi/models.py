"""Pydantic models for Suchi API."""

from pydantic import BaseModel


class Author(BaseModel):
    family: str
    given: str = ""


class EntryCreate(BaseModel):
    """Used when adding an entry manually."""
    type: str = "article"
    title: str
    author: list[Author] = []
    doi: str | None = None
    isbn: str | None = None
    date: str | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    abstract: str | None = None
    tags: list[str] = []
    collections: list[str] = []
    url: str | None = None


class EntryResponse(BaseModel):
    """Returned when listing/getting entries."""
    id: str  # directory name
    type: str
    title: str
    author: list[Author] = []
    doi: str | None = None
    isbn: str | None = None
    date: str | None = None
    journal: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    abstract: str | None = None
    tags: list[str] = []
    collections: list[str] = []
    url: str | None = None
    files: list[str] = []
    added: str | None = None
    modified: str | None = None


class AddByIdentifier(BaseModel):
    """Add entry by DOI, ISBN, arXiv ID, or URL."""
    identifier: str
    tags: list[str] = []
    collections: list[str] = []


class ExportRequest(BaseModel):
    entry_ids: list[str] = []  # Empty = export all
    format: str = "bibtex"  # bibtex, csl-json, ris


class SearchQuery(BaseModel):
    q: str
    tags: list[str] = []
    collections: list[str] = []
    limit: int = 50
