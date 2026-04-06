"""AI Chat routes — chat with papers, collections, or selected text via Gemini."""

import base64

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import httpx
import fitz  # PyMuPDF

from .. import library
from .. import collections as col_service
from ..config import get_config
from ..translators.pdf_extract import extract_text_from_pdf
from pathlib import Path

router = APIRouter(prefix="/api/chat", tags=["chat"])

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    # Context — provide one of these:
    entry_id: str | None = None          # Chat with a specific paper
    collection_id: str | None = None     # Chat with all papers in a collection
    selected_text: str | None = None     # Chat about selected PDF text
    entry_id_for_selection: str | None = None  # Which paper the selection is from
    # Visual context — include current PDF page as an image
    page_number: int | None = None       # Current page being viewed (1-indexed)


def _render_page_image(entry_id: str, page_number: int) -> str | None:
    """Render a PDF page as a base64-encoded JPEG image for Gemini."""
    entry = library.get_entry(entry_id)
    if not entry:
        return None
    entry_dir = library.get_entry_dir(entry_id)
    if not entry_dir:
        return None
    pdfs = [f for f in entry.get("files", []) if f.endswith(".pdf")]
    if not pdfs:
        return None

    pdf_path = entry_dir / pdfs[0]
    try:
        doc = fitz.open(str(pdf_path))
        if page_number < 1 or page_number > doc.page_count:
            doc.close()
            return None
        page = doc[page_number - 1]
        # Render at 2x resolution for clarity
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg", jpg_quality=85)
        doc.close()
        return base64.b64encode(img_bytes).decode("ascii")
    except Exception:
        return None


@router.post("")
async def chat(req: ChatRequest):
    """Chat with Gemini about papers. Streams the response."""
    config = get_config()
    api_key = config.ai.gemini_api_key
    model = config.ai.model or "gemini-2.0-flash"

    if not api_key:
        raise HTTPException(400, "Gemini API key not configured. Go to Settings to add it.")

    # Build context
    system_prompt, context_text = _build_context(req)

    # Render current PDF page as an image if page_number is provided
    page_image_b64 = None
    eid = req.entry_id or req.entry_id_for_selection
    if req.page_number and eid:
        page_image_b64 = _render_page_image(eid, req.page_number)

    # Build Gemini request
    contents = []

    # System instruction as first user message with context + optional page image
    if context_text or page_image_b64:
        first_parts: list[dict] = []
        prompt_text = system_prompt
        if context_text:
            prompt_text += f"\n\n---\n\nHere is the research context:\n\n{context_text}"
        if page_image_b64:
            prompt_text += f"\n\nThe user is currently viewing page {req.page_number} of the PDF (image attached)."

        first_parts.append({"text": prompt_text})

        # Attach page image as inline data
        if page_image_b64:
            first_parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": page_image_b64,
                }
            })

        contents.append({"role": "user", "parts": first_parts})
        contents.append({
            "role": "model",
            "parts": [{"text": "I've reviewed the research material and the current page. How can I help you?"}]
        })

    # Add conversation history
    for msg in req.history:
        contents.append({
            "role": "user" if msg.role == "user" else "model",
            "parts": [{"text": msg.content}]
        })

    # Add current message
    contents.append({
        "role": "user",
        "parts": [{"text": req.message}]
    })

    # Call Gemini API with streaming
    url = f"{GEMINI_API}/{model}:streamGenerateContent?alt=sse&key={api_key}"

    async def stream_response():
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                url,
                json={
                    "contents": contents,
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 4096,
                    },
                },
            ) as response:
                if response.status_code != 200:
                    error_text = ""
                    async for chunk in response.aiter_text():
                        error_text += chunk
                    yield f"data: {_json_dumps({'error': error_text[:500]})}\n\n"
                    return

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            yield "data: [DONE]\n\n"
                            return
                        try:
                            import json
                            parsed = json.loads(data)
                            candidates = parsed.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for part in parts:
                                    text = part.get("text", "")
                                    if text:
                                        yield f"data: {_json_dumps({'text': text})}\n\n"
                        except Exception:
                            continue

                yield "data: [DONE]\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")


