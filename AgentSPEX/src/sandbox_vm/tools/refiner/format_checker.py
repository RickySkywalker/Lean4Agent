"""Format checking tool for LaTeX papers — checks title, abstract, subsections, references, figures, etc."""

import json
import os
import re
from pathlib import Path

from sandbox_vm.tools.utils import _err, _ok


def check_format(
    sections_dir: str,
    min_refs: int = 20,
    max_title_words: int = 10,
    min_title_words: int = 4,
    max_subsections: int = 5,
) -> dict:
    """
    Check formatting requirements for a LaTeX paper and return detailed results.

    Runs 9 automated checks: title length, abstract single paragraph, subsection count,
    reference count, no (a)(b)(c) pattern, equations centered, abstract no citations,
    no orphan citations, and has figure.

    Args:
        sections_dir: Path to directory containing .tex files (relative to /workspace or absolute).
        min_refs: Minimum number of effective references required (default 20).
        max_title_words: Maximum words allowed in title (default 10).
        min_title_words: Minimum words required in title (default 4).
        max_subsections: Maximum subsections allowed per section (default 5).

    Returns:
        {
            "ok": True,
            "results": dict  # Full check results as JSON-serializable dict
        } or {"ok": False, "error": str, "message": str}

    Examples:
        >>> result = check_format("/workspace/outputs/paper/sections")
        >>> print(result["results"]["automated_pass_count"])
        9
    """
    if not sections_dir or not isinstance(sections_dir, str):
        return _err("INVALID_INPUT", message="sections_dir must be a non-empty string")

    d = Path(sections_dir)
    if not d.is_absolute():
        d = Path("/workspace") / sections_dir.lstrip("/")
    d = str(d)

    if not os.path.isdir(d):
        return _err("DIR_NOT_FOUND", message=f"Directory not found: {sections_dir}")

    try:
        results = {}

        # 1. Title word count
        title_words, title_text = _count_title_words(d)
        results["title_words"] = title_words
        results["title_text"] = title_text
        results["title_ok"] = min_title_words <= title_words <= max_title_words

        # 2. Abstract paragraphs
        abstract_paras = _count_abstract_paragraphs(d)
        results["abstract_paragraphs"] = abstract_paras
        results["abstract_single_paragraph"] = abstract_paras == 1

        # 3. Subsections per section
        max_sub, max_sub_file, sub_details = _count_subsections(d)
        results["max_subsections"] = max_sub
        results["max_subsections_file"] = max_sub_file
        results["subsections_ok"] = max_sub <= max_subsections
        results["subsection_details"] = sub_details

        # 4. Reference count
        ref_count = _count_references(d)
        results["reference_count"] = ref_count
        results["references_ok"] = ref_count >= min_refs

        # 5. (a)(b)(c) pattern in related work
        has_abc, abc_matches = _check_abc_pattern(d)
        results["has_abc_pattern"] = has_abc
        results["abc_ok"] = not has_abc

        # 6. Equations centered
        eq_centered, eq_issues = _check_equations_centered(d)
        results["equations_centered"] = eq_centered
        results["equation_issues"] = eq_issues

        # 7. Abstract has no citations
        abstract_no_cite, abstract_cite_keys = _check_abstract_no_citations(d)
        results["abstract_no_citations"] = abstract_no_cite
        results["abstract_citation_keys"] = abstract_cite_keys

        # 8. No orphan citations
        no_orphans, orphan_details = _check_orphan_citations(d)
        results["no_orphan_citations"] = no_orphans
        results["orphan_citation_details"] = orphan_details

        # 9. Has figure
        has_fig, fig_details = _check_has_figure(d)
        results["has_figure"] = has_fig
        results["figure_details"] = fig_details

        # Summary
        checks = [
            results["title_ok"],
            results["abstract_single_paragraph"],
            results["subsections_ok"],
            results["references_ok"],
            results["abc_ok"],
            results["equations_centered"],
            results["abstract_no_citations"],
            results["no_orphan_citations"],
            results["has_figure"],
        ]
        results["automated_pass_count"] = sum(checks)
        results["automated_total_checks"] = len(checks)

        return _ok(results=results)

    except Exception as e:
        return _err("CHECK_ERROR", message=f"Format check failed: {e}")


# ── Internal helper functions ──────────────────────────────────────────


def _count_title_words(sections_dir):
    main_path = os.path.join(sections_dir, "main.tex")
    if not os.path.exists(main_path):
        return -1, ""
    text = open(main_path).read()
    m = re.search(r"\\title\{(.+?)\}", text, re.DOTALL)
    if not m:
        return -1, ""
    title = m.group(1).strip()
    clean = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", title)
    clean = re.sub(r"[{}\\]", "", clean)
    return len(clean.split()), title


