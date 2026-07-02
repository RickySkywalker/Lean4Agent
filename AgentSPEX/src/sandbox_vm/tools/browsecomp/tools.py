"""BrowseComp-Plus retrieval tools for the sandbox MCP server.

Lazy-loads the BM25 index and corpus metadata from $VM_WORKSPACE/browsecomp_index/
on first tool call.
"""

import json
import os
from pathlib import Path
from typing import Dict

import bm25s
import Stemmer

_STEMMER = Stemmer.Stemmer("porter")

_retriever = None
_corpus_lookup = None
_loaded = False

_SNIPPET_MAX_CHARS = 2000
_DEFAULT_K = 5

_INDEX_SUBDIR = "browsecomp_index"
_CORPUS_META_FILENAME = "corpus_meta.jsonl"


def _get_index_dir() -> Path:
    workspace = os.environ.get("VM_WORKSPACE", "/workspace")
    return Path(workspace) / _INDEX_SUBDIR


def _ensure_loaded():
    """Lazy-load the BM25 index and corpus lookup on first use."""
    global _retriever, _corpus_lookup, _loaded
    if _loaded:
        return

    index_dir = _get_index_dir()
    corpus_meta_path = index_dir / _CORPUS_META_FILENAME

    if not index_dir.exists():
        raise FileNotFoundError(
            f"BrowseComp index not found at {index_dir}. "
            "Run the benchmark's index step first to build and copy the index."
        )

    _retriever = bm25s.BM25.load(str(index_dir), load_corpus=True, mmap=True)

    _corpus_lookup = {}
    if corpus_meta_path.exists():
        with open(corpus_meta_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    doc = json.loads(line)
                    _corpus_lookup[doc["id"]] = doc["text"]

    _loaded = True


async def browsecomp_search(query: str, k: int = _DEFAULT_K) -> list:
    """Search the BrowseComp-Plus corpus and return top-k results with docid, score, and snippet.

    Args:
        query: Search query string.
        k: Number of results to return. Defaults to 5.

    Returns:
        List of dicts with docid, score, and snippet fields.
    """
    try:
        _ensure_loaded()
    except FileNotFoundError as e:
        return [{"error": str(e)}]

    query_tokens = bm25s.tokenize([query], stopwords="en", stemmer=_STEMMER)
    results, scores = _retriever.retrieve(
        query_tokens, k=min(k, len(_retriever.corpus))
    )

    hits = []
    for doc, score in zip(results[0], scores[0]):
        docid = doc.get("id", "") if isinstance(doc, dict) else str(doc)
        text = doc.get("text", "") if isinstance(doc, dict) else ""
        snippet = text[:_SNIPPET_MAX_CHARS] if len(text) > _SNIPPET_MAX_CHARS else text
        hits.append(
            {
                "docid": docid,
                "score": round(float(score), 4),
                "snippet": snippet,
            }
        )

    return hits


async def browsecomp_get_document(docid: str) -> dict:
    """Retrieve the full text of a document by its ID from the BrowseComp-Plus corpus.

    Args:
        docid: Document ID to retrieve.

    Returns:
        Dict with docid and text fields, or error if not found.
    """
    try:
        _ensure_loaded()
    except FileNotFoundError as e:
        return {"error": str(e)}

    text = _corpus_lookup.get(str(docid))
    if text is None:
        return {"error": f"Document {docid} not found"}

    return {"docid": str(docid), "text": text}