@router.post("/quick")
async def quick_chat(req: ChatRequest):
    """Non-streaming chat — returns full response at once."""
    config = get_config()
    api_key = config.ai.gemini_api_key
    model = config.ai.model or "gemini-2.0-flash"

    if not api_key:
        raise HTTPException(400, "Gemini API key not configured. Go to Settings to add it.")

    system_prompt, context_text = _build_context(req)

    contents = []
    if context_text:
        contents.append({
            "role": "user",
            "parts": [{"text": f"{system_prompt}\n\n---\n\n{context_text}"}]
        })
        contents.append({
            "role": "model",
            "parts": [{"text": "I've reviewed the material. How can I help?"}]
        })

    for msg in req.history:
        contents.append({
            "role": "user" if msg.role == "user" else "model",
            "parts": [{"text": msg.content}]
        })

    contents.append({"role": "user", "parts": [{"text": req.message}]})

    url = f"{GEMINI_API}/{model}:generateContent?key={api_key}"

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json={
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
        })

        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Gemini API error: {resp.text[:300]}")

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise HTTPException(500, "No response from Gemini")

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)

    return {"response": text}


@router.get("/page-image/{entry_id}/{page_number}")
async def get_page_image(entry_id: str, page_number: int):
    """Render a PDF page as a JPEG image. Used for visual context in chat."""
    img_b64 = _render_page_image(entry_id, page_number)
    if not img_b64:
        raise HTTPException(404, "Could not render page")
    import base64 as b64module
    from fastapi.responses import Response
    return Response(
        content=b64module.b64decode(img_b64),
        media_type="image/jpeg",
    )


