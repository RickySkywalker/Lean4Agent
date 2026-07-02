"""Citation pool builder — searches for related papers and builds a deduped BibTeX pool."""

import json
import os
import re
from pathlib import Path

from sandbox_vm.tools.research.reference import get_abstract_from_url, get_bibtex_from_url
from sandbox_vm.tools.utils import _err, _ok
from sandbox_vm.tools.web.web_search import firecrawl_search


async def search_citation_pool(
    sections_dir: str, output_dir: str, force: bool = False
) -> dict:
    """
    Build a citation pool by searching for related papers based on paper content.

    Reads .tex files to extract topic keywords, searches via Firecrawl, extracts
    BibTeX entries, deduplicates against existing references.bib, and saves
    citation_pool.json.

    If citation_pool.json already exists and is non-empty, returns cached result
    unless force=True.

    Args:
        sections_dir: Path to directory containing .tex files.
        output_dir: Path to output directory for citation_pool.json.
        force: If True, rebuild even if pool already exists (default False).

    Returns:
        {
            "ok": True,
            "message": str,  # e.g. "POOL_SAVED: 19 citations" or "CACHED: already has 19 entries"
            "pool_path": str,
            "count": int
        } or {"ok": False, "error": str, "message": str}

    Examples:
        >>> result = await search_citation_pool(
        ...     "/workspace/outputs/paper/sections",
        ...     "/workspace/outputs/paper/refiner")
        >>> print(result["message"])
        "POOL_SAVED: 19 citations to /workspace/.../citation_pool.json"
    """
    if not sections_dir or not isinstance(sections_dir, str):
        return _err("INVALID_INPUT", message="sections_dir must be a non-empty string")
    if not output_dir or not isinstance(output_dir, str):
        return _err("INVALID_INPUT", message="output_dir must be a non-empty string")

    # Resolve paths
    sd = Path(sections_dir)
    if not sd.is_absolute():
        sd = Path("/workspace") / sections_dir.lstrip("/")
    od = Path(output_dir)
    if not od.is_absolute():
        od = Path("/workspace") / output_dir.lstrip("/")

    pool_path = od / "citation_pool.json"

    # Check cache
    if not force and pool_path.exists():
        try:
            data = json.loads(pool_path.read_text())
            if isinstance(data, list) and len(data) > 0:
                return _ok(
                    message=f"CACHED: citation_pool.json already has {len(data)} entries. Use --force to rebuild.",
                    pool_path=str(pool_path),
                    count=len(data),
                )
        except Exception:
            pass

    # Read paper content
    paper_text = _extract_keywords_from_sections(str(sd))
    if not paper_text:
        return _err("NO_TEX_FILES", message="No .tex files found in sections_dir")

    # Get existing bib info for dedup
    existing_keys, existing_titles = _get_existing_bib_info(str(sd))

    # Generate queries
    queries = _generate_queries(paper_text)

    # Search
    all_results = []
    seen_urls = set()
    for query in queries:
        try:
            results = await firecrawl_search(query, num_results=4)
            for r in results:
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_results.append(r)
        except Exception:
            pass

    # Extract BibTeX for each
    pool = []
    for result in all_results:
        url = result["url"]
        local_file = result.get("local_filename", "")

        # Extract title from downloaded file
        title = "Unknown"
        if local_file and os.path.exists(local_file):
            try:
                with open(local_file, "r") as f:
                    content = f.read(3000)
                lines = content.strip().split("\n")
                for line in lines[:5]:
                    line = line.strip().strip("#").strip()
                    if 10 < len(line) < 200:
                        title = line
                        break
            except Exception:
                pass

        # Get BibTeX
        try:
            bib_result = get_bibtex_from_url(url, title)
            if not bib_result.get("ok"):
                continue

            bibtex = bib_result["bibtex"]

            # Get abstract
            abstract_text = ""
            try:
                abs_result = get_abstract_from_url(url, title)
                if abs_result.get("ok") and abs_result.get("abstract"):
                    abstract_text = abs_result["abstract"]
            except Exception:
                pass

            bib_title = _extract_title_from_bibtex(bibtex) or title

            # Normalize key
            new_key, new_bibtex = _normalize_bibtex_key(bibtex)
            if not new_key:
                continue

            # Filter junk
            junk_titles = {
                "user login",
                "creative commons",
                "license",
                "sign in",
                "access denied",
                "page not found",
                "403 forbidden",
                "cookie policy",
                "privacy policy",
                "terms of service",
            }
            if any(junk in bib_title.lower() for junk in junk_titles):
                continue
            if len(bib_title) < 10:
                continue

            # Dedup against existing bib by title
            bib_title_lower = bib_title.lower()[:40]
            if bib_title_lower in existing_titles:
                continue

            # Dedup against existing bib by key
            if new_key in existing_keys:
                for suffix in "abcdefghij":
                    alt_key = f"{new_key}{suffix}"
                    if alt_key not in existing_keys:
                        new_key = alt_key
                        new_bibtex = re.sub(
                            r"(@\w+\{)[^,\s]+", f"\\1{new_key}", new_bibtex, count=1
                        )
                        break
                else:
                    continue

            # Dedup within pool by title
            pool_titles = {
                _extract_title_from_bibtex(p["bibtex"]).lower()[:40]
                for p in pool
                if _extract_title_from_bibtex(p["bibtex"])
            }
            if bib_title_lower in pool_titles:
                continue

            # Dedup within pool by key
            pool_keys = {p.get("key") for p in pool}
            if new_key in pool_keys:
                for suffix in "abcdefghij":
                    alt_key = f"{new_key}{suffix}"
                    if alt_key not in pool_keys and alt_key not in existing_keys:
                        new_key = alt_key
                        new_bibtex = re.sub(
                            r"(@\w+\{)[^,\s]+", f"\\1{new_key}", new_bibtex, count=1
                        )
                        break
                else:
                    continue

            pool.append(
                {
                    "key": new_key,
                    "bibtex": new_bibtex,
                    "title": bib_title,
                    "abstract": abstract_text,
                    "url": url,
                }
            )

            existing_keys.add(new_key)
            existing_titles.add(bib_title_lower)

        except Exception:
            continue

    # Save
    od.mkdir(parents=True, exist_ok=True)
    with open(str(pool_path), "w") as f:
        json.dump(pool, f, indent=2)

    return _ok(
        message=f"POOL_SAVED: {len(pool)} citations to {pool_path}",
        pool_path=str(pool_path),
        count=len(pool),
    )