def _count_abstract_paragraphs(sections_dir):
    path = os.path.join(sections_dir, "abstract.tex")
    if not os.path.exists(path):
        return -1
    text = open(path).read()
    text = re.sub(r"\\begin\{abstract\}", "", text)
    text = re.sub(r"\\end\{abstract\}", "", text)
    text = text.strip()
    if not text:
        return 0
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return len(paragraphs)


def _count_subsections(sections_dir):
    results = {}
    max_count = 0
    max_file = ""
    for fname in os.listdir(sections_dir):
        if not fname.endswith(".tex") or fname == "main.tex":
            continue
        text = open(os.path.join(sections_dir, fname)).read()
        count = len(re.findall(r"\\subsection\{", text))
        results[fname] = count
        if count > max_count:
            max_count = count
            max_file = fname
    return max_count, max_file, results


def _count_references(sections_dir):
    bib_path = os.path.join(sections_dir, "references.bib")
    if not os.path.exists(bib_path):
        return 0
    bib_text = open(bib_path).read()
    bib_keys = set()
    for m in re.finditer(r"@\w+\{([^,\s]+)", bib_text):
        bib_keys.add(m.group(1).strip())

    cited_keys = set()
    for fname in os.listdir(sections_dir):
        if not fname.endswith(".tex"):
            continue
        text = open(os.path.join(sections_dir, fname)).read()
        for m in re.findall(r"\\cite\{([^}]+)\}", text):
            for key in m.split(","):
                cited_keys.add(key.strip())

    return len(bib_keys & cited_keys)


def _check_abc_pattern(sections_dir):
    path = os.path.join(sections_dir, "related_work.tex")
    if not os.path.exists(path):
        return False, []
    text = open(path).read()
    matches = re.findall(r"\([a-z]\)|\([iv]+\)", text)
    return len(matches) > 0, matches


def _check_equations_centered(sections_dir):
    issues = []
    for fname in os.listdir(sections_dir):
        if not fname.endswith(".tex") or fname == "main.tex":
            continue
        text = open(os.path.join(sections_dir, fname)).read()
        if "$$" in text:
            issues.append(
                f"{fname}: uses $$ display math instead of equation environment"
            )
        align_count = len(re.findall(r"\\begin\{align\}", text))
        if align_count > 0:
            issues.append(f"{fname}: uses align environment ({align_count}x)")
    return len(issues) == 0, issues


def _check_abstract_no_citations(sections_dir):
    path = os.path.join(sections_dir, "abstract.tex")
    if not os.path.exists(path):
        return True, []
    text = open(path).read()
    cites = re.findall(r"\\cite\{([^}]*)\}", text)
    if not cites:
        return True, []
    all_keys = []
    for c in cites:
        all_keys.extend([k.strip() for k in c.split(",")])
    return False, all_keys


def _check_has_figure(sections_dir):
    has_includegraphics = False
    has_caption = False
    has_fig_label = False
    has_fig_ref = False
    figure_file_exists = False

    figures_dir = os.path.join(sections_dir, "figures")
    if os.path.isdir(figures_dir):
        for f in os.listdir(figures_dir):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".pdf", ".eps")):
                figure_file_exists = True
                break

    for fname in os.listdir(sections_dir):
        if not fname.endswith(".tex"):
            continue
        text = open(os.path.join(sections_dir, fname)).read()
        if re.search(r"\\includegraphics", text):
            has_includegraphics = True
        if re.search(r"\\caption\{", text):
            has_caption = True
        if re.search(r"\\label\{fig:", text):
            has_fig_label = True
        if re.search(r"\\ref\{fig:", text):
            has_fig_ref = True

    ok = (
        figure_file_exists
        and has_includegraphics
        and has_caption
        and has_fig_label
        and has_fig_ref
    )
    return ok, {
        "figure_file_exists": figure_file_exists,
        "has_includegraphics": has_includegraphics,
        "has_caption": has_caption,
        "has_fig_label": has_fig_label,
        "has_fig_ref": has_fig_ref,
    }


def _check_orphan_citations(sections_dir):
    bib_path = os.path.join(sections_dir, "references.bib")
    bib_keys = set()
    if os.path.exists(bib_path):
        text = open(bib_path).read()
        for m in re.finditer(r"@\w+\{([^,\s]+)", text):
            bib_keys.add(m.group(1).strip())

    orphans = {}
    for fname in os.listdir(sections_dir):
        if not fname.endswith(".tex"):
            continue
        text = open(os.path.join(sections_dir, fname)).read()
        cites = re.findall(r"\\cite\{([^}]*)\}", text)
        for c in cites:
            for key in c.split(","):
                key = key.strip()
                if key and key not in bib_keys:
                    orphans.setdefault(key, []).append(fname)

    return len(orphans) == 0, orphans
