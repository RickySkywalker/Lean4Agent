"""Compile LaTeX sections directory to PDF using pdflatex."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from sandbox_vm.tools.utils import _err, _ok


def compile_pdf(
    sections_dir: str,
    output_pdf: str,
    primearxiv_sty: str = "/workspace/PRIMEarxiv.sty",
) -> dict:
    """
    Compile a LaTeX sections directory to a PDF file.

    Mirrors the compilation logic in the web app: copies files to a temp directory,
    runs pdflatex + bibtex, and produces a PDF. Installs texlive if pdflatex is
    not available.

    Args:
        sections_dir: Path to directory containing main.tex and section .tex files.
        output_pdf: Destination path for the compiled PDF.
        primearxiv_sty: Path to PRIMEarxiv.sty file (default: /workspace/PRIMEarxiv.sty).

    Returns:
        {
            "ok": True,
            "message": str,  # e.g. "PDF compiled successfully: path (size)"
            "output_path": str
        } or {"ok": False, "error": str, "message": str}

    Examples:
        >>> result = compile_pdf("/workspace/outputs/paper/sections",
        ...     "/workspace/outputs/paper/proposal.pdf")
        >>> print(result["message"])
        "PDF compiled successfully: /workspace/outputs/paper/proposal.pdf (712K)"
    """
    if not sections_dir or not isinstance(sections_dir, str):
        return _err("INVALID_INPUT", message="sections_dir must be a non-empty string")
    if not output_pdf or not isinstance(output_pdf, str):
        return _err("INVALID_INPUT", message="output_pdf must be a non-empty string")

    # Resolve paths
    sd = Path(sections_dir)
    if not sd.is_absolute():
        sd = Path("/workspace") / sections_dir.lstrip("/")

    out = Path(output_pdf)
    if not out.is_absolute():
        out = Path("/workspace") / output_pdf.lstrip("/")

    main_tex = sd / "main.tex"
    if not main_tex.exists():
        return _err("FILE_NOT_FOUND", message=f"main.tex not found in {sections_dir}")

    # Install pdflatex if not present
    if not shutil.which("pdflatex"):
        try:
            subprocess.run(
                ["sudo", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update", "-qq"],
                capture_output=True,
                timeout=120,
            )
            subprocess.run(
                [
                    "sudo",
                    "DEBIAN_FRONTEND=noninteractive",
                    "apt-get",
                    "install",
                    "-y",
                    "-qq",
                    "texlive-latex-base",
                    "texlive-latex-recommended",
                    "texlive-fonts-recommended",
                    "texlive-science",
                    "texlive-latex-extra",
                ],
                capture_output=True,
                timeout=600,
            )
        except Exception as e:
            return _err("INSTALL_FAILED", message=f"Failed to install texlive: {e}")

    # Create temp working directory
    work_dir = tempfile.mkdtemp()
    try:
        # Copy main.tex to top level
        shutil.copy2(str(main_tex), os.path.join(work_dir, "main.tex"))

        # Copy .sty if exists
        sty_path = Path(primearxiv_sty)
        if sty_path.exists():
            shutil.copy2(str(sty_path), os.path.join(work_dir, "PRIMEarxiv.sty"))

        # Copy everything else into sections/ (matching \input{sections/...})
        sections_dest = os.path.join(work_dir, "sections")
        os.makedirs(sections_dest, exist_ok=True)

        for item in sd.iterdir():
            fname = item.name
            if fname == "main.tex":
                continue
            if item.is_dir():
                # Copy subdirectories (e.g. figures/) into both sections/ and top level
                shutil.copytree(
                    str(item), os.path.join(sections_dest, fname), dirs_exist_ok=True
                )
                shutil.copytree(
                    str(item), os.path.join(work_dir, fname), dirs_exist_ok=True
                )
            else:
                shutil.copy2(str(item), os.path.join(sections_dest, fname))
                # Also copy .bib files to top level for bibtex
                if fname.endswith(".bib"):
                    shutil.copy2(str(item), os.path.join(work_dir, fname))

        # Compile
        pdflatex_cmd = ["pdflatex", "-interaction=nonstopmode", "main.tex"]
        run_opts = dict(cwd=work_dir, capture_output=True, timeout=120)

        subprocess.run(pdflatex_cmd, **run_opts)

        # bibtex if .bib files exist
        bib_files = list(Path(work_dir).glob("*.bib")) + list(
            Path(sections_dest).glob("*.bib")
        )
        if bib_files:
            subprocess.run(
                ["bibtex", "main"], cwd=work_dir, capture_output=True, timeout=60
            )

        subprocess.run(pdflatex_cmd, **run_opts)
        subprocess.run(pdflatex_cmd, **run_opts)

        # Check result
        compiled_pdf = os.path.join(work_dir, "main.pdf")
        if os.path.exists(compiled_pdf):
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(compiled_pdf, str(out))
            size = os.path.getsize(str(out))
            size_str = (
                f"{size / 1024:.0f}K"
                if size < 1024 * 1024
                else f"{size / (1024*1024):.1f}M"
            )
            return _ok(
                message=f"PDF compiled successfully: {output_pdf} ({size_str})",
                output_path=str(out),
            )
        else:
            # Read last 30 lines of log for debugging
            log_path = os.path.join(work_dir, "main.log")
            log_tail = ""
            if os.path.exists(log_path):
                with open(log_path) as f:
                    lines = f.readlines()
                    log_tail = "".join(lines[-30:])
            return _err(
                "COMPILE_FAILED",
                message=f"PDF compilation failed. Log tail:\n{log_tail}",
            )

    except subprocess.TimeoutExpired:
        return _err("TIMEOUT", message="pdflatex timed out after 120 seconds")
    except Exception as e:
        return _err("COMPILE_ERROR", message=f"Compilation error: {e}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