# ── Internal helpers ──────────────────────────────────────────────────


def _extract_keywords_from_sections(sections_dir):
    texts = []
    for fname in ["abstract.tex", "introduction.tex", "method.tex", "related_work.tex"]:
        path = os.path.join(sections_dir, fname)
        if os.path.exists(path):
            texts.append(open(path).read())
    return "\n".join(texts)


def _get_existing_bib_info(sections_dir):
    bib_path = os.path.join(sections_dir, "references.bib")
    keys = set()
    titles = set()
    if os.path.exists(bib_path):
        text = open(bib_path).read()
        for m in re.finditer(r"@\w+\{([^,\s]+)", text):
            keys.add(m.group(1).strip())
        for m in re.finditer(r"title\s*=\s*\{([^}]+)\}", text, re.IGNORECASE):
            titles.add(m.group(1).strip().lower()[:40])
    return keys, titles


def _normalize_bibtex_key(bibtex_str):
    author_match = re.search(r"author\s*=\s*\{([^}]+)\}", bibtex_str, re.IGNORECASE)
    year_match = re.search(r"year\s*=\s*\{?(\d{4})\}?", bibtex_str, re.IGNORECASE)
    if not author_match or not year_match:
        return None, bibtex_str
    author_str = author_match.group(1)
    year = year_match.group(1)
    first_author = author_str.split(" and ")[0].strip()
    if "," in first_author:
        last_name = first_author.split(",")[0].strip()
    else:
        parts = first_author.split()
        last_name = parts[-1] if parts else "Unknown"
    last_name = re.sub(r"[^a-zA-Z]", "", last_name) or "Unknown"
    new_key = f"{last_name}_{year}"
    new_bibtex = re.sub(r"(@\w+\{)[^,\s]+", f"\\1{new_key}", bibtex_str, count=1)
    return new_key, new_bibtex


