"""Paper search tool integrating TinyScientist's paper search logic as a sandbox MCP tool."""

import os
from typing import Any, Dict, List, Optional

import requests

from sandbox_vm.tools.utils import _err, _ok


def _sanitize_text(x: Any) -> str:
    """
    Sanitize text fields returned by upstream APIs.
    In particular, strip NUL bytes ('\\x00') which can cause JSON files to be
    treated as binary and break downstream readers.
    """
    if x is None:
        return ""
    if not isinstance(x, str):
        x = str(x)
    # Remove embedded NULs; keep other unicode characters.
    return x.replace("\x00", "")


def _openalex_abstract_text(work: Dict[str, Any]) -> str:
    """
    Convert OpenAlex abstract_inverted_index to plain text.
    OpenAlex often does not provide a plain 'abstract' field, but does provide
    'abstract_inverted_index': {token: [positions...]}.
    """
    inv = work.get("abstract_inverted_index")
    if not inv:
        return ""
    tokens: List[tuple[int, str]] = []
    try:
        for word, positions in inv.items():
            for p in positions or []:
                try:
                    tokens.append((int(p), str(word)))
                except Exception:
                    continue
        if not tokens:
            return ""
        tokens.sort(key=lambda x: x[0])
        return " ".join(w for _, w in tokens).strip()
    except Exception:
        return ""


def paper_search(
    query: str,
    result_limit: int = 30,
    engine: str = "openalex",
    s2_api_key: Optional[str] = None,
) -> dict:
    """
    Search for academic papers using Semantic Scholar, arXiv, or OpenAlex.

    This tool integrates TinyScientist's paper search logic as a sandbox MCP tool.
    It supports multiple search engines with fallback mechanisms.

    Args:
        query: Search query string
        result_limit: Maximum number of results to return (default: 30)
        engine: Search engine to use: "semanticscholar", "openalex", or "arxiv" (default: "openalex")
        s2_api_key: Optional Semantic Scholar API key

    Returns:
        {
            "papers": List[Dict],  # List of paper dictionaries with title, abstract, authors, venue, year, etc.
            "formatted_string": str  # Formatted string for use in prompts
        } on success, or {"error": "error message"} on failure
    """
    try:
        if not query:
            return _err("INVALID_INPUT", message="Query cannot be empty")

        s2_api_key = s2_api_key or os.getenv("S2_API_KEY")

        papers = []

        if engine == "semanticscholar":
            papers = _search_semanticscholar(query, result_limit, s2_api_key)
            if (
                not papers and engine != "openalex"
            ):  # Fallback to OpenAlex if no results
                papers = _search_openalex(query, result_limit)
        elif engine == "openalex":
            papers = _search_openalex(query, result_limit)
        elif engine == "arxiv":
            papers = _search_arxiv(query, result_limit)
        else:
            return _err("INVALID_ENGINE", message=f"Unknown engine: {engine}")

        # Format papers for prompts (similar to TinyScientist's _format_paper_results)
        formatted_string = _format_paper_results(papers)

        return _ok(
            papers=papers,
            formatted_string=formatted_string,
            query=query,
            engine=engine,
            num_results=len(papers),
        )

    except Exception as e:
        return _err("EXECUTION_ERROR", message=f"Paper search failed: {str(e)}")


def _search_semanticscholar(
    query: str, result_limit: int, s2_api_key: Optional[str]
) -> List[Dict[str, Any]]:
    """Search Semantic Scholar API."""
    headers = {
        "User-Agent": "TinyScientist/1.0",
        "Accept": "application/json",
    }
    if s2_api_key:
        headers["x-api-key"] = s2_api_key

    params = {
        "query": query,
        "limit": result_limit,
        "fields": "title,authors,venue,year,abstract,citationCount,paperId",
    }

    try:
        response = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        results = response.json()

        papers = []
        for paper in results.get("data", [])[:result_limit]:
            authors = ", ".join(
                [_sanitize_text(a.get("name", "")) for a in paper.get("authors", [])]
            )
            papers.append(
                {
                    "title": _sanitize_text(paper.get("title", "")),
                    "abstract": _sanitize_text(paper.get("abstract", "")),
                    "authors": _sanitize_text(authors),
                    "venue": _sanitize_text(paper.get("venue", "")),
                    "year": paper.get("year", ""),
                    "citationCount": paper.get("citationCount", 0),
                }
            )
        return papers
    except Exception as e:
        print(f"Semantic Scholar search failed: {e}")
        return []


