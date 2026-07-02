"""Reference and citation tools for academic papers."""

import os
import re
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

import requests

from sandbox_vm.mcp.utils import WORKSPACE_DIR, filename_to_path
from sandbox_vm.tools.utils import _err, _ok


def get_bibtex_from_url(url: str, title: str) -> dict:
    """
    Get BibTeX citation from a paper's url and title using CiteAS API. If failed, fallback to CrossRef API.

    Args:
        url: The web URL points to the paper want to retrieve bibtex.
        title: Paper name for query search, use the proper file name, exclude prefix file path for better search quality.

    Returns:
        {
            "bibtex": str,  # BibTeX formatted citation
        } on success, or {"error": "error_code", "message": "error message"} on failure

    Examples:
        >>> result = get_bibtex_from_url("https://arxiv.org/abs/1706.03762", "Attention Is All You Need")
        >>> print(result["bibtex"])
        @article{...}

        >>> result = get_bibtex_from_url("https://doi.org/10.1038/nature12373", "Nanometre-scale thermometry in a living cell")
        >>> print(result["bibtex"])
        @article{...}
    """
    if not title or not isinstance(title, str):
        return _err("INVALID_INPUT", message="title must be a non-empty string")

    if not url or not isinstance(url, str):
        return _err("INVALID_INPUT", message="URL must be a non-empty string")

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return _err("INVALID_URL", message="URL must start with http:// or https://")

    # Use arxiv API for arxiv papers (fast path)
    if "arxiv.org" in url:
        try:
            if "v2" in url:
                url = url.replace("v2", "")
            if "v1" in url:
                url = url.replace("v1", "")

            arxiv_id = url.split("/")[-1]
            if arxiv_id[-1] == "?":
                arxiv_id = arxiv_id[:-1]

            doi = "10.48550/arxiv." + arxiv_id

            doi_url = f"https://doi.org/{doi}"
            headers = {"Accept": "application/x-bibtex"}
            response = requests.get(doi_url, headers=headers, timeout=10)
            if response.status_code == 200:
                return _ok(
                    bibtex=response.text.replace("\n", ""),
                )
        except Exception as e:
            print(f"Arxiv DOI Extract Failed: {str(e)}, falling back to CrossRef API")

    # For BioRxiv/MedRxiv, try direct DOI API access (no JavaScript needed)
    if "biorxiv.org" in url or "medrxiv.org" in url:
        try:
            # Extract DOI from URL - BioRxiv URLs are like: /content/10.1101/YYYY.MM.DD.XXXXXX
            doi_match = re.search(r"10\.\d+/[\d.]+", url)
            if doi_match:
                doi = doi_match.group(0)
                doi_url = f"https://doi.org/{doi}"
                headers = {"Accept": "application/x-bibtex"}
                response = requests.get(doi_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    return _ok(
                        bibtex=response.text.replace("\n", ""),
                    )
        except Exception as doi_error:
            print("No BibTeX in DOI Search response, falling back to CrossRef API")

    # Use crossRef API
    api_url = "https://api.crossref.org/works"
    params = {"query.title": title, "rows": 1}

    resp = requests.get(api_url, params=params)
    data = resp.json()

    for item in data["message"]["items"]:
        doi = item["DOI"]

    doi_url = f"https://doi.org/{doi}"
    headers = {"Accept": "application/x-bibtex"}
    response = requests.get(doi_url, headers=headers, timeout=10)
    if response.status_code == 200:
        return _ok(
            bibtex=response.text.replace("\n", ""),
        )

    return _err(
        "FETCH_FAILED",
        message=f"ALL bibtex Retreival failed, plesae read the file and generate bibtex.",
    )


def get_abstract_from_url(url: str, title: str) -> dict:
    """
    MCP Tool: Retrieve abstract for an academic paper.

    Args:
        url: Web URL pointing to the paper. Must begin with "http://" or "https://".
        title: Paper title for query search (used when DOI cannot be extracted from URL).

    Returns:
        dict:
            On success:
            {
                "abstract": str | None,  # Paper abstract, None if unavailable
            }

            On failure:
            {
                "error": str,      # error code
                "message": str,    # human-readable explanation
            }

    Examples:
        >>> result = get_abstract_from_url("https://arxiv.org/abs/1706.03762v2", "Attention Is All You Need")
        >>> print(result["abstract"])
        "The dominant sequence transduction models..."

        >>> result = get_abstract_from_url("https://doi.org/10.1038/nature12373", "Nanometre-scale thermometry")
        >>> print(result["abstract"])
        "..."  # may be None depending on metadata availability
    """
    # -------------------------
    # Input validation
    # -------------------------
    if not title or not isinstance(title, str):
        return _err("INVALID_INPUT", message="title must be a non-empty string")

    if not url or not isinstance(url, str):
        return _err("INVALID_INPUT", message="URL must be a non-empty string")

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return _err("INVALID_URL", message="URL must start with http:// or https://")

    # OpenAlex "polite pool" contact email — set OPENALEX_EMAIL (or CITEAS_EMAIL)
    # to your own address; unset falls back to the anonymous pool.
    openalex_email = os.getenv("OPENALEX_EMAIL", os.getenv("CITEAS_EMAIL", ""))

    # -------------------------
    # Helper functions
    # -------------------------
    def _extract_arxiv_id(u: str) -> Optional[str]:
        parsed = urlparse(u)
        if "arxiv.org" not in (parsed.netloc or ""):
            return None
        path = (parsed.path or "").strip("/")
        if not path:
            return None
        arxiv_id = path.split("/")[-1].replace(".pdf", "")
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)  # strip v1/v2/...
        return arxiv_id or None

    def _extract_doi_from_text(text: str) -> Optional[str]:
        m = re.search(r"\b10\.\d{4,9}/[^\s\"<>]+", text)
        if not m:
            return None
        return m.group(0).rstrip(").,;")

    def _crossref_search_doi_by_title(t: str) -> Optional[str]:
        r = requests.get(
            "https://api.crossref.org/works",
            params={"query.title": t, "rows": 1},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        try:
            items = r.json().get("message", {}).get("items", []) or []
            if not items:
                return None
            return items[0].get("DOI")
        except Exception:
            return None

    def _openalex_work_by_doi(doi: str) -> Optional[Dict[str, Any]]:
        r = requests.get(
            f"https://api.openalex.org/works/https://doi.org/{doi}",
            params={"mailto": openalex_email} if openalex_email else {},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except Exception:
            return None

    def _openalex_abstract_text(work: Dict[str, Any]) -> Optional[str]:
        inv = work.get("abstract_inverted_index")
        if not inv:
            return None
        tokens = []
        for word, positions in inv.items():
            for p in positions:
                tokens.append((p, word))
        if not tokens:
            return None
        tokens.sort(key=lambda x: x[0])
        return " ".join(w for _, w in tokens).strip() or None

    def _crossref_abstract(doi: str) -> Optional[str]:
        r = requests.get(f"https://api.crossref.org/works/{doi}", timeout=10)
        if r.status_code != 200:
            return None
        try:
            msg = r.json().get("message", {}) or {}
            return msg.get("abstract")
        except Exception:
            return None

    def _doi_csl_json_abstract(doi: str) -> Optional[str]:
        r = requests.get(
            f"https://doi.org/{doi}",
            headers={"Accept": "application/vnd.citationstyles.csl+json"},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        try:
            return (r.json() or {}).get("abstract")
        except Exception:
            return None

    # -------------------------
    # 1) Resolve DOI
    # -------------------------
    doi: Optional[str] = None

    try:
        arxiv_id = _extract_arxiv_id(url)
        if arxiv_id:
            doi = f"10.48550/arXiv.{arxiv_id}"
        else:
            if "biorxiv.org" in url or "medrxiv.org" in url:
                # Extract DOI from URL - BioRxiv URLs are like: /content/10.1101/YYYY.MM.DD.XXXXXX
                doi_match = re.search(r"10\.\d+/[\d.]+", url)
                if doi_match:
                    doi = doi_match.group(0)
            else:
                doi = _extract_doi_from_text(url)
            if not doi:
                doi = _crossref_search_doi_by_title(title)
                if not doi:
                    return _err(
                        "DOI_NOT_FOUND",
                        message="Could not extract DOI from URL and Crossref title search did not return a DOI.",
                    )
    except Exception as e:
        return _err("FETCH_FAILED", message=f"DOI resolution failed: {e}")

    # -------------------------
    # 2) Fetch Abstract (OpenAlex -> Semantic Scholar -> Crossref -> doi.org CSL-JSON)
    # -------------------------
    abstract: Optional[str] = None

    # Try OpenAlex first (best coverage)
    try:
        work = _openalex_work_by_doi(doi)
        if work:
            abstract = _openalex_abstract_text(work)
            if abstract:
                return _ok(abstract=abstract)
            else:
                print("OpenAlex record found but no abstract_inverted_index present.")
        else:
            print("OpenAlex lookup failed or work not found.")
    except Exception as e:
        print(f"OpenAlex abstract fetch error (non-fatal): {e}")

    # Try Crossref fallback
    if not abstract:
        try:
            abstract = _crossref_abstract(doi)
            if abstract:
                return _ok(abstract=abstract)
            else:
                print("Crossref has no abstract for this DOI (common).")
        except Exception as e:
            print(f"Crossref abstract fetch error (non-fatal): {e}")

    # Try doi.org CSL-JSON as final fallback
    if not abstract:
        try:
            abstract = _doi_csl_json_abstract(doi)
            if abstract:
                return _ok(abstract=abstract)
            else:
                print("doi.org CSL-JSON has no abstract for this DOI.")
        except Exception as e:
            print(f"doi.org CSL-JSON abstract fetch error (non-fatal): {e}")

    # All methods failed, return None
    return _ok(abstract=abstract)


def json_to_bibtex(json_file_path: str) -> dict:
    """
    Convert JSON citation file to LaTeX BibTeX format.

    Reads a JSON file containing citations (with 'bibtex' field) and converts
    it to a .bib file. The output file is saved in the same directory as the
    input file with the name 'references.bib'.

    Args:
        json_file_path: Path to the input JSON file (relative to workspace or absolute).
                       Example: "sections/reference.json" or
                                "/workspace/outputs/AIScientist_Writer_test_writer/sections/reference.json"

    Returns:
        dict:
            On success:
            {
                "message": str,  # Success message with details
                "output_path": str,  # Path to the generated .bib file
                "entries_count": int,  # Number of BibTeX entries converted
            }

            On failure:
            {
                "error": str,      # Error code
                "message": str,    # Human-readable error message
            }

    Examples:
        >>> result = json_to_bibtex("sections/reference.json")
        >>> if "error" not in result:
        ...     print(f"Generated {result['output_path']} with {result['entries_count']} entries")
        "Generated /workspace/outputs/.../sections/references.bib with 5 entries"
    """
    import json
    from pathlib import Path

    # Input validation
    if not json_file_path or not isinstance(json_file_path, str):
        return _err(
            "INVALID_INPUT", message="json_file_path must be a non-empty string"
        )

    try:
        # Resolve path using the workspace utility function
        # This handles both relative and absolute paths correctly
        # and uses VM_WORKSPACE environment variable for actual workspace location
        full_json_path = filename_to_path(json_file_path)

        # Check if input file exists
        if not full_json_path.exists():
            return _err(
                "FILE_NOT_FOUND",
                message=f"Input JSON file not found: {json_file_path} (resolved to: {full_json_path})",
            )

        # Check if it's a JSON file
        if not full_json_path.suffix.lower() == ".json":
            return _err(
                "INVALID_FILE_TYPE",
                message=f"Input file must be a .json file, got: {full_json_path.suffix}",
            )

        # Read JSON file
        try:
            with open(full_json_path, "r", encoding="utf-8") as f:
                citations = json.load(f)
        except json.JSONDecodeError as e:
            return _err(
                "INVALID_JSON", message=f"Invalid JSON format in {json_file_path}: {e}"
            )
        except Exception as e:
            return _err("READ_ERROR", message=f"Failed to read {json_file_path}: {e}")

        # Validate JSON structure
        if not isinstance(citations, list):
            return _err(
                "INVALID_JSON_STRUCTURE",
                message="JSON file must contain a list of citations",
            )

        # Extract and deduplicate BibTeX entries
        seen_keys = set()
        bibtex_entries = []

        def extract_bibtex_key(bibtex_str):
            """Extract BibTeX key from a BibTeX entry string."""
            import re

            match = re.search(r"@\w+\{([^,}]+)", bibtex_str)
            if match:
                return match.group(1).strip()
            return None

        def clean_bibtex_entry(bibtex_str):
            """Clean and format a BibTeX entry string."""
            import re

            # Remove leading/trailing whitespace
            bibtex_str = bibtex_str.strip()

            # Remove leading @ if it's preceded by a space
            bibtex_str = re.sub(r"^\s*@", "@", bibtex_str)

            # Ensure proper formatting: @type{key, ...}
            if not bibtex_str.startswith("@"):
                match = re.search(r"@\w+", bibtex_str)
                if match:
                    bibtex_str = bibtex_str[match.start() :]

            # Ensure the entry ends with a closing brace
            if not bibtex_str.rstrip().endswith("}"):
                last_brace = bibtex_str.rfind("}")
                if last_brace > 0:
                    bibtex_str = bibtex_str[: last_brace + 1]

            # Fix missing journal field for @article entries
            # Check if it's an @article entry
            if bibtex_str.strip().startswith("@article"):
                # Check if journal field is missing (case-insensitive)
                if "journal" not in bibtex_str.lower():
                    # Extract arxiv ID if present
                    arxiv_match = re.search(
                        r"arxiv\.org/abs/(\d+\.\d+)", bibtex_str, re.IGNORECASE
                    )
                    if arxiv_match:
                        arxiv_id = arxiv_match.group(1)
                        # Add journal field before the closing brace
                        journal_field = (
                            f",\n  journal = {{arXiv preprint arXiv:{arxiv_id}}}"
                        )
                        bibtex_str = (
                            bibtex_str.rstrip().rstrip("}") + journal_field + "\n}"
                        )
                    else:
                        # Check for publisher field to determine journal
                        publisher_match = re.search(
                            r"publisher\s*=\s*\{([^}]+)\}", bibtex_str, re.IGNORECASE
                        )
                        if publisher_match:
                            publisher = publisher_match.group(1).strip()
                            # For arXiv, add journal field
                            if "arxiv" in publisher.lower():
                                # Try to extract arxiv ID from URL or DOI
                                url_match = re.search(
                                    r"url\s*=\s*\{([^}]+)\}", bibtex_str, re.IGNORECASE
                                )
                                if url_match:
                                    url = url_match.group(1)
                                    arxiv_id_match = re.search(
                                        r"arxiv\.org/abs/(\d+\.\d+)", url, re.IGNORECASE
                                    )
                                    if arxiv_id_match:
                                        arxiv_id = arxiv_id_match.group(1)
                                        journal_field = f",\n  journal = {{arXiv preprint arXiv:{arxiv_id}}}"
                                    else:
                                        journal_field = (
                                            f",\n  journal = {{arXiv preprint}}"
                                        )
                                else:
                                    journal_field = f",\n  journal = {{arXiv preprint}}"
                                bibtex_str = (
                                    bibtex_str.rstrip().rstrip("}")
                                    + journal_field
                                    + "\n}"
                                )
                            # For ChemRxiv and other preprint servers
                            elif "chemrxiv" in publisher.lower():
                                journal_field = f",\n  journal = {{ChemRxiv}}"
                                bibtex_str = (
                                    bibtex_str.rstrip().rstrip("}")
                                    + journal_field
                                    + "\n}"
                                )
                            elif (
                                "biorxiv" in publisher.lower()
                                or "medrxiv" in publisher.lower()
                            ):
                                journal_field = f",\n  journal = {{{publisher}}}"
                                bibtex_str = (
                                    bibtex_str.rstrip().rstrip("}")
                                    + journal_field
                                    + "\n}"
                                )
                            # For other publishers without journal, use publisher as journal
                            else:
                                journal_field = f",\n  journal = {{{publisher}}}"
                                bibtex_str = (
                                    bibtex_str.rstrip().rstrip("}")
                                    + journal_field
                                    + "\n}"
                                )
                        else:
                            # No publisher field, add a generic journal field
                            journal_field = f",\n  journal = {{Preprint}}"
                            bibtex_str = (
                                bibtex_str.rstrip().rstrip("}") + journal_field + "\n}"
                            )

            return bibtex_str

        for citation in citations:
            if "bibtex" not in citation:
                continue  # Skip citations without bibtex field

            bibtex_str = citation["bibtex"]
            bibtex_str = clean_bibtex_entry(bibtex_str)

            # Extract key for deduplication
            key = extract_bibtex_key(bibtex_str)
            if key is None:
                continue  # Skip entries without valid key

            # Deduplicate based on key
            if key not in seen_keys:
                seen_keys.add(key)
                bibtex_entries.append(bibtex_str)

        if not bibtex_entries:
            return _err(
                "NO_ENTRIES",
                message=f"No valid BibTeX entries found in {json_file_path}",
            )

        # Generate output path (same directory, name is references.bib)
        output_dir = full_json_path.parent
        output_bib_path = output_dir / "references.bib"

        # Write to .bib file
        try:
            with open(output_bib_path, "w", encoding="utf-8") as f:
                for entry in bibtex_entries:
                    f.write(entry)
                    f.write("\n\n")  # Two newlines between entries

            # Return relative path for consistency (relative to workspace)
            try:
                relative_output_path = str(output_bib_path.relative_to(WORKSPACE_DIR))
            except ValueError:
                # If path is not under WORKSPACE_DIR, return absolute path
                relative_output_path = str(output_bib_path)

            return _ok(
                message=f"Successfully converted {len(bibtex_entries)} entries to references.bib",
                output_path=relative_output_path,
                entries_count=len(bibtex_entries),
            )
        except Exception as e:
            return _err(
                "WRITE_ERROR", message=f"Failed to write {output_bib_path}: {e}"
            )
    except Exception as e:
        return _err(
            "UNEXPECTED_ERROR", message=f"Unexpected error in json_to_bibtex: {e}"
        )
