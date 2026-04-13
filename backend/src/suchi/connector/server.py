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
import logging

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from .. import library
from .. import collections as col_service

# Track the currently selected collection in the Suchi UI.
# When the user selects a collection in the sidebar, the UI calls
# POST /connector/setSelectedCollection to update this.
# The Zotero Connector then calls GET /connector/getSelectedCollection
# and saves items into that collection.
_selected_collection_id: str | None = None
_selected_collection_name: str = "My Library"

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
    global _selected_collection_id, _selected_collection_name
    body = await request.json()
    items = body.get("items", [])
    if not items:
        return _add_zotero_headers(JSONResponse(
            {"error": "NoItems", "message": "No items to save"},
            status_code=400,
        ))

    # Determine which collection to save into, in priority order:
    # 1. Explicit target from the connector dropdown (prefixed "C<id>")
    # 2. The currently selected collection in the Suchi UI (_selected_collection_id)
    # 3. No collection (root library)
    target = body.get("target") or body.get("uri", "")
    target_collection = None
    if isinstance(target, str) and target.startswith("C"):
        target_collection = target[1:]  # Strip "C" prefix
    elif _selected_collection_id:
        target_collection = _selected_collection_id

    saved = []
    for item in items:
        try:
            entry = _zotero_item_to_suchi(item)
            # Set target collection
            if target_collection:
                entry["collections"] = [target_collection]
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
        "collections": [_selected_collection_id] if _selected_collection_id else [],
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
    """Tell the connector which collection is currently selected and provide
    the full collection tree for the dropdown picker.

    The Zotero Connector uses the `targets` array to populate a dropdown
    that lets users pick which collection to save into.
    """
    global _selected_collection_id, _selected_collection_name

    # Build the targets list from our collection tree
    targets = _build_targets()

    selected_id = f"C{_selected_collection_id}" if _selected_collection_id else "L1"
    selected_name = _selected_collection_name if _selected_collection_id else "My Library"

    resp = JSONResponse({
        "id": selected_id,
        "name": selected_name,
        "libraryID": 1,
        "libraryEditable": True,
        "filesEditable": True,
        "targets": targets,
    })
    return _add_zotero_headers(resp)


def _build_targets() -> list[dict]:
    """Build the targets array for the Zotero Connector collection picker.

    Format: [{id: "L1" or "C<id>", name: "...", level: 0-N, filesEditable: true}]
    "L" prefix = library root, "C" prefix = collection.
    Level indicates nesting depth (0 = root library, 1 = top collection, 2+ = subcollection).
    """
    # Start with the root library
    targets = [{
        "id": "L1",
        "name": "My Library",
        "level": 0,
        "filesEditable": True,
    }]

    # Get all collections from Suchi
    try:
        tree = col_service.get_collection_tree()
        _add_tree_targets(tree, targets, level=1)
    except Exception as e:
        logger.warning(f"Failed to load collections for connector: {e}")

    return targets


def _add_tree_targets(nodes: list[dict], targets: list[dict], level: int) -> None:
    """Recursively add collection tree nodes to the targets list (depth-first)."""
    for node in nodes:
        targets.append({
            "id": f"C{node['id']}",
            "name": node.get("name", node["id"]),
            "level": level,
            "filesEditable": True,
        })
        if node.get("children"):
            _add_tree_targets(node["children"], targets, level + 1)


@app.post("/connector/setSelectedCollection")
async def set_selected_collection(request: Request):
    """Called by the Suchi UI when the user selects a collection in the sidebar.

    This makes the Zotero Connector save papers into that collection.
    """
    global _selected_collection_id, _selected_collection_name
    body = await request.json()
    _selected_collection_id = body.get("id")
    _selected_collection_name = body.get("name", "My Library")

    # Also expose via the main Suchi API (port 9876)
    return _add_zotero_headers(JSONResponse({"ok": True, "collection": _selected_collection_name}))


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
        "collections": [_selected_collection_id] if _selected_collection_id else [],
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
