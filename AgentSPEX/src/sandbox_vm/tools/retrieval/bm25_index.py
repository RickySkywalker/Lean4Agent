"""BM25S indexing tool for building sparse retrieval indices over document corpora."""

import os
from typing import List

import bm25s
import Stemmer

_STEMMER = Stemmer.Stemmer("porter")
_INDEX_ROOT = os.environ.get("BM25_INDEX_ROOT", "/tmp/bm25_indices")


async def bm25_index(
    collection: str,
    documents: List[str],
    method: str = "lucene",
    k1: float = 0.9,
    b: float = 0.4,
) -> dict:
    """
    Build a BM25 index over a list of documents and save it under the given collection name.

    Args:
        collection: Name for this index (e.g. "arxiv_papers", "codebase_docs").
        documents: List of plain-text strings to index.
        method: BM25 variant ("lucene", "robertson", "atire", "bm25+"). Defaults to "lucene".
        k1: Term-frequency saturation. Defaults to 0.9.
        b: Length normalization. Defaults to 0.4.

    Returns:
        dict with index_dir, collection, and num_documents on success; {"error": str} on failure.
    """
    try:
        if not documents:
            return {"error": "No documents to index"}

        corpus_texts = []
        corpus_meta = []
        for i, text in enumerate(documents):
            corpus_texts.append(str(text))
            corpus_meta.append({"id": str(i), "text": str(text)})

        corpus_tokens = bm25s.tokenize(corpus_texts, stopwords="en", stemmer=_STEMMER)

        retriever = bm25s.BM25(method=method, k1=k1, b=b)
        retriever.index(corpus_tokens)

        index_dir = os.path.join(_INDEX_ROOT, collection)
        os.makedirs(index_dir, exist_ok=True)
        retriever.save(index_dir, corpus=corpus_meta)

        return {
            "index_dir": index_dir,
            "collection": collection,
            "num_documents": len(corpus_texts),
        }

    except Exception as e:
        return {"error": f"BM25 indexing failed: {str(e)}"}
