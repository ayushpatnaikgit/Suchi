"""Zotero Connector-compatible HTTP server on port 23119.

Implements the subset of the Zotero Connector Server protocol that the
browser extension uses to save items. This lets users install the official
Zotero Connector from the Chrome/Firefox store and have it save to Suchi.

Protocol reference:
  https://www.zotero.org/support/dev/client_coding/connector_http_server

Endpoints implemented:
  GET/POST /connector/ping          — health check
  POST     /connector/saveItems     — save translated items
  POST     /connector/saveSnapshot  — save a webpage snapshot
  POST     /connector/selectItems   — select from multiple items (auto-selects all)
  GET      /connector/getTranslatorCode — returns empty (translators are in the extension)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from .. import library
from ..config import get_config

logger = logging.getLogger("suchi.connector")

CONNECTOR_PORT = 23119

app = FastAPI(title="Suchi Zotero Connector", docs_url=None, redoc_url=None)

# CORS — the browser extension sends requests from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Zotero-API-Version"],
)


def _add_zotero_headers(response: Response) -> Response:
    response.headers["X-Zotero-Version"] = "7.0"
    response.headers["Zotero-API-Version"] = "3"
    return response


# ─── /connector/ping ───

@app.api_route("/connector/ping", methods=["GET", "POST"])
async def ping():
    """Tell the browser extension that Suchi is running."""
    resp = JSONResponse({
        "prefs": {
            "automaticSnapshots": False,
        },
    })
    return _add_zotero_headers(resp)


# Also respond to bare /ping for some connector versions
@app.api_route("/ping", methods=["GET", "POST"])
async def ping_bare():
    return await ping()


# ─── /connector/saveItems ───

@app.post("/connector/saveItems")
async def save_items(request: Request):
    """Save items sent by the Zotero Connector.

    The connector sends a JSON object with:
    - items: array of Zotero item objects
    - uri: the page URL
    - cookie: browser cookies (ignored)
    """
    body = await request.json()
    items = body.get("items", [])
    if not items:
        return _add_zotero_headers(JSONResponse(
            {"error": "NoItems", "message": "No items to save"},
            status_code=400,
        ))

    saved = []
    for item in items:
        try:
            entry = _zotero_item_to_suchi(item)
            result = library.add_entry_manual(entry)

            # Download PDF attachments if available
            pdf_urls = _extract_pdf_urls(item)
            if pdf_urls and result:
                asyncio.create_task(_download_first_pdf(result["id"], pdf_urls))

            saved.append({"id": result["id"], "title": result.get("title", "")})
            logger.info(f"Saved from connector: {result.get('title', '')[:60]}")
        except Exception as e:
            logger.error(f"Failed to save item: {e}")

    resp = JSONResponse({"items": saved})
    return _add_zotero_headers(resp)


# ─── /connector/saveSnapshot ───

@app.post("/connector/saveSnapshot")
async def save_snapshot(request: Request):
    """Save a webpage snapshot. We save it as a basic entry with the URL."""
    body = await request.json()
    url = body.get("url") or body.get("uri", "")
    title = body.get("title", url)

    entry = {
        "type": "webpage",
        "title": title,
        "url": url,
        "author": [],
        "tags": [],
        "collections": [],
    }

    result = library.add_entry_manual(entry)
    logger.info(f"Saved snapshot: {title[:60]}")

    resp = JSONResponse({"id": result["id"]})
    return _add_zotero_headers(resp)


# ─── /connector/selectItems ───

@app.post("/connector/selectItems")
async def select_items(request: Request):
    """When multiple items are found, the connector asks which to save.

    We auto-select all of them (Zotero shows a dialog, but for simplicity
    we save everything).
    """
    body = await request.json()
    # Return all item keys as selected
    selected = {}
    for key, title in body.items():
        if isinstance(title, str):
            selected[key] = title

    resp = JSONResponse(selected)
    return _add_zotero_headers(resp)


# ─── /connector/getTranslatorCode ───

@app.get("/connector/getTranslatorCode")
async def get_translator_code(translatorID: str = ""):
    """Return translator code. The translators are bundled in the extension,
    so we return empty. Some connector versions call this as a fallback."""
    return _add_zotero_headers(Response(content="", media_type="text/javascript"))


# ─── /connector/getSelectedCollection ───

@app.api_route("/connector/getSelectedCollection", methods=["GET", "POST"])
async def get_selected_collection():
    """Tell the connector which collection is currently selected.
    Returns a dummy response — items go to the root library."""
    resp = JSONResponse({
        "id": "root",
        "name": "My Library",
    })
    return _add_zotero_headers(resp)


# ─── Conversion helpers ───

def _zotero_item_to_suchi(item: dict) -> dict:
    """Convert a Zotero item object to Suchi's metadata format."""
    # Map Zotero item types to Suchi types
    type_map = {
        "journalArticle": "article",
        "book": "book",
        "bookSection": "inbook",
        "conferencePaper": "inproceedings",
        "thesis": "thesis",
        "report": "report",
        "webpage": "webpage",
        "preprint": "article",
        "newspaperArticle": "article",
        "magazineArticle": "article",
        "encyclopediaArticle": "article",
        "patent": "patent",
        "dataset": "dataset",
    }

    # Extract authors
    authors = []
    for creator in item.get("creators", []):
        if creator.get("creatorType") in ("author", "contributor", "editor"):
            authors.append({
                "family": creator.get("lastName", ""),
                "given": creator.get("firstName", ""),
            })

    # Extract tags
    tags = []
    for tag_obj in item.get("tags", []):
        tag = tag_obj.get("tag", "") if isinstance(tag_obj, dict) else str(tag_obj)
        if tag:
            tags.append(tag.lower())

    entry = {
        "type": type_map.get(item.get("itemType", ""), "article"),
        "title": item.get("title", ""),
        "author": authors,
        "doi": item.get("DOI", "") or None,
        "isbn": item.get("ISBN", "") or None,
        "date": item.get("date", "") or None,
        "journal": item.get("publicationTitle", "") or item.get("journalAbbreviation", "") or None,
        "volume": item.get("volume", "") or None,
        "issue": item.get("issue", "") or None,
        "pages": item.get("pages", "") or None,
        "publisher": item.get("publisher", "") or None,
        "abstract": item.get("abstractNote", "") or None,
        "url": item.get("url", "") or None,
        "tags": tags,
        "collections": [],
    }

    # Clean up None/empty values
    return {k: v for k, v in entry.items() if v is not None and v != ""}


