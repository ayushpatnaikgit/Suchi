"""FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import entries, search, export, collections, settings, chat, citations, references, pdf_finder, annotations, discovery, sync, deep_research
from . import library as lib_module
from .search import index_entry, remove_from_index, rebuild_index


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register search index hooks so entries are indexed on create/update/delete
    lib_module.set_index_hooks(
        on_added=index_entry,
        on_removed=remove_from_index,
    )
    # Build index on startup if needed
    rebuild_index()
    yield


app = FastAPI(
    title="Suchi",
    description="सूची — CLI-first reference manager with AI-powered research tools",
    version="0.1.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tauri webview + browser extension
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(entries.router)
app.include_router(search.router)
app.include_router(export.router)
app.include_router(collections.router)
app.include_router(settings.router)
app.include_router(chat.router)
app.include_router(citations.router)
app.include_router(references.router)
app.include_router(pdf_finder.router)
app.include_router(annotations.router)
app.include_router(discovery.router)
app.include_router(sync.router)
app.include_router(deep_research.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.1"}