def _build_context(req: ChatRequest) -> tuple[str, str]:
    """Build system prompt and context text based on what we're chatting about."""

    if req.selected_text:
        # Chat about selected PDF text
        entry = library.get_entry(req.entry_id_for_selection) if req.entry_id_for_selection else None
        paper_info = ""
        if entry:
            authors = ", ".join(f"{a.get('given','')} {a.get('family','')}".strip() for a in entry.get("author", []))
            paper_info = f"\nFrom: {entry.get('title', '')} by {authors} ({entry.get('date', '')})\n"

        system_prompt = (
            "You are a research assistant. The user has selected a passage from a research paper. "
            "Help them understand it. Explain jargon, give context, answer questions about the text. "
            "Be concise and scholarly. "
            "When referencing any paper by title, wrap it in double brackets like [[Paper Title Here]]."
        )
        context_text = f"{paper_info}\nSelected text:\n\"\"\"\n{req.selected_text}\n\"\"\""
        return system_prompt, context_text

    if req.entry_id:
        # Chat with a specific paper
        entry = library.get_entry(req.entry_id)
        if not entry:
            return "You are a research assistant.", ""

        authors = ", ".join(f"{a.get('given','')} {a.get('family','')}".strip() for a in entry.get("author", []))
        meta = f"Title: {entry.get('title', '')}\nAuthors: {authors}\nDate: {entry.get('date', '')}\n"
        if entry.get("journal"): meta += f"Journal: {entry['journal']}\n"
        if entry.get("doi"): meta += f"DOI: {entry['doi']}\n"
        if entry.get("abstract"): meta += f"\nAbstract:\n{entry['abstract']}\n"
        if entry.get("tags"): meta += f"\nTags: {', '.join(entry['tags'])}\n"

        # Try PageIndex-style retrieval first (reasoning over tree index)
        context_text = meta
        used_pageindex = False

        entry_dir = library.get_entry_dir(req.entry_id)
        pdfs = [f for f in entry.get("files", []) if f.endswith(".pdf")]
        if entry_dir and pdfs:
            pdf_path = entry_dir / pdfs[0]
            try:
                from ..pageindex.retriever import retrieve_pages
                from ..pageindex.indexer import get_cached_index

                # Only use PageIndex if the tree index exists (don't auto-build during chat)
                cached_index = get_cached_index(entry_dir)
                if cached_index:
                    pages = retrieve_pages(req.message, pdf_path, tree_index=cached_index, max_pages=5)
                    if pages:
                        context_text += "\n\n--- RELEVANT PAGES (retrieved via PageIndex reasoning) ---\n"
                        for p in pages:
                            context_text += f"\n=== PAGE {p['page_num']} ===\n"
                            if p.get("relevance_reason"):
                                context_text += f"[Relevant because: {p['relevance_reason']}]\n"
                            context_text += p["text"] + "\n"
                        used_pageindex = True
            except Exception:
                pass

        if not used_pageindex:
            # Fallback: full paper text (truncated)
            paper_text = _get_paper_text(entry)
            if paper_text:
                context_text += f"\n\nFull paper text:\n{paper_text[:30000]}"

        rag_note = ""
        if used_pageindex:
            rag_note = (
                "The context below contains ONLY the most relevant pages from the paper, "
                "selected by reasoning over the paper's structure. If you need information "
                "from other sections, mention which section would help. "
            )

        system_prompt = (
            "You are a research assistant helping the user understand a specific research paper. "
            f"{rag_note}"
            "Answer questions about the paper's methodology, findings, implications, and context. "
            "Cite specific page numbers when relevant (e.g., 'on page 5...'). Be concise and scholarly. "
            "IMPORTANT: When referencing this or any other paper by title, always wrap the EXACT title in double brackets like [[Paper Title Here]]. "
            "This creates a clickable link in the UI."
        )

        return system_prompt, context_text

    if req.collection_id:
        # Chat with a collection — provide summaries of all papers
        flat = col_service.get_collections_flat()
        # Get all entries in this collection + subcollections
        descendant_ids = {req.collection_id}
        changed = True
        while changed:
            changed = False
            for c in flat:
                if c.get("parent_id") in descendant_ids and c["id"] not in descendant_ids:
                    descendant_ids.add(c["id"])
                    changed = True

        entries = library.list_entries(limit=10000)
        col_entries = [e for e in entries if any(c in descendant_ids for c in e.get("collections", []))]

        col = col_service.get_collection(req.collection_id)
        col_name = col["name"] if col else req.collection_id

        # Try PageIndex collection-level retrieval
        used_pageindex = False
        context_text = ""

        try:
            from ..pageindex.retriever import retrieve_from_collection
            from ..pageindex.indexer import COLLECTION_INDEX_FILENAME
            import json

            config = get_config()
            lib_dir = config.library_dir
            col_index_path = lib_dir / ".collections" / f"{req.collection_id}{COLLECTION_INDEX_FILENAME}"

            if col_index_path.exists():
                col_index = json.loads(col_index_path.read_text())
                pages = retrieve_from_collection(
                    req.message, col_index, lib_dir,
                    max_papers=3, max_pages_per_paper=3,
                )
                if pages:
                    context_text = f"Collection: {col_name} ({len(col_entries)} papers)\n"
                    context_text += "\n--- RELEVANT PAGES (retrieved via PageIndex reasoning) ---\n"
                    current_entry = ""
                    for p in pages:
                        if p.get("entry_id") != current_entry:
                            current_entry = p.get("entry_id", "")
                            context_text += f"\n\n=== FROM: {p.get('entry_title', current_entry)} ===\n"
                        context_text += f"\n--- PAGE {p['page_num']} ---\n"
                        if p.get("relevance_reason"):
                            context_text += f"[Relevant because: {p['relevance_reason']}]\n"
                        context_text += p["text"] + "\n"
                    used_pageindex = True
        except Exception:
            pass

        if not used_pageindex:
            # Fallback: paper summaries only
            papers_summary = ""
            for e in col_entries:
                authors = ", ".join(a.get("family", "") for a in e.get("author", [])[:3])
                year = (e.get("date", "") or "").split("-")[0]
                papers_summary += f"\n- {e.get('title', '')} ({authors}, {year})"
                if e.get("abstract"):
                    papers_summary += f"\n  Abstract: {e['abstract'][:300]}"
                papers_summary += "\n"
            context_text = f"Collection: {col_name}\nPapers ({len(col_entries)}):\n{papers_summary}"

        rag_note = ""
        if used_pageindex:
            rag_note = (
                "The context below contains relevant pages from the most relevant papers in this collection, "
                "selected by reasoning over each paper's structure. Cite specific papers and pages when answering. "
            )

        system_prompt = (
            f"You are a research assistant. The user is working with a collection of papers called '{col_name}' "
            f"containing {len(col_entries)} papers. {rag_note}"
            "Help them synthesize, compare, find gaps, "
            "identify themes, and answer questions about this body of research. "
            "IMPORTANT: When referencing any paper by title, always wrap the EXACT title in double brackets like [[Paper Title Here]]. "
            "This creates a clickable link in the UI. Use the exact titles from the context provided."
        )

        return system_prompt, context_text

    # General chat — no specific context
    system_prompt = (
        "You are a research assistant integrated into Suchi, a reference manager. "
        "Help the user with research questions, methodology advice, writing help, "
        "and understanding academic concepts. "
        "When referencing any paper by title, wrap it in double brackets like [[Paper Title Here]]."
    )
    return system_prompt, ""


def _get_paper_text(entry: dict) -> str | None:
    """Extract full text from a paper's PDF."""
    entry_dir = library.get_entry_dir(entry.get("id", ""))
    if not entry_dir:
        return None

    pdfs = [f for f in entry.get("files", []) if f.endswith(".pdf")]
    if not pdfs:
        return None

    pdf_path = entry_dir / pdfs[0]
    if not pdf_path.exists():
        return None

    try:
        return extract_text_from_pdf(pdf_path, max_pages=50)
    except Exception:
        return None


def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj)
