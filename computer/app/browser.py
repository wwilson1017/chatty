"""Playwright attached over CDP to the Chromium the desktop launched.

Snapshots are `aria_snapshot(mode="ai")` with `[ref=eN]` markers; acting uses `aria-ref=` locators.
`describe()` explains the element behind a ref, a screen pixel or the focus, and `check_expect()`
re-reads that description right before an action. Password-field values are never read, and the
snapshot drops them before it leaves this module.
"""
import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import time
from decimal import Decimal, InvalidOperation

import httpx
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from .desktop import CDP_URL, PROFILES_DIR

ACT_TIMEOUT_MS = 5000
OFFLINE_CDP_PORT = 9223
SNAPSHOT_MAX_CHARS = 40000

METRICS_JS = ("() => ({sx: window.screenX, sy: window.screenY, ow: window.outerWidth, oh: window.outerHeight,"
              " iw: window.innerWidth, ih: window.innerHeight})")
DEEP_POINT_JS = """([x, y]) => {
  let e = document.elementFromPoint(x, y);
  while (e && e.shadowRoot) {
    const inner = e.shadowRoot.elementFromPoint(x, y);
    if (!inner || inner === e) break;
    e = inner;
  }
  return e;
}"""
DEEP_ACTIVE_JS = """() => {
  let e = document.activeElement;
  while (e && e.shadowRoot && e.shadowRoot.activeElement) e = e.shadowRoot.activeElement;
  return e && e !== document.body && e !== document.documentElement ? e : null;
}"""
FRAME_OFFSET_JS = "e => { const r = e.getBoundingClientRect(); return [r.x + e.clientLeft, r.y + e.clientTop]; }"
IS_PASSWORD_JS = "e => (e.type || '').toLowerCase() === 'password'"
# Describes an element: role/name/form facts plus the raw material for the context fingerprint.
# Password fields are skipped everywhere; their values are never read.
DESCRIBE_JS = """(el) => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const lower = s => norm(s).toLowerCase();
  const text = n => n.innerText || n.textContent || '';
  const tag = el.tagName.toLowerCase();
  const type = (el.getAttribute('type') || '').toLowerCase();
  const roleOf = () => {
    const r = el.getAttribute('role'); if (r) return r.split(/\\s+/)[0];
    if (tag === 'a') return el.hasAttribute('href') ? 'link' : 'generic';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'input') return ({submit: 'button', button: 'button', reset: 'button', image: 'button',
      checkbox: 'checkbox', radio: 'radio', range: 'slider', number: 'spinbutton', search: 'searchbox'})[type || 'text'] || 'textbox';
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'img') return 'img';
    if (tag === 'option') return 'option';
    if (el.isContentEditable) return 'textbox';
    return 'generic';
  };
  const nameOf = () => {
    const al = el.getAttribute('aria-label'); if (al) return al;
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\\s+/).map(id => el.ownerDocument.getElementById(id)).filter(Boolean).map(text).join(' ');
      if (norm(t)) return t;
    }
    if (el.labels && el.labels.length) return Array.from(el.labels).map(text).join(' ');
    if (tag === 'input') {
      if (type === 'submit' || type === 'button' || type === 'reset') return el.value || (type === 'submit' ? 'Submit' : type === 'reset' ? 'Reset' : '');
      if (type === 'image') return el.alt || el.value || '';
      return el.placeholder || el.title || '';
    }
    if (tag === 'img') return el.alt || el.title || '';
    const t = text(el); if (norm(t)) return t;
    const img = el.querySelector('img[alt]'); if (img) return img.alt;
    return el.title || '';
  };
  const form = el.form || el.closest('form');
  const isSubmit = !!form && ((tag === 'button' && (type === '' || type === 'submit'))
    || (tag === 'input' && (type === 'submit' || type === 'image')));
  const anchor = el.closest('a[href]');
  const r = el.getBoundingClientRect();
  const SKIP = ['password', 'hidden', 'submit', 'button', 'reset', 'image', 'file'];
  const EDITOR = '[contenteditable=""],[contenteditable="true"],[contenteditable="plaintext-only"]';
  const fieldValue = f => {
    const ft = (f.type || '').toLowerCase();
    if (ft === 'checkbox' || ft === 'radio') return f.checked ? 'on' : 'off';
    if (f.tagName === 'SELECT') return Array.from(f.selectedOptions).map(o => lower(o.value || o.textContent)).join('|');
    return lower(f.value);
  };
  let context = null;
  let formInfo = null;
  if (form) {
    const fields = [];
    const formFields = [];  // shape only (name/type/autocomplete/visible), never a value
    for (const f of Array.from(form.elements)) {
      const ft = (f.type || '').toLowerCase();
      if (['submit', 'button', 'reset', 'image'].includes(ft) || f.tagName === 'FIELDSET' || f.tagName === 'BUTTON' || f.tagName === 'OUTPUT') continue;
      const fr = f.getBoundingClientRect();
      const fname = lower(f.name || f.id || f.getAttribute('aria-label') || '');
      formFields.push({name: fname, type: f.tagName === 'SELECT' ? 'select' : f.tagName === 'TEXTAREA' ? 'textarea' : (ft || 'text'),
                       autocomplete: (f.getAttribute('autocomplete') || '').toLowerCase() || null,
                       visible: fr.width > 0 && fr.height > 0});
      if (SKIP.includes(ft)) continue;
      fields.push([fname, fieldValue(f)]);
    }
    for (const ce of form.querySelectorAll(EDITOR)) fields.push(['editor', lower(text(ce))]);
    context = {kind: 'form', fields};
    formInfo = {action: form.action || null, method: lower(form.method || 'get'),
                role: (form.getAttribute('role') || '').toLowerCase() || null,
                text: lower(text(form)).slice(0, 1000), fields: formFields};
  } else {
    let c = el;
    while (c && c !== el.ownerDocument.body && !c.querySelector(EDITOR + ',textarea')) c = c.parentElement;
    if (c && c !== el.ownerDocument.body) {
      const fields = [];
      for (const chip of c.querySelectorAll('[role="option"],[role="listitem"],[data-hovercard-id],[email],[class*="chip" i],[class*="recipient" i],[class*="token" i]')) {
        const t = lower(chip.getAttribute('email') || chip.getAttribute('data-hovercard-id') || text(chip));
        if (t) fields.push(['chip', t]);
      }
      for (const ed of c.querySelectorAll(EDITOR + ',textarea')) {
        if ((ed.type || '').toLowerCase() === 'password') continue;
        fields.push(['editor', lower(ed.tagName === 'TEXTAREA' ? ed.value : text(ed))]);
      }
      if (fields.length) context = {kind: 'composer', fields};
    }
  }
  return {tag, role: roleOf(), name: norm(nameOf()).slice(0, 300), type: type || null,
          href: anchor ? anchor.href : null, is_submit: isSubmit, form: formInfo,
          box: {x: r.x, y: r.y, w: r.width, h: r.height}, context};
}"""