def _extract_pdf_urls(item: dict) -> list[str]:
    """Extract PDF URLs from a Zotero item's attachments."""
    urls = []

    # Check item-level PDF URL
    for key in ("url", "attachment.url"):
        url = item.get(key, "")
        if url and url.lower().endswith(".pdf"):
            urls.append(url)

    # Check attachments array
    for att in item.get("attachments", []):
        url = att.get("url", "")
        mime = att.get("mimeType", "")
        if url and ("pdf" in mime.lower() or url.lower().endswith(".pdf")):
            urls.append(url)

    return urls


async def _download_first_pdf(entry_id: str, pdf_urls: list[str]):
    """Download the first available PDF for an entry."""
    import httpx

    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        return

    for url in pdf_urls:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    pdf_path = entry_dir / "document.pdf"
                    pdf_path.write_bytes(resp.content)
                    library.attach_file(entry_id, pdf_path)
                    logger.info(f"Downloaded PDF for {entry_id}")
                    return
        except Exception as e:
            logger.debug(f"Failed to download PDF from {url}: {e}")
            continue


# ─── Server entry point ───

def start_connector_server(port: int = CONNECTOR_PORT):
    """Start the Zotero Connector-compatible server."""
    logger.info(f"Starting Zotero Connector shim on port {port}")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