def _extract_title_from_bibtex(bibtex_str):
    m = re.search(r"title\s*=\s*\{([^}]+)\}", bibtex_str, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _generate_queries(paper_text):
    clean = re.sub(r"\\cite\{[^}]*\}", " ", paper_text)
    clean = re.sub(r"\\label\{[^}]*\}", " ", clean)
    clean = re.sub(r"\\ref\{[^}]*\}", " ", clean)
    clean = re.sub(r"\\begin\{[^}]*\}", " ", clean)
    clean = re.sub(r"\\end\{[^}]*\}", " ", clean)
    clean = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", clean)
    clean = re.sub(r"\\[a-zA-Z]+", " ", clean)
    clean = re.sub(r"[{}$%&_^~\\]", " ", clean)
    clean = re.sub(r"\s+", " ", clean)

    title_match = re.search(r"\\title\{([^}]+)\}", paper_text)
    title = ""
    if title_match:
        title = title_match.group(1)
        title = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", title)
        title = re.sub(r"[{}\\]", "", title).strip()

    words = re.findall(r"\b[a-zA-Z]{3,}\b", clean.lower())
    stopwords = {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "are",
        "was",
        "were",
        "been",
        "being",
        "have",
        "has",
        "had",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "our",
        "their",
        "these",
        "those",
        "which",
        "where",
        "when",
        "what",
        "how",
        "not",
        "but",
        "also",
        "than",
        "then",
        "each",
        "such",
        "into",
        "over",
        "only",
        "more",
        "most",
        "some",
        "any",
        "all",
        "both",
        "other",
        "same",
        "given",
        "used",
        "using",
        "based",
        "approach",
        "method",
        "propose",
        "proposed",
        "paper",
        "section",
        "figure",
        "table",
        "results",
        "show",
        "shows",
        "shown",
        "use",
        "work",
        "provide",
        "provides",
        "text",
        "following",
        "specific",
        "different",
        "first",
        "second",
        "third",
        "new",
        "however",
        "while",
        "since",
        "between",
        "through",
        "respectively",
        "denoted",
        "defined",
        "note",
        "thus",
        "hence",
        "therefore",
        "ensure",
        "consider",
        "step",
        "process",
        "perform",
        "enable",
        "allows",
        "allow",
        "introduce",
        "present",
        "describe",
        "aim",
        "goal",
        "main",
        "key",
        "important",
        "significant",
        "existing",
        "recent",
        "previous",
        "prior",
        "current",
        "above",
        "below",
        "example",
        "case",
        "include",
        "includes",
        "including",
        "number",
        "set",
        "total",
        "output",
        "input",
        "model",
        "models",
        "system",
        "systems",
        "data",
        "level",
        "high",
        "low",
        "large",
        "small",
        "well",
        "better",
        "best",
        "achieve",
        "achieved",
    }

    filtered = [w for w in words if w not in stopwords and len(w) > 2]
    bigram_freq = {}
    for i in range(len(filtered) - 1):
        bg = f"{filtered[i]} {filtered[i+1]}"
        bigram_freq[bg] = bigram_freq.get(bg, 0) + 1

    unigram_freq = {}
    for w in filtered:
        unigram_freq[w] = unigram_freq.get(w, 0) + 1

    top_bigrams = sorted(bigram_freq.items(), key=lambda x: -x[1])[:15]
    top_unigrams = sorted(unigram_freq.items(), key=lambda x: -x[1])[:15]

    queries = []
    if title:
        queries.append(title[:80])

    for bg, _ in top_bigrams:
        if len(queries) >= 4:
            break
        queries.append(bg)

    unis = [u for u, _ in top_unigrams]
    if len(unis) >= 4:
        queries.append(f"{unis[0]} {unis[1]} {unis[2]}")
        queries.append(f"{unis[1]} {unis[3]}")

    for bg, _ in top_bigrams[3:]:
        if len(queries) >= 8:
            break
        if bg not in queries:
            queries.append(bg)

    while len(queries) < 8 and unis:
        idx = len(queries) % len(unis)
        queries.append(f"{unis[idx]} {unis[(idx+2) % len(unis)]}")

    return queries[:8]