VALUE_LINE_RE = re.compile(r"^(\s*- (?:textbox|searchbox|combobox|spinbutton)\b.*?\[ref=([a-z0-9]+)\][^:\n]*): (.+)$")
CURRENCY = r"[$€£¥]|\b(?:USD|EUR|GBP|CAD|AUD|JPY|CHF|MXN|NZD)\b"
AMOUNT = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
MONEY_RE = re.compile(rf"(?:(?P<c1>{CURRENCY})\s?(?P<a1>{AMOUNT}))|(?:(?P<a2>{AMOUNT})\s?(?P<c2>{CURRENCY}))", re.I)
SUBTOTAL_RE = re.compile(r"sub\s*-?\s*total", re.I)
CURRENCY_NAMES = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
EXPECT_FIELDS = ("action", "host", "path", "frame_url", "role", "name", "form_action")


class BrowserError(Exception):
    """A browser-level failure the caller can act on (-> 4xx/5xx with its message)."""


def normalise_name(name) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip().lower()


def parse_total(snapshot: str):
    """The single snapshot line that says "total" (not "subtotal") with one money amount.
    None when no line mentions a total, "ambiguous" when the total can't be pinned down."""
    # simplification: amounts as 1,234.56 or 1234.56 with a symbol or ISO code; the upgrade is a
    # locale-aware parser once a real checkout defeats this one.
    candidates, saw_total = [], False
    for line in snapshot.splitlines():
        if "total" not in line.lower() or SUBTOTAL_RE.search(line):
            continue
        saw_total = True
        amounts = [(m.group("c1") or m.group("c2"), m.group("a1") or m.group("a2")) for m in MONEY_RE.finditer(line)]
        if len(amounts) == 1:
            text = line.split("]: ", 1)[-1] if "]: " in line else line  # drop the `- role [ref=eN]:` prefix
            candidates.append((text.strip().strip('"'), amounts[0]))
    if not saw_total:
        return None
    if len(candidates) != 1:
        return "ambiguous"
    line, (cur, amt) = candidates[0]
    try:
        amount = str(Decimal(amt.replace(",", "")).quantize(Decimal("0.01")))
    except InvalidOperation:
        return "ambiguous"
    return {"amount": amount, "currency": CURRENCY_NAMES.get(cur, cur.upper()), "text": line[:200]}


