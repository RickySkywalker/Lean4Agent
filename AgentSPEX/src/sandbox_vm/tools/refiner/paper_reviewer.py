"""Submit a PDF to the review API and return structured review results."""

import json
from datetime import datetime
from pathlib import Path

import requests

from sandbox_vm.tools.utils import _err, _ok


def review_paper(
    pdf_path: str,
    output_json: str = "",
    arxiv_id: str = "2603",
    n_reviews: int = 256,
    seed: int = 42,
) -> dict:
    """
    Submit a PDF paper to the review API and return structured review results.

    Uploads the PDF to the unified review endpoint, which returns reviewer
    assessments including novelty, significance, soundness, strengths, weaknesses,
    and a normalized score.

    Args:
        pdf_path: Path to the PDF file to review (relative to /workspace or absolute).
        output_json: Path to save the review JSON. If empty, auto-generated with timestamp.
        arxiv_id: Arxiv ID for constraining related-work date (default "2603").
        n_reviews: Number of reviews to aggregate (default 256).
        seed: Random seed for reproducibility (default 42).

    Returns:
        {
            "ok": True,
            "review": dict,     # Contains Novelty, Significance, Soundness, Strengths, Weaknesses
            "score": dict,      # Contains expected_rating (normalized 0-10)
            "output_path": str  # Path to saved JSON
        } or {"ok": False, "error": str, "message": str}

    Examples:
        >>> result = review_paper("/workspace/outputs/paper/proposal.pdf",
        ...     "/workspace/outputs/paper/review.json")
        >>> print(result["score"]["expected_rating"])
        5.6632
    """
    if not pdf_path or not isinstance(pdf_path, str):
        return _err("INVALID_INPUT", message="pdf_path must be a non-empty string")

    # Resolve paths
    p = Path(pdf_path)
    if not p.is_absolute():
        p = Path("/workspace") / pdf_path.lstrip("/")

    if not p.exists():
        return _err("FILE_NOT_FOUND", message=f"PDF file not found: {pdf_path}")

    # Auto-generate output path if not provided
    if not output_json:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_json = str(p.parent / f"result_{ts}.json")
    else:
        out = Path(output_json)
        if not out.is_absolute():
            out = Path("/workspace") / output_json.lstrip("/")
        output_json = str(out)

    api_url = "https://researchguide.site/api/unified-review"

    try:
        with open(str(p), "rb") as f:
            response = requests.post(
                api_url,
                headers={"X-API-Key": "OptimalScale"},
                files={"file": (p.name, f, "application/pdf")},
                data={
                    "arxiv_id": str(arxiv_id),
                    "n_reviews": str(n_reviews),
                    "seed": str(seed),
                },
                timeout=600,
            )

        if response.status_code != 200:
            return _err(
                "API_ERROR",
                message=f"Review API returned status {response.status_code}: {response.text[:500]}",
            )

        data = response.json()

        review = data.get("review", {})
        score_data = data.get("score", {})

        # Prefer adjusted_expected_rating, fall back to expected_rating
        adjusted = score_data.get("adjusted_expected_rating")
        expected = score_data.get("expected_rating")
        adj_val = adjusted if isinstance(adjusted, (int, float)) else None
        exp_val = expected if isinstance(expected, (int, float)) else None

        result = {
            "review": {
                "Novelty": review.get("Novelty", ""),
                "Significance": review.get("Significance", ""),
                "Soundness": review.get("Soundness", ""),
                "Strengths": review.get("strengths", ""),
                "Weaknesses": review.get("weaknesses", ""),
                "comparison_with_previous_work": review.get(
                    "comparison_with_previous_work", ""
                ),
            },
            "score": {
                "adjusted_expected_rating": adj_val,
                "expected_rating": exp_val,
            },
        }

        # Save to file
        Path(output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(output_json, "w") as f:
            json.dump(result, f, indent=2)

        return _ok(
            review=result["review"],
            score=result["score"],
            output_path=output_json,
        )

    except requests.Timeout:
        return _err("TIMEOUT", message="Review API request timed out after 600 seconds")
    except requests.ConnectionError as e:
        return _err("CONNECTION_ERROR", message=f"Could not connect to review API: {e}")
    except Exception as e:
        return _err("REVIEW_FAILED", message=f"Review API call failed: {e}")