def _search_openalex(query: str, result_limit: int) -> List[Dict[str, Any]]:
    """Search OpenAlex API."""
    mail = os.getenv("OPENALEX_MAIL_ADDRESS")
    headers = {"User-Agent": f"mailto:{mail}" if mail else "TinyScientist/1.0"}

    params = {
        "search": query,
        "per_page": min(result_limit, 25),  # OpenAlex max per_page is 25
    }

    try:
        response = requests.get(
            "https://api.openalex.org/works",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        results = response.json()

        papers = []
        for work in results.get("results", [])[:result_limit]:
            abstract = work.get("abstract") or ""
            # OpenAlex commonly provides abstract_inverted_index instead of plain abstract text
            if not abstract:
                abstract = _openalex_abstract_text(work)
            authors = ", ".join(
                [
                    _sanitize_text(a.get("author", {}).get("display_name", ""))
                    for a in work.get("authorships", [])
                ]
            )
            papers.append(
                {
                    "title": _sanitize_text(work.get("title", "")),
                    "abstract": _sanitize_text(abstract),
                    "authors": _sanitize_text(authors),
                    "venue": _sanitize_text(
                        work.get("primary_location", {})
                        .get("source", {})
                        .get("display_name", "")
                    ),
                    "year": work.get("publication_year", ""),
                    "citationCount": work.get("cited_by_count", 0),
                }
            )
        return papers
    except Exception as e:
        print(f"OpenAlex search failed: {e}")
        return []


def _search_arxiv(query: str, result_limit: int) -> List[Dict[str, Any]]:
    """Search arXiv API."""
    import xml.etree.ElementTree as ET

    params = {
        "search_query": query,
        "start": 0,
        "max_results": result_limit,
    }

    try:
        response = requests.get(
            "http://export.arxiv.org/api/query",
            params=params,
            timeout=30,
        )
        response.raise_for_status()

        root = ET.fromstring(response.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        papers = []
        for entry in root.findall("atom:entry", ns):
            title = (
                entry.find("atom:title", ns).text
                if entry.find("atom:title", ns) is not None
                else ""
            )
            summary = (
                entry.find("atom:summary", ns).text
                if entry.find("atom:summary", ns) is not None
                else ""
            )
            authors = [
                _sanitize_text(a.find("atom:name", ns).text)
                for a in entry.findall("atom:author", ns)
                if a.find("atom:name", ns) is not None
            ]
            published = (
                entry.find("atom:published", ns).text
                if entry.find("atom:published", ns) is not None
                else ""
            )
            year = published[:4] if published else ""

            papers.append(
                {
                    "title": _sanitize_text(title),
                    "abstract": _sanitize_text(summary),
                    "authors": _sanitize_text(", ".join(authors)),
                    "venue": "arXiv",
                    "year": year,
                    "citationCount": 0,
                }
            )
        return papers
    except Exception as e:
        print(f"arXiv search failed: {e}")
        return []


def _format_paper_results(papers: List[Dict[str, Any]]) -> str:
    """Format paper results with title, authors, venue, and abstract (similar to TinyScientist)."""
    if not papers:
        return "No papers found."

    paper_strings = []
    for i, paper in enumerate(papers):
        title = paper.get("title", "No title")
        abstract = paper.get("abstract", "")

        # Format: Title. Authors. Venue.\nAbstract: ...
        paper_str = f"{i}: {title}."
        if abstract and len(abstract.strip()) > 0:
            # Truncate very long abstracts
            abstract_text = abstract.strip()
            if len(abstract_text) > 2000:
                abstract_text = abstract_text[:2000] + "..."
            paper_str += f"\nAbstract: {abstract_text}"

        paper_strings.append(paper_str)

    return "\n\n".join(paper_strings)
