"""BM25S search tool for querying pre-built sparse retrieval indices."""

import os

import bm25s
import Stemmer

_STEMMER = Stemmer.Stemmer("porter")
_INDEX_ROOT = os.environ.get("BM25_INDEX_ROOT", "/tmp/bm25_indices")


async def bm25_search(
    collection: str,
    query: str,
    k: int = 10,
) -> dict:
    """
    Search a BM25 collection by name and return the top-k results with scores.

    Args:
        collection: Name of the index to search.
        query: Search query string. Use newlines to separate multiple queries.
        k: Number of results per query. Defaults to 10.

    Returns:
        dict with a "queries" list on success; {"error": str} on failure.
    """
    try:
        index_dir = os.path.join(_INDEX_ROOT, collection)
        if not os.path.isdir(index_dir):
            return {"error": f"Collection not found: {collection}"}

        retriever = bm25s.BM25.load(index_dir, load_corpus=True, mmap=True)

        queries = [q.strip() for q in query.split("\n") if q.strip()]
        if not queries:
            return {"error": "No valid queries provided"}

        query_tokens = bm25s.tokenize(queries, stopwords="en", stemmer=_STEMMER)
        results, scores = retriever.retrieve(
            query_tokens, k=min(k, len(retriever.corpus))
        )

        all_results = []
        for qi, q in enumerate(queries):
            query_results = []
            for doc, score in zip(results[qi], scores[qi]):
                doc_id = doc.get("id", "") if isinstance(doc, dict) else str(doc)
                doc_text = doc.get("text", "") if isinstance(doc, dict) else ""
                query_results.append(
                    {
                        "id": doc_id,
                        "text": doc_text[:500] if len(doc_text) > 500 else doc_text,
                        "score": float(score),
                    }
                )
            all_results.append({"query": q, "results": query_results})

        return {"queries": all_results}

    except Exception as e:
        return {"error": f"BM25 search failed: {str(e)}"}
