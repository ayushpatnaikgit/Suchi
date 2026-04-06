"""PageIndex-style RAG: vectorless, reasoning-based document retrieval.

Inspired by VectifyAI/PageIndex (https://github.com/VectifyAI/PageIndex).
Uses LLM reasoning over hierarchical document trees instead of vector embeddings.
"""

from .indexer import build_tree_index, build_collection_index
from .retriever import retrieve_pages, retrieve_from_collection

__all__ = [
    "build_tree_index",
    "build_collection_index",
    "retrieve_pages",
    "retrieve_from_collection",
]
