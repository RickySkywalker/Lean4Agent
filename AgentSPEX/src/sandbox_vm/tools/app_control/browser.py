"""
Session-scoped Chromium driver (Playwright over CDP)

Tools:
- browser_navigate
- browser_action
- browser_screenshot
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastmcp import Context
from playwright.async_api import Error as PwError
from playwright.async_api import TimeoutError as PwTimeout
from playwright.async_api import async_playwright

from sandbox_vm.tools.session_management import MANAGER
from sandbox_vm.tools.utils import _err, _ok, _sid, _to_vpath

try:
    CDP_PORT = os.environ["CDP_PORT"]
except KeyError as e:
    print(f"Missing required env var: {e.args[0]}", file=sys.stderr)
    sys.exit(1)


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


BROWSER_NAV_OPEN_TAB = _env_bool("BROWSER_NAV_OPEN_TAB", True)
DEFAULT_ACTION_TIMEOUT_MS = int(os.environ.get("BROWSER_ACTION_TIMEOUT_MS", "10000"))

MAX_LABEL_LEN = 160
MAX_URL_LABEL_LEN = 120
MAX_RETURN_URL_LEN = 200  # for url_short

URL_PARAM_ALLOWLIST = {"q", "query", "k", "page", "p"}


async def _ws_url(retries: int = 3, delay: float = 2.0) -> str:
    """Get Chrome DevTools WebSocket URL with retry logic."""
    last_error = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"http://127.0.0.1:{CDP_PORT}/json/version")
                r.raise_for_status()
                return r.json()["webSocketDebuggerUrl"]
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                await asyncio.sleep(delay)
    raise last_error or RuntimeError("Failed to get CDP WebSocket URL")


def _shorten_nav_url(raw: str) -> str:
    try:
        sp = urlsplit(raw)
        # keep only a tiny allowlist of query params
        qs = [
            (k, v)
            for k, v in parse_qsl(sp.query, keep_blank_values=False)
            if k in URL_PARAM_ALLOWLIST
        ]
        new_q = urlencode(qs, doseq=True)
        short = urlunsplit((sp.scheme, sp.netloc, sp.path, new_q, ""))  # no fragment
        if len(short) > MAX_RETURN_URL_LEN:
            short = short[: MAX_RETURN_URL_LEN - 1] + "…"
        return short
    except Exception:
        return (
            raw[: MAX_RETURN_URL_LEN - 1] + "…"
            if len(raw) > MAX_RETURN_URL_LEN
            else raw
        )


_JS_DIGEST = r"""
() => {
  function pick(sel, n=4, L=160){
    return Array.from(document.querySelectorAll(sel))
      .map(n => (n.innerText||"").trim().replace(/\s+/g," "))
      .filter(Boolean).slice(0,n).map(t => t.slice(0,L));
  }
  const title = (document.title||"").trim();
  const meta  = (document.querySelector('meta[name="description"]')?.getAttribute('content')||"").trim();
  const main  = (document.querySelector("main, article, body")?.innerText||"")
                  .trim().replace(/\s+/g," ").slice(0, 800);
  const vpW = window.innerWidth  || document.documentElement.clientWidth  || 0;
  const vpH = window.innerHeight || document.documentElement.clientHeight || 0;
  return { title, meta, h1: pick("h1", 3, 180), h2: pick("h2", 3, 160), main, vpW, vpH };
}
"""

_JS_COLLECT = r"""
() => {
  const nodes = Array.from(document.querySelectorAll(`
    a[href], button, [role='button'],
    input[type='submit'], input[type='button'],
    input[type='search'], input[type='text'], textarea
  `));

  function isActionable(el) {
    if (!el.isConnected) return false;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden" || cs.pointerEvents === "none") return false;
    if (el.closest('[aria-hidden="true"]')) return false;

    const tag = el.tagName.toLowerCase();
    const roleAttr = (el.getAttribute("role") || "").toLowerCase();
    const typeAttr = (el.getAttribute("type") || "").toLowerCase();
    const href = tag === "a" ? (el.getAttribute("href") || "") : "";

    // invalid links, skip links, javascript pseudo-links
    if (tag === "a") {
      const hrefLC = href.trim().toLowerCase();
      if (!hrefLC || hrefLC.startsWith("#") || hrefLC.startsWith("javascript:")) return false;
      try {
        const u = new URL(href, location.origin);
        const host = (u.hostname||"").toLowerCase();
        const path = u.pathname||"";
        // filter obvious ad/redirectors
        if (host.includes("aax-") && host.includes("retail-direct")) return false;
        if (path.startsWith("/x/c/")) return false;
      } catch(e) {}
    }

    const isButton = tag === "button" || (tag === "input" && (typeAttr === "submit" || typeAttr === "button"));
    const isLink   = tag === "a";
    const isTextbox= (tag === "input" && (!typeAttr || typeAttr === "text" || typeAttr === "search"))
                     || tag === "textarea" || roleAttr === "searchbox" || roleAttr === "textbox";

    return (isButton || isLink || isTextbox);
  }

  function roleFor(el) {
    const tag = el.tagName.toLowerCase();
    const roleAttr = (el.getAttribute("role") || "").toLowerCase();
    const typeAttr = (el.getAttribute("type") || "").toLowerCase();
    let role = roleAttr || tag;
    if (tag === "a" && el.getAttribute("href")) role = "link";
    if (tag === "input") {
      if (typeAttr === "search") role = "searchbox";
      else if (!typeAttr || typeAttr === "text") role = "textbox";
      else if (typeAttr === "submit" || typeAttr === "button") role = "button";
    }
    return role;
  }

  function shortHref(href) {
    try {
      const u = new URL(href, location.origin);
      const s = `${u.hostname}${u.pathname}`;
      return s.length > 120 ? s.slice(0,119) + "…" : s;
    } catch(e) {
      return href.length > 120 ? href.slice(0,119) + "…" : href;
    }
  }

  function labelFor(el) {
    const tag = el.tagName.toLowerCase();
    const aria = el.getAttribute("aria-label") || "";
    const name = el.getAttribute("name") || "";
    const placeholder = el.getAttribute("placeholder") || "";
    const titleAttr = el.getAttribute("title") || "";
    const text = (el.innerText || "").trim().replace(/\s+/g, " ");
    const href = tag === "a" ? (el.getAttribute("href") || "") : "";
    // Prefer human text; use short URL only as last fallback
    const raw = aria || text || placeholder || name || titleAttr || "";
    if (raw) return raw;
    return shortHref(href) || tag;
  }

  function cssPath(el){
    const path=[]; let e=el, depth=0;
    while(e && e.nodeType===1 && depth<10){
      let s=e.nodeName.toLowerCase();
      if(e.id){ s+="#"+CSS.escape(e.id); path.unshift(s); break; }
      let nth=1, sib=e;
      while((sib=sib.previousElementSibling)) if(sib.nodeName.toLowerCase()===s) nth++;
      path.unshift(`${s}:nth-of-type(${nth})`); e=e.parentElement; depth++;
    }
    return path.join(">");
  }

  const vpW = (window.innerWidth  || document.documentElement.clientWidth  || 0);
  const vpH = (window.innerHeight || document.documentElement.clientHeight || 0);

  const items = [];
  for (const el of nodes) {
    if (!isActionable(el) || el.disabled) continue;

    const rect = el.getBoundingClientRect();
    const area = Math.max(0, rect.width) * Math.max(0, rect.height);
    if (area < 36) continue;

    const inViewport = !(rect.bottom <= 0 || rect.right <= 0 || rect.top >= vpH || rect.left >= vpW);

    // Center-point occlusion test
    let occluded = false;
    if (inViewport && rect.width >= 2 && rect.height >= 2) {
      const cx = Math.min(vpW - 1, Math.max(1, rect.left + rect.width/2));
      const cy = Math.min(vpH - 1, Math.max(1, rect.top  + rect.height/2));
      const topEl = document.elementFromPoint(cx, cy);
      occluded = !!(topEl && !el.contains(topEl) && topEl !== el);
    }

    const tag  = el.tagName.toLowerCase();
    const role = roleFor(el);
    const label = labelFor(el).slice(0, 160);
    const text = (el.innerText||"").trim().replace(/\s+/g," ");
    const href = tag === "a" ? (el.getAttribute("href") || "") : "";

    // selector cascade
    const selectors = [];
    if (el.id) selectors.push("#"+CSS.escape(el.id));
    const testid = el.getAttribute("data-testid") || el.getAttribute("data-qa") || "";
    if (testid) selectors.push(`[data-testid="${testid}"]`, `[data-qa="${testid}"]`);
    const aria = el.getAttribute("aria-label") || "";
    if (aria) selectors.push(`${tag}[aria-label="${aria}"]`);
    const placeholder = el.getAttribute("placeholder") || "";
    if (placeholder && (tag === "input" || tag === "textarea")) selectors.push(`${tag}[placeholder="${placeholder}"]`);
    const name = el.getAttribute("name") || "";
    if (name && tag !== "a") selectors.push(`${tag}[name="${name}"]`);
    const typeAttr = (el.getAttribute("type") || "").toLowerCase();
    if (typeAttr && (tag === "input" || tag === "button")) selectors.push(`${tag}[type="${typeAttr}"]`);
    if (text) selectors.push(`${tag}:has-text("${text.slice(0,40).replace(/"/g,'\\"')}")`);

    items.push({
      tag, role, typeAttr, aria, name, placeholder, titleAttr: el.getAttribute("title") || "",
      text, href,
      label,
      inViewport, occluded, area,
      left: Math.round(rect.left),
      top:  Math.round(rect.top),
      right: Math.round(rect.right),
      bottom: Math.round(rect.bottom),
      selectors: Array.from(new Set(selectors)).slice(0, 6),
      pathSig: cssPath(el)
    });
    if (items.length >= 300) break;
  }
  return items;
}
"""

_JS_PREVIEW = r"""
() => {
  const root = document.querySelector('main, article, [role="main"]') || document.body;
  const vpH = (window.innerHeight || document.documentElement.clientHeight || 0);

  const parts = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, null);
  let nChars = 0;
  while (walker.nextNode()) {
    const el = walker.currentNode;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none") continue;
    if (!el.innerText) continue;
    const r = el.getBoundingClientRect();
    const inVp = !(r.bottom <= 0 || r.top >= vpH);
    if (!inVp) continue;
    const tag = el.tagName.toLowerCase();
    if (["nav","aside","footer","script","style"].includes(tag)) continue;
    const txt = (el.innerText || "").trim().replace(/\s+/g," ");
    if (txt) {
      parts.push(txt);
      nChars += txt.length;
      if (nChars > 2000) break;
    }
  }

  let preview = parts.join(" ").slice(0, 1500);
  if (preview.length < 400) {
    const mainTxt = (root.innerText || "").trim().replace(/\s+/g," ").slice(0, 1500);
    preview = mainTxt;
  }

  const headings = Array.from(document.querySelectorAll("h1,h2,h3")).slice(0,6)
                   .map(n => (n.innerText||"").trim().replace(/\s+/g," ").slice(0,120));

  return { preview, headings };
}
"""


def _stable_id(*parts: str) -> str:
    fp = "|".join(p or "" for p in parts)
    return "e_" + hashlib.sha1(fp.encode("utf-8")).hexdigest()[:10]


def _rank_key(el: Dict[str, Any]) -> int:
    role = (el.get("role") or "").lower()
    label = (el.get("label") or "").lower()
    href = (el.get("href") or "").lower()

    if href.startswith("#") or href.startswith("javascript:"):
        return -999

    score = 0
    if el.get("inViewport"):
        score += 6
    if el.get("occluded"):
        score -= 5
    try:
        score += min(int((el.get("area") or 0) / 3000), 4)
    except Exception:
        pass

    if role in {"searchbox", "textbox"}:
        score += 3
    if role == "button" and any(
        k in label for k in ("search", "submit", "go", "buy", "add to cart", "next")
    ):
        score += 2
    if role == "link" and any(k in label for k in ("next", "advanced search")):
        score += 1
    return score


def _truncate(s: str, max_chars: int) -> Tuple[str, bool]:
    b = s.encode("utf-8", "replace")
    if len(b) > max_chars:
        return b[:max_chars].decode("utf-8", "replace"), True
    return s, False


def _minimal_summary(d: Dict[str, Any]) -> str:
    parts = []
    if d.get("title"):
        parts.append(d["title"])
    if d.get("meta"):
        parts.append(d["meta"])
    if d.get("h1"):
        parts.append(" | ".join(d["h1"]))
    if d.get("h2"):
        parts.append(" | ".join(d["h2"]))
    if d.get("main"):
        parts.append(d["main"])
    txt = "\n".join(parts).strip()
    return _truncate(txt, 2000)[0]


@dataclass
class _SessionState:
    url: str = ""
    internal: List[Dict[str, Any]] = field(default_factory=list)
    public: List[Dict[str, Any]] = field(default_factory=list)
    # All visible elements with bounding boxes — used for SoM annotation
    all_visible: List[Dict[str, Any]] = field(default_factory=list)
    # SoM sequential-id → element dict (populated after browser_navigate/action with som=True)
    som_map: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    vp_w: int = 0
    vp_h: int = 0


@dataclass
class _BrowserWorker:
    session_id: str
    ws_url: Optional[str] = None
    thread: Optional[threading.Thread] = None
    loop: Optional[asyncio.AbstractEventLoop] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    ready_event: threading.Event = field(default_factory=threading.Event)
    last_used: float = field(default_factory=time.time)

    _pw: Any = None
    _browser: Any = None
    _context: Any = None
    _page: Any = None

    state: _SessionState = field(default_factory=_SessionState)
    start_error: Optional[BaseException] = None

    def touch(self):
        self.last_used = time.time()

    def start(self, timeout: float = 15.0):
        self.thread = threading.Thread(
            target=self._run, name=f"browser-{self.session_id}", daemon=True
        )
        self.thread.start()
        if not self.ready_event.wait(timeout):
            err = self.start_error
            raise RuntimeError(
                f"Browser worker failed to start within {timeout}s (CDP_PORT={os.getenv('CDP_PORT')})."
            ) from err

    def stop(self):
        try:
            if self.stop_event:
                self.stop_event.set()
            if self.thread:
                self.thread.join(timeout=3.0)
        except Exception:
            pass

    def _run(self):
        asyncio.run(self._main())

    async def _main(self):
        try:
            self.loop = asyncio.get_running_loop()
            if not self.ws_url:
                self.ws_url = await _ws_url()
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.connect_over_cdp(self.ws_url)
            self._context = await self._browser.new_context(accept_downloads=True)
            self._page = await self._context.new_page()
            self.ready_event.set()

            try:
                while not self.stop_event.is_set():
                    await asyncio.sleep(1.0)
            finally:
                try:
                    if self._context:
                        await self._context.close()
                except Exception:
                    pass
                try:
                    if self._browser and self._browser.is_connected():
                        await self._browser.close()
                except Exception:
                    pass
                try:
                    if self._pw:
                        await self._pw.stop()
                except Exception:
                    pass
        except Exception as e:
            self.start_error = e
            self.ready_event.set()
            raise

    def submit(self, coro) -> Future:
        self.touch()
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


async def _extract(page, state: _SessionState, *, limit: int) -> Dict[str, Any]:
    try:
        digest = await page.evaluate(_JS_DIGEST)
        summary = _minimal_summary(digest)
        state.vp_w = digest.get("vpW", 0)
        state.vp_h = digest.get("vpH", 0)
    except Exception:
        summary = ""

    content_preview = ""
    try:
        pv = await page.evaluate(_JS_PREVIEW)
        if pv and isinstance(pv, dict):
            if pv.get("headings"):
                summary = (summary + "\n" + " | ".join(pv["headings"])).strip()
            content_preview = pv.get("preview", "")[:1500]
    except Exception:
        pass

    try:
        raw = await page.evaluate(_JS_COLLECT)
        raw = sorted(raw, key=_rank_key, reverse=True)

        visible = [e for e in raw if e.get("inViewport") and not e.get("occluded")]
        offscr = [e for e in raw if e not in visible]

        limit = max(1, min(int(limit), 10))
        chosen = visible[:limit]
        if len(chosen) < limit:
            chosen += offscr[: (limit - len(chosen))]

        internal: List[Dict[str, Any]] = []
        public: List[Dict[str, Any]] = []
        for i, el in enumerate(chosen, 1):
            role = el.get("role") or el.get("tag") or "button"
            label = (el.get("label") or role)[:MAX_LABEL_LEN]
            sid = _stable_id(
                el.get("tag", ""),
                role,
                el.get("aria", ""),
                el.get("name", ""),
                el.get("typeAttr", ""),
                el.get("text", ""),
                el.get("pathSig", ""),
            )
            internal.append(
                {
                    "idx": i,
                    "target_id": sid,
                    "role": role,
                    "label": label,
                    "href": el.get("href") or "",
                    "selectors": el.get("selectors", []),
                    "pathSig": el.get("pathSig", ""),
                }
            )
            public.append(
                {
                    "target_id": sid,
                    "label": label,
                    "role": (
                        "type_text"
                        if role.lower() in {"textbox", "searchbox", "input", "textarea"}
                        else "click"
                    ),
                }
            )

        state.url = page.url
        state.internal = internal
        state.public = public
        state.all_visible = visible  # full list with bounding boxes for SoM
        return {
            "summary": summary,
            "actions": public,
            "content_preview": content_preview,
        }
    except Exception:
        state.url = page.url
        state.internal = []
        state.public = []
        return {"summary": summary, "actions": [], "content_preview": content_preview}


async def _reacquire_selector(page, rec: Dict[str, Any]) -> Optional[str]:
    """
    Re-collect actionable elements and try to find the same target again by:
      1) stable id match
      2) (role, label) exact match
      3) (role, label prefix) fuzzy match
    Returns a usable selector string or None.
    """
    try:
        raw = await page.evaluate(_JS_COLLECT)
    except Exception:
        return None

    # stable re-id
    for el in raw:
        sid = _stable_id(
            el.get("tag", ""),
            rec.get("role", ""),
            el.get("aria", ""),
            el.get("name", ""),
            el.get("typeAttr", ""),
            el.get("text", ""),
            el.get("pathSig", ""),
        )
        if sid == rec.get("target_id"):
            # prefer best selector available
            sels = el.get("selectors") or []
            if sels:
                return sels[0]
            if el.get("pathSig"):
                return el["pathSig"]

    # exact label+role
    role = (rec.get("role") or "").lower()
    label = rec.get("label") or ""
    for el in raw:
        if (el.get("label") or "") == label and (el.get("role") or "").lower() == role:
            sels = el.get("selectors") or []
            if sels:
                return sels[0]
            if el.get("pathSig"):
                return el["pathSig"]

    # fuzzy label prefix
    pref = label[:40]
    for el in raw:
        if (el.get("label") or "").startswith(pref) and (
            el.get("role") or ""
        ).lower() == role:
            sels = el.get("selectors") or []
            if sels:
                return sels[0]
            if el.get("pathSig"):
                return el["pathSig"]

    return None


async def _resolve_selector(
    page, state: _SessionState, *, target_id: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    rec = next((o for o in state.internal if o["target_id"] == target_id), None)
    if rec is None:
        return None, None
    for sel in rec.get("selectors", []):
        try:
            if await page.query_selector(sel):
                return sel, rec
        except Exception:
            continue
    ps = rec.get("pathSig")
    if ps:
        try:
            if await page.query_selector(ps):
                return ps, rec
        except Exception:
            pass

    new_sel = await _reacquire_selector(page, rec)
    if new_sel:
        return new_sel, rec
    return None, rec


async def _type_or_click(
    page, selector: str, role: str, text: Optional[str]
) -> Dict[str, Any]:
    try:
        loc = page.locator(selector).first

        try:
            await loc.scroll_into_view_if_needed(timeout=DEFAULT_ACTION_TIMEOUT_MS)
        except Exception:
            pass
        try:
            await page.evaluate(
                """sel => {
                    const el = document.querySelector(sel);
                    if (!el) return;
                    function scrollable(n){
                      while(n){
                        const s=getComputedStyle(n);
                        const oy = s.overflowY || s.overflow;
                        if ((n.scrollHeight>n.clientHeight) && (oy==='auto'||oy==='scroll')) return n;
                        n=n.parentElement;
                      }
                      return document.scrollingElement || document.documentElement || document.body;
                    }
                    const sc = scrollable(el);
                    const r  = el.getBoundingClientRect();
                    const mid = r.top - (window.innerHeight/2) + (r.height/2);
                    try { sc.scrollBy({top: mid, behavior:'instant'}); } catch {}
                    el.scrollIntoView({block:'center', inline:'center'});
                }""",
                selector,
            )
        except Exception:
            pass

        # Text entry
        if text is not None and role.lower() in {
            "textbox",
            "searchbox",
            "input",
            "textarea",
        }:
            try:
                await loc.click(timeout=DEFAULT_ACTION_TIMEOUT_MS)
            except Exception:
                pass
            try:
                await loc.fill("", timeout=DEFAULT_ACTION_TIMEOUT_MS)
            except Exception:
                try:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Backspace")
                except Exception:
                    pass
            await loc.fill(text, timeout=DEFAULT_ACTION_TIMEOUT_MS)
            try:
                submit = page.locator(
                    "button[type='submit'], input[type='submit']"
                ).first
                if await submit.count():
                    await submit.click(timeout=DEFAULT_ACTION_TIMEOUT_MS)
                else:
                    await page.keyboard.press("Enter")
            except Exception:
                pass
            return _ok()

        # Clickables
        try:
            await loc.click(timeout=DEFAULT_ACTION_TIMEOUT_MS)
            return _ok()
        except PwTimeout:
            try:
                await loc.focus(timeout=500)
                if role.lower() == "link":
                    await page.keyboard.press("Enter")
                else:
                    await page.keyboard.press("Space")
                return _ok()
            except Exception:
                pass
            try:
                await loc.click(timeout=1000, force=True)
                return _ok()
            except Exception as e2:
                return _err(f"INTERACTION_FAILED: {type(e2).__name__}: {e2}")
        except PwError as e:
            return _err(f"INTERACTION_FAILED: {type(e).__name__}: {e}")
    except (PwTimeout, PwError) as e:
        return _err(f"INTERACTION_FAILED: {type(e).__name__}: {e}")


async def _save_html_snapshot(rt, page) -> Optional[str]:
    try:
        html = await page.content()
        ts = time.strftime("%Y%m%d-%H%M%S")
        name = f"page-{ts}.html"
        out = rt.root / "url_download" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8", errors="ignore")
        return _to_vpath(rt.root, out)
    except Exception:
        return None


async def _capture_vision(rt, bw: "_BrowserWorker", som: bool) -> dict:
    """Capture a screenshot and optionally annotate it with Set-of-Marks.

    Returns a dict with zero or more of:
      screenshot_filename: vpath to the raw screenshot
      som_filename:        vpath to the SoM-annotated screenshot
      som_elements:        list of "id: N, text: ..., tag: ..." strings
    """
    # Wait for the page to visually settle before screenshotting.
    # "load" waits for all resources; the short timeout prevents hanging on
    # pages with persistent network activity (analytics, websockets).
    try:
        await bw._page.wait_for_load_state("load", timeout=5000)
    except Exception:
        pass
    # Small delay for JS-rendered content to paint after load fires.
    await asyncio.sleep(0.5)

    ts = time.strftime("%Y%m%d-%H%M%S")
    shot_path = rt.root / "shots" / f"shot-{ts}.png"
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    await bw._page.screenshot(path=shot_path)
    shot_vpath = _to_vpath(rt.root, shot_path)

    result: dict = {"screenshot_filename": shot_vpath}

    if som and bw.state.all_visible:
        from sandbox_vm.tools.app_control.som_annotator import annotate_som

        som_path = rt.root / "shots" / f"shot-{ts}-som.png"
        som_map, ac_tree = annotate_som(
            str(shot_path), bw.state.all_visible, str(som_path)
        )
        bw.state.som_map = som_map
        result["som_filename"] = _to_vpath(rt.root, som_path)
        result["som_elements"] = ac_tree

    return result


async def browser_navigate(
    ctx: Context,
    url: str,
    limit: int = 10,
    screenshot: bool = False,
    som: bool = True,
) -> dict:
    """
    Navigate the browser to a URL and extract page content and actionable elements.

    Args:
        url (required): The URL to navigate to.
        limit (optional): Maximum number of actionable elements to return. Defaults to 10.
        screenshot (optional): If True, capture a raw screenshot after navigation. Defaults to False.
        som (optional): If True, capture a Set-of-Marks annotated screenshot with numbered elements. Defaults to True.

    Returns:
        dict with keys: url, url_short, summary, content_preview, actions, local_filename,
                        and optionally screenshot_filename, som_filename, som_elements.
    """
    session_id = _sid(ctx)
    rt = MANAGER.get(session_id)

    bw = getattr(rt, "browser_worker", None)
    if bw is None or (bw.thread and not bw.thread.is_alive()):
        bw = _BrowserWorker(session_id=session_id)
        bw.start()
        rt.browser_worker = bw

    async def _run():
        try:
            if BROWSER_NAV_OPEN_TAB and bw._context:
                try:
                    if bw._page and not bw._page.is_closed():
                        await bw._page.close()
                except Exception:
                    pass
                bw._page = await bw._context.new_page()
            await bw._page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            return _err(f"NAVIGATION_ERROR: {type(e).__name__}: {e}", url=url)

        ext = await _extract(bw._page, bw.state, limit=limit)
        snap_vpath = await _save_html_snapshot(rt, bw._page)

        extra = {}
        if screenshot or som:
            extra.update(await _capture_vision(rt, bw, som))

        rt.touch()
        return _ok(
            url=bw._page.url,
            url_short=_shorten_nav_url(bw._page.url),
            summary=ext["summary"],
            content_preview=ext.get("content_preview", ""),
            actions=ext["actions"],
            local_filename=snap_vpath,
            **extra,
        )

    return await asyncio.wrap_future(bw.submit(_run()))


async def browser_action(
    ctx: Context,
    action_id: str,
    input_text: Optional[str] = None,
    limit: int = 10,
    screenshot: bool = False,
    som: bool = False,
) -> dict:
    """
    Perform an action on a browser element identified by its action_id.

    Args:
        action_id (required): The target_id of the element to interact with (from browser_navigate actions).
        input_text (optional): Text to type into input fields. If provided for a textbox/searchbox, the text will be entered and submitted.
        limit (optional): Maximum number of actionable elements to return after the action. Defaults to 10.
        screenshot (optional): If True, capture a screenshot after the action and include its path. Defaults to False.
        som (optional): If True, capture a Set-of-Marks annotated screenshot with numbered elements. Implies screenshot=True. Defaults to False.

    Returns:
        dict with keys: url, url_short, summary, content_preview, actions, local_filename,
                        and optionally screenshot_filename, som_filename, som_elements.
    """
    rt = MANAGER.get(_sid(ctx))
    bw = getattr(rt, "browser_worker", None)
    if not bw:
        return _err(
            "NO_ACTIVE_SESSION", message="Call browser_navigate(ctx, url) first."
        )

    async def _run():
        if not bw.state.internal:
            return _err(
                "NO_CONTEXT",
                message="Call browser_navigate(ctx, url) first to populate actions.",
            )

        sel, rec = await _resolve_selector(bw._page, bw.state, target_id=action_id)
        if rec is None:
            return _err("TARGET_NOT_FOUND_BY_ID", action_id=action_id)
        if not sel:
            return _err(
                "SELECTOR_UNRESOLVED",
                message="Element no longer resolvable; refresh candidates.",
                idx=rec.get("idx"),
                action_id=rec.get("target_id"),
            )

        role = rec.get("role", "")
        act = await _type_or_click(bw._page, sel, role, input_text)
        if "error" in act:
            return act

        try:
            await bw._page.wait_for_load_state(
                "domcontentloaded", timeout=DEFAULT_ACTION_TIMEOUT_MS
            )
        except Exception:
            pass

        ext = await _extract(bw._page, bw.state, limit=limit)
        snap_vpath = await _save_html_snapshot(rt, bw._page)

        extra = {}
        if screenshot or som:
            extra.update(await _capture_vision(rt, bw, som))

        rt.touch()
        return _ok(
            url=bw._page.url,
            url_short=_shorten_nav_url(bw._page.url),
            summary=ext["summary"],
            content_preview=ext.get("content_preview", ""),
            actions=ext["actions"],
            local_filename=snap_vpath,
            **extra,
        )

    return await asyncio.wrap_future(bw.submit(_run()))


async def browser_screenshot(ctx: Context, full_page: bool = False) -> dict:
    """
    Capture a screenshot of the current browser page.

    Args:
        full_page (optional): If True, captures the entire scrollable page. Defaults to False (viewport only).

    Returns:
        dict with keys: local_filename (path to the saved screenshot)
    """
    rt = MANAGER.get(_sid(ctx))
    bw = getattr(rt, "browser_worker", None)
    if not bw:
        return _err(
            "NO_ACTIVE_SESSION", message="Call browser_navigate(ctx, url) first."
        )

    ts = time.strftime("%Y%m%d-%H%M%S")
    out = rt.root / "shots" / f"shot-{ts}.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    async def _run():
        try:
            await bw._page.screenshot(path=out, full_page=full_page)
            vpath = _to_vpath(rt.root, out)
            rt.touch()
            return _ok(local_filename=vpath, screenshot_filename=vpath)
        except Exception as e:
            return _err(f"SCREENSHOT_ERROR: {type(e).__name__}: {e}")

    return await asyncio.wrap_future(bw.submit(_run()))


async def browser_click_element(ctx: Context, element_number: int) -> dict:
    """
    Click a numbered element from a Set-of-Marks screenshot.
    Call browser_navigate(som=True) or browser_action(som=True) first to populate element numbers.

    Args:
        element_number (required): The sequential number shown on the annotated SoM screenshot.

    Returns:
        dict with key: ok (bool), or error if element_number is not found.
    """
    rt = MANAGER.get(_sid(ctx))
    bw = getattr(rt, "browser_worker", None)
    if not bw:
        return _err("NO_ACTIVE_SESSION", message="Call browser_navigate first.")

    el = bw.state.som_map.get(element_number)
    if el is None:
        return _err(
            "SOM_ELEMENT_NOT_FOUND",
            message=f"Element {element_number} not in SoM map. Call browser_navigate(som=True) first.",
        )

    cx = (el["left"] + el["right"]) // 2
    cy = (el["top"] + el["bottom"]) // 2

    async def _run():
        await bw._page.mouse.click(cx, cy)
        rt.touch()
        return _ok(clicked_at={"x": cx, "y": cy}, label=el.get("label", ""))

    return await asyncio.wrap_future(bw.submit(_run()))


async def browser_type(
    ctx: Context,
    text: str,
    press_enter: bool = False,
) -> dict:
    """
    Type text into the currently focused browser element.
    Call browser_click_element first to focus the input field.

    Args:
        text (required): Text to type.
        press_enter (optional): Press Enter after typing. Defaults to False.

    Returns:
        dict with key: ok (bool)
    """
    rt = MANAGER.get(_sid(ctx))
    bw = getattr(rt, "browser_worker", None)
    if not bw:
        return _err("NO_ACTIVE_SESSION", message="Call browser_navigate first.")

    async def _run():
        await bw._page.keyboard.type(text)
        if press_enter:
            await bw._page.keyboard.press("Enter")
        rt.touch()
        return _ok()

    return await asyncio.wrap_future(bw.submit(_run()))


async def browser_key(ctx: Context, key: str) -> dict:
    """
    Press a keyboard key or shortcut on the current browser page.
    Follows Playwright key names (e.g. "Enter", "Tab", "Control+a", "ArrowDown", "Escape").

    Args:
        key (required): Key or key combination to press.

    Returns:
        dict with key: ok (bool)
    """
    rt = MANAGER.get(_sid(ctx))
    bw = getattr(rt, "browser_worker", None)
    if not bw:
        return _err("NO_ACTIVE_SESSION", message="Call browser_navigate first.")

    async def _run():
        await bw._page.keyboard.press(key)
        rt.touch()
        return _ok()

    return await asyncio.wrap_future(bw.submit(_run()))


async def browser_scroll(
    ctx: Context,
    direction: str = "down",
    amount: int = 300,
) -> dict:
    """
    Scroll the current browser page.

    Args:
        direction (optional): "up" or "down". Defaults to "down".
        amount (optional): Scroll distance in pixels. Defaults to 300.

    Returns:
        dict with key: ok (bool)
    """
    rt = MANAGER.get(_sid(ctx))
    bw = getattr(rt, "browser_worker", None)
    if not bw:
        return _err("NO_ACTIVE_SESSION", message="Call browser_navigate first.")

    delta_y = amount if direction == "down" else -amount

    async def _run():
        await bw._page.mouse.wheel(0, delta_y)
        rt.touch()
        return _ok()

    return await asyncio.wrap_future(bw.submit(_run()))


async def _browser_page_html(ctx: Context) -> dict:
    rt = MANAGER.get(_sid(ctx))
    bw = getattr(rt, "browser_worker", None)
    if not bw or not bw._page:
        return _err("NO_ACTIVE_SESSION", message="No browser page. Navigate first.")

    async def _run():
        return await bw._page.content()

    try:
        html = await asyncio.wrap_future(bw.submit(_run()))
        rt.touch()
        return _ok(html=html)
    except Exception as e:
        return _err("PAGE_HTML_ERROR", message=f"{type(e).__name__}: {e}")