def context_fingerprint(context) -> str | None:
    if not context or not context.get("fields"):
        return None
    canonical = json.dumps(sorted(context["fields"]), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


class BrowserSession:
    def __init__(self):
        self._pw = None
        self.browser = None
        self.agent: str | None = None

    @property
    def connected(self) -> bool:
        return self.browser is not None and self.browser.is_connected()

    async def connect(self, agent: str, download_dir: str):
        await self.close()
        self._pw = await async_playwright().start()
        self.browser = await self._pw.chromium.connect_over_cdp(CDP_URL)
        os.makedirs(download_dir, exist_ok=True)
        cdp = await self.browser.new_browser_cdp_session()
        await cdp.send("Browser.setDownloadBehavior",
                       {"behavior": "allow", "downloadPath": download_dir, "eventsEnabled": True})
        await cdp.detach()
        self.agent = agent

    async def close(self):
        if self.browser is not None:
            try:
                await self.browser.close()
            except PlaywrightError:
                pass
        if self._pw is not None:
            await self._pw.stop()
        self._pw = self.browser = self.agent = None

    @property
    def context(self):
        if not self.connected:
            raise BrowserError("browser is not connected")
        return self.browser.contexts[0]

    def pages(self):
        return [p for p in self.context.pages if not p.is_closed()]

    async def current_page(self):
        """The foreground tab (the only one `visibilityState` reports visible)."""
        pages = self.pages()
        if not pages:
            return await self.context.new_page()
        for p in pages:
            try:
                if await p.evaluate("document.visibilityState") == "visible":
                    return p
            except PlaywrightError:
                continue
        return pages[-1]

    async def tabs(self, current):
        out = []
        for i, p in enumerate(self.pages()):
            try:
                title = await p.title()
            except PlaywrightError:
                title = ""
            out.append({"index": i, "url": p.url, "title": title, "active": p is current})
        return out

    # ----- snapshot --------------------------------------------------------------------------

    async def raw_snapshot(self, page) -> str:
        snap = await page.locator("body").aria_snapshot(mode="ai", timeout=ACT_TIMEOUT_MS)
        return await self._redact_passwords(page, snap)

    async def _redact_passwords(self, page, snap: str) -> str:
        out = []
        for line in snap.splitlines():
            m = VALUE_LINE_RE.match(line)
            if m:
                try:
                    is_pw = await page.locator(f"aria-ref={m.group(2)}").evaluate(IS_PASSWORD_JS, timeout=1000)
                except PlaywrightError:
                    is_pw = True  # can't tell: drop the value
                if is_pw:
                    line = m.group(1)
            out.append(line)
        return "\n".join(out)

    async def snapshot(self, max_chars: int = SNAPSHOT_MAX_CHARS) -> dict:
        page = await self.current_page()
        snap = await self.raw_snapshot(page)
        truncated = len(snap) > max_chars
        return {
            "url": page.url, "title": await page.title(),
            "snapshot": snap[:max_chars], "truncated": truncated,
            "total": parse_total(snap), "tabs": await self.tabs(page),
        }

    # ----- locating ----------------------------------------------------------------------------

    async def page_offset(self, page) -> tuple[int, int, dict]:
        """Screen pixel of the viewport's top-left corner: window position plus the toolbar.
        Chromium's own frame, when it draws one, has the same border on all four sides, so the
        side border is `(outer - inner) / 2` horizontally and is subtracted from the vertical
        difference too (spike measured at 1280x800: 4 px per side unmaximised, 0 maximised)."""
        m = await page.evaluate(METRICS_JS)
        side = (m["ow"] - m["iw"]) // 2
        return m["sx"] + side, m["sy"] + (m["oh"] - m["ih"]) - side, m

    async def _descend(self, frame, handle, x, y):
        """Follow iframes from a hit element until it isn't one. Returns (frame, element, x, y)."""
        for _ in range(8):
            el = handle.as_element() if handle else None
            if el is None:
                return frame, None, x, y
            if (await el.evaluate("e => e.tagName.toLowerCase()")) != "iframe":
                return frame, el, x, y
            child = await el.content_frame()
            if child is None:
                return frame, el, x, y
            ox, oy = await el.evaluate(FRAME_OFFSET_JS)
            x, y, frame = x - ox, y - oy, child
            handle = await frame.evaluate_handle(DEEP_POINT_JS, [x, y])
        return frame, None, x, y

    async def element_at_pixel(self, page, sx: int, sy: int):
        ox, oy, m = await self.page_offset(page)
        x, y = sx - ox, sy - oy
        if not (0 <= x < m["iw"] and 0 <= y < m["ih"]):
            return None, None
        handle = await page.main_frame.evaluate_handle(DEEP_POINT_JS, [x, y])
        frame, el, _, _ = await self._descend(page.main_frame, handle, x, y)
        return frame, el

    async def focused_element(self, page):
        frame = page.main_frame
        for _ in range(8):
            handle = await frame.evaluate_handle(DEEP_ACTIVE_JS)
            el = handle.as_element()
            if el is None:
                return frame, None
            if (await el.evaluate("e => e.tagName.toLowerCase()")) != "iframe":
                return frame, el
            child = await el.content_frame()
            if child is None:
                return frame, el
            frame = child
        return frame, None

    async def element_by_ref(self, page, ref: str):
        try:
            el = await page.locator(f"aria-ref={ref}").element_handle(timeout=2000)
        except PlaywrightError:
            return None, None
        return await el.owner_frame(), el

    async def _frame_screen_offset(self, page, frame) -> tuple[float, float]:
        ox, oy, _ = await self.page_offset(page)
        f = frame
        while f.parent_frame is not None:
            fe = await f.frame_element()
            fx, fy = await fe.evaluate(FRAME_OFFSET_JS)
            ox, oy = ox + fx, oy + fy
            f = f.parent_frame
        return ox, oy

    async def describe(self, page, *, ref: str | None = None, point: tuple[int, int] | None = None,
                       focused: bool = False) -> dict:
        if ref:
            frame, el = await self.element_by_ref(page, ref)
        elif point is not None:
            frame, el = await self.element_at_pixel(page, *point)
        elif focused:
            frame, el = await self.focused_element(page)
        else:
            raise BrowserError("give ref, point or focused")
        url = page.url
        parsed = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]*)([^?#]*)", url)
        base = {
            "found": el is not None,
            "page": {"host": parsed.group(1) if parsed else "", "path": (parsed.group(2) or "/") if parsed else "",
                     "title": await page.title()},
        }
        if el is None:
            return base
        info = await el.evaluate(DESCRIBE_JS)
        ox, oy = await self._frame_screen_offset(page, frame)
        box = info.pop("box")
        context = info.pop("context")
        snap = await self.raw_snapshot(page)
        return {
            **base, **info, "ref": ref, "frame_url": frame.url,
            "context_kind": context["kind"] if context else None,
            "context_fp": context_fingerprint(context),
            "total": parse_total(snap),
            "box": box,
            "screen_box": {"x": round(ox + box["x"]), "y": round(oy + box["y"]), "w": round(box["w"]), "h": round(box["h"])},
        }

    @staticmethod
    def expect_mismatches(expect: dict, actual: dict, action: str) -> list[str]:
        """Fields of `expect` the live element no longer matches (empty = go ahead)."""
        if not actual.get("found"):
            return ["found"]
        current = {
            "action": action, "host": actual["page"]["host"], "path": actual["page"]["path"],
            "frame_url": actual.get("frame_url"), "role": actual.get("role"),
            "name": normalise_name(actual.get("name")),
            "form_action": (actual.get("form") or {}).get("action"),
        }
        bad = []
        for field in EXPECT_FIELDS:
            if field not in expect:
                bad.append(field)
                continue
            want = normalise_name(expect[field]) if field == "name" else expect[field]
            if want != current[field]:
                bad.append(field)
        if "context_fp" in expect and expect["context_fp"] is not None and expect["context_fp"] != actual.get("context_fp"):
            bad.append("context_fp")
        if "total" in expect and expect["total"] is not None:
            want, have = expect["total"], actual.get("total")
            if not isinstance(have, dict) or have["amount"] != str(want.get("amount")) or have["currency"] != want.get("currency"):
                bad.append("total")
        return bad

    # ----- acting --------------------------------------------------------------------------------

    async def act(self, kind: str, p: dict) -> dict:
        page = await self.current_page()
        ref = p.get("ref")
        loc = page.locator(f"aria-ref={ref}") if ref else None
        if kind in ("click", "fill", "select", "hover") and loc is None:
            raise BrowserError(f"{kind} needs a ref")
        try:
            if kind == "click":
                await loc.click(timeout=ACT_TIMEOUT_MS)
            elif kind == "fill":
                await loc.fill(str(p.get("text", "")), timeout=ACT_TIMEOUT_MS)
            elif kind == "type":
                text = str(p.get("text", ""))
                if loc is not None:
                    await loc.press_sequentially(text, delay=15, timeout=ACT_TIMEOUT_MS + len(text) * 20)
                else:
                    await page.keyboard.type(text, delay=15)
            elif kind == "press":
                key = p.get("key")
                if not key:
                    raise BrowserError("press needs a key")
                if loc is not None:
                    await loc.press(key, timeout=ACT_TIMEOUT_MS)
                else:
                    await page.keyboard.press(key)
            elif kind == "select":
                value = p.get("value")
                await loc.select_option(value if isinstance(value, list) else [value], timeout=ACT_TIMEOUT_MS)
            elif kind == "hover":
                await loc.hover(timeout=ACT_TIMEOUT_MS)
            elif kind == "scroll":
                if loc is not None:
                    await loc.scroll_into_view_if_needed(timeout=ACT_TIMEOUT_MS)
                else:
                    await page.mouse.wheel(int(p.get("dx", 0)), int(p.get("dy", 600)))
            elif kind == "navigate":
                url = p.get("url")
                if not url:
                    raise BrowserError("navigate needs a url")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            elif kind in ("back", "forward", "reload"):
                await getattr(page, "go_back" if kind == "back" else "go_forward" if kind == "forward" else "reload")(
                    wait_until="domcontentloaded", timeout=15000)
            elif kind == "new_tab":
                page = await self.context.new_page()
                if p.get("url"):
                    await page.goto(p["url"], wait_until="domcontentloaded", timeout=30000)
            elif kind == "switch_tab":
                page = self.pages()[int(p.get("index", 0))]
                await page.bring_to_front()
            elif kind == "close_tab":
                target = self.pages()[int(p["index"])] if p.get("index") is not None else page
                await target.close()
                page = await self.current_page()
            else:
                raise BrowserError(f"unknown act kind {kind!r}")
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=3000)
            except PlaywrightError:
                pass
            return {"url": page.url, "title": await page.title()}
        except (IndexError, ValueError) as e:
            raise BrowserError(str(e)) from e
        except PlaywrightError as e:
            raise BrowserError(str(e).splitlines()[0][:300]) from e

    # ----- stored site data ---------------------------------------------------------------------

    @staticmethod
    def cookie_db_path(agent: str) -> str:
        # Debian's Chromium 155 writes Default/Cookies; newer builds move it under Default/Network/
        newer = os.path.join(PROFILES_DIR, agent, "Default", "Network", "Cookies")
        return newer if os.path.exists(newer) else os.path.join(PROFILES_DIR, agent, "Default", "Cookies")

    @classmethod
    def list_sites(cls, agent: str) -> list[dict]:
        path = cls.cookie_db_path(agent)
        if not os.path.exists(path):
            return []
        db = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
        try:
            rows = db.execute("SELECT host_key, COUNT(*) FROM cookies GROUP BY host_key ORDER BY host_key").fetchall()
        finally:
            db.close()
        return [{"domain": host, "cookies": n} for host, n in rows]

    @staticmethod
    async def _clear_site(browser, domain: str):
        """Cookies for the host and its subdomains, plus all storage for the host's default-port
        origins. Storage.clearDataForOrigin needs a page-level CDP session (it has the storage
        partition); the browser-level one answers "Internal error"."""
        bare = domain.lstrip(".")
        context = browser.contexts[0]
        await context.clear_cookies(domain=re.compile(rf"(^|\.){re.escape(bare)}$"))
        pages = [p for p in context.pages if not p.is_closed()]
        page = pages[0] if pages else await context.new_page()
        cdp = await context.new_cdp_session(page)
        try:
            for origin in (f"https://{bare}", f"http://{bare}"):
                await cdp.send("Storage.clearDataForOrigin", {"origin": origin, "storageTypes": "all"})
        finally:
            await cdp.detach()
            if not pages:
                await page.close()

    async def clear_site_live(self, domain: str):
        try:
            await self._clear_site(self.browser, domain)
        except PlaywrightError as e:
            raise BrowserError(str(e).splitlines()[0][:300]) from e

    @staticmethod
    async def clear_site_offline(agent: str, domain: str):
        """The agent's Chromium isn't on the screen: open its profile headless on a side port, clear
        cookies and storage over CDP the same way, and close it so the change is on disk."""
        profile = os.path.join(PROFILES_DIR, agent)
        if not os.path.isdir(profile):
            return
        proc = subprocess.Popen(
            ["chromium", "--headless=new", f"--user-data-dir={profile}", f"--remote-debugging-port={OFFLINE_CDP_PORT}",
             "--remote-debugging-address=127.0.0.1", "--no-sandbox", "--disable-dev-shm-usage", "--no-first-run",
             "--password-store=basic", "--disk-cache-dir=/tmp/chromium-cache-offline", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                deadline = time.monotonic() + 30
                while True:
                    try:
                        await client.get(f"http://127.0.0.1:{OFFLINE_CDP_PORT}/json/version")
                        break
                    except httpx.HTTPError:
                        if proc.poll() is not None or time.monotonic() > deadline:
                            raise BrowserError("could not open the stored profile to clear it") from None
                        await asyncio.sleep(0.2)
            pw = await async_playwright().start()
            try:
                browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{OFFLINE_CDP_PORT}")
                await BrowserSession._clear_site(browser, domain)
                await browser.close()
            finally:
                await pw.stop()
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)  # a clean exit flushes the profile to disk
                proc.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    @staticmethod
    def delete_profile(agent: str):
        shutil.rmtree(os.path.join(PROFILES_DIR, agent), ignore_errors=True)
