from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from fastmcp import Context

from sandbox_vm.mcp.utils import filename_to_path
from sandbox_vm.tools.app_control.browser import (_browser_page_html,
                                                  browser_navigate)
from sandbox_vm.tools.parser.parsing import extract_text_from_files
from sandbox_vm.tools.session_management import MANAGER
from sandbox_vm.tools.utils import _err, _ok, _sid


def _url_to_filename(url: str) -> str:
    """
    Create a stable, safe filename for a URL.
    """
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"{h}.html"


async def _save_current_page_html(ctx: Context, url: str) -> Dict[str, Any]:
    """
    After navigating, capture HTML from the current page and save it into the
    session's url_download directory. Returns { handle }.
    """
    rt = MANAGER.get(_sid(ctx))

    # Fetch HTML from current page (no disk IO from the browser tool)
    html_res = await _browser_page_html(ctx)
    if "error" in html_res:
        return html_res

    html = html_res.get("html", "")
    out_dir = rt.root / "url_download"
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = _url_to_filename(url)
    path = out_dir / fname

    try:
        path.write_text(html, encoding="utf-8")
    except Exception as e:
        return _err("WRITE_ERROR", message=str(e))

    handle = rt.publish_path(path, perm="r", label=f"page-{fname}")
    rt.touch()
    return _ok(handle=handle)


async def web_fetch_urls(ctx: Context, urls: List[str]) -> dict:
    """
    Download multiple URLs and return sandbox handles to the saved artifacts.

    Args:
        urls (required): list of urls

    Returns:
      {
        results: [{ url, handle }]
      }
    """
    sid = _sid(ctx)
    results: List[Dict[str, Any]] = []

    for url in urls:
        try:
            nav = await browser_navigate(ctx, url)
            if not nav or "error" in nav:
                continue

            saved = await _save_current_page_html(ctx, nav.get("url") or url)
            if "error" not in saved:
                results.append({"url": url, "handle": saved["handle"]})
        except Exception:
            continue

    MANAGER.touch(sid)
    return _ok(results=results)


async def web_fetch_and_parse_urls(
    ctx: Context,
    urls: List[str],
    output_parent: Optional[str] = None,
) -> dict:
    """
    Download URLs, extract text from the resulting HTML files, and
    return sandbox handles for both inputs and extracted outputs.

    Returns:
      {
        downloaded: [{ url, handle }],
        extracted: {
          outputs: [<handles to .txt files>]
        }
      }
    """
    rt = MANAGER.get(_sid(ctx))

    downloaded = await web_fetch_urls(ctx, urls)
    if "error" in downloaded:
        return downloaded

    # Resolve input handles to real paths for the parser (server-side only)
    input_paths: List[str] = []
    for item in downloaded["results"]:
        try:
            p = rt.resolve(item["handle"], need="r")
            input_paths.append(str(p))
        except Exception:
            continue

    if not input_paths:
        return _err("NO_INPUTS", message="No inputs resolved for extraction")

    parser_kwargs: Dict[str, Any] = {}
    if output_parent:
        try:
            out_dir = rt.resolve(output_parent, need="list")
            out_dir.mkdir(parents=True, exist_ok=True)
            parser_kwargs["output_dir"] = str(out_dir)
        except Exception as e:
            return _err(type(e).__name__, message=str(e))

    parsed = await extract_text_from_files(input_paths, **parser_kwargs)

    outputs: List[str] = []
    if isinstance(parsed, dict):
        filenames = parsed.get("filenames") or parsed.get("outputs") or []
        for fp in filenames:
            try:
                h = rt.publish_path(filename_to_path(fp), perm="r")
                outputs.append(h)
            except Exception:
                continue

    rt.touch()
    return _ok(
        downloaded=downloaded["results"],
        extracted={"outputs": outputs},
    )
