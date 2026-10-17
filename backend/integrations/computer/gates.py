"""
Chatty — the gate classifier. Run in Chatty BEFORE each consequential action the
helper asks for: it decides from the computer's /browser/element description
(PR 1) and the latest snapshot text whether the action may go to the computer or
must stop for approval. Pure; the first matching rule decides; a checked action
whose target can't be identified is a gate (fail closed).

Action labels follow the computer's `expect.action` convention: toolset members
(`left_click`, `left_mouse_down`, `key:ctrl+Return`, `hold_key:space`, `type`)
and browser acts (`act:click`, `act:press:Enter`, `act:select`, `act:type`).
`type` / `act:type` are checked only when the text contains a newline, and then
count as Enter on the target.
"""

import re
from dataclasses import dataclass

KINDS = ("buy", "delete", "post", "send", "submit")


@dataclass(frozen=True)
class Verdict:
    gated: bool
    kind: str | None = None  # one of KINDS when gated
    rule: str = ""           # which rule decided ("1.buy", "2.login", "6.form", "unidentified", "free")
    reason: str = ""
    # A repeat (double/triple click, held key, repeat > 1): refused even once approved —
    # an approval buys exactly one activation (PR 4 sends a single click/Enter/Space).
    multi: bool = False


FREE = Verdict(False, rule="free")

# ── what is checked at all ───────────────────────────────────────────────────

_CLICKS = frozenset({"left_click", "right_click", "middle_click", "double_click", "triple_click",
                     "left_mouse_down", "left_click_drag", "act:click"})
_ACTIVATABLE_ROLES = frozenset({"button", "link", "checkbox", "radio", "switch", "menuitem", "menuitemcheckbox",
                                "menuitemradio", "tab", "option", "treeitem"})
_TEXT_INPUT_TYPES = frozenset({"", "text", "search", "email", "url", "tel", "number", "password"})
_MODS = {"ctrl", "control", "cmd", "meta", "super", "command"}


@dataclass(frozen=True)
class _Key:
    key: str   # "enter" | "space" | "s" | anything else lowercased
    mod: bool  # Ctrl/Cmd held


def _key_of(label: str) -> _Key | None:
    """The key a label presses, or None for clicks and acts. `type` labels count as Enter."""
    if label in ("type", "act:type"):
        return _Key("enter", False)
    for prefix in ("key:", "hold_key:", "act:press:"):
        if label.startswith(prefix):
            parts = [p.strip().lower() for p in label[len(prefix):].split("+")]
            mod = any(p in _MODS for p in parts)
            key = next((p for p in parts if p not in _MODS and p not in ("shift", "alt")), "")
            if key in ("return", "enter", "kp_enter"):
                key = "enter"
            elif key in ("space", " "):
                key = "space"
            return _Key(key, mod)
    return None


def needs_check(label: str, text: str | None = None) -> bool:
    """Whether `label` is a checked action. Screenshots, zoom, mouse moves, scroll, wait,
    cursor position, mouse-up, fill, hover, navigation and tab actions are always free."""
    if label in _CLICKS or label == "act:select":
        return True
    if label in ("type", "act:type"):
        return "\n" in (text or "")
    key = _key_of(label)
    if key is None:
        return False
    return key.key in ("enter", "space") or (key.mod and key.key == "s")


# ── vocabularies (the plan's rule words) ─────────────────────────────────────

def _words(alts: str) -> re.Pattern:
    return re.compile(rf"(?<![a-z])(?:{alts})(?![a-z])", re.I)


KIND_WORDS: tuple[tuple[str, re.Pattern], ...] = (
    ("buy", _words(r"place (?:your |the )?order|buy|pay|purchase|confirm (?:order|payment|purchase)|subscribe|donate|transfer")),
    ("delete", _words(r"delete|remove account|erase|empty trash|close account|deactivate|cancel (?:subscription|order|account)")),
    ("send", _words(r"send|reply all|forward")),
    ("post", _words(r"post|publish|tweet|share|comment|reply|submit review")),
)
LOGIN_WORDS = _words(r"sign in|log in|login|continue")
SIGNUP_WORDS = _words(r"sign up|create|register|join|new password|confirm password")
CART_LEGWORK = _words(r"add to (?:cart|bag|basket)|update quantity|remove item|apply coupon")
CONTINUE = _words(r"continue|next")
LEGWORK = _words(r"add to (?:cart|bag|basket)|quantity|remove item|continue shopping|back|edit|change|search|filter|next page|continue|next")
CONFIRM = _words(r"confirm|finish|done|yes|ok|okay|agree|accept|approve|authori[sz]e|complete|save|update|create|register|join")
# "sign" as in e-sign; "sign in/up/out" are navigation (a login *submission* is decided by rules 2 and 6)
SIGN = re.compile(r"(?<![a-z])sign(?![a-z])(?!\s*[- ]?\s*(?:in|up|out)(?![a-z]))", re.I)
CHECKOUT = _words(r"cart|checkout|payments?|billing|orders?|pay")
# A payment form showing: card fields in the snapshot, or a payment / review-order heading.
PAYMENT_FIELDS = re.compile(r'(?:textbox|spinbutton|combobox|group)\s+"[^"]*(?:card number|credit card|cvc|cvv|security code|iban|expir)', re.I)
PAYMENT_HEADING = re.compile(r'heading\s+"[^"]*(?<![a-z])(?:payment|review (?:your |the )?order)(?![a-z])', re.I)
PAYMENT_FIELD_NAME = re.compile(r"card.?number|cvc|cvv|security.?code|iban|card.?expir", re.I)


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def payment_form_showing(page_text: str, form: dict | None) -> bool:
    if PAYMENT_FIELDS.search(page_text or "") or PAYMENT_HEADING.search(page_text or ""):
        return True
    for f in (form or {}).get("fields") or []:
        if str(f.get("autocomplete") or "").lower().startswith("cc-") or PAYMENT_FIELD_NAME.search(str(f.get("name") or "")):
            return True
    return False


def _is_login(form: dict | None, name: str) -> bool:
    """Exactly one password field (not new-password), at most two other visible fields, a sign-in
    word on the button or form, and no sign-up word anywhere on the form. Needs PR 1's
    form.fields and form.text; without them a login can't be positively identified."""
    if not form or form.get("fields") is None or form.get("text") is None:
        return False
    fields = form["fields"]
    pw = [f for f in fields if str(f.get("type") or "").lower() == "password"]
    if len(pw) != 1 or str(pw[0].get("autocomplete") or "").lower() == "new-password":
        return False
    others = [f for f in fields if f not in pw and f.get("visible", True) and str(f.get("type") or "").lower() != "hidden"]
    if len(others) > 2:
        return False
    text = _norm(form["text"])
    if not (LOGIN_WORDS.search(name) or LOGIN_WORDS.search(text)):
        return False
    return not (SIGNUP_WORDS.search(text) or SIGNUP_WORDS.search(name))


def _is_search(form: dict | None, checkout: bool) -> bool:
    if not form or checkout or str(form.get("method") or "get").lower() != "get":
        return False
    if str(form.get("role") or "").lower() == "search":
        return True
    fields = form.get("fields")
    return bool(fields) and len(fields) == 1 and str(fields[0].get("type") or "").lower() == "search"


def _gated(kind: str, rule: str, name: str, multi: bool) -> Verdict:
    return Verdict(True, kind, rule, f"{kind}: {name!r} ({rule})", multi)


def classify(label: str, element: dict | None, *, page_text: str = "", repeat: int = 1) -> Verdict:
    """Decide one checked action. `element` is the /browser/element description of the target
    (ref, pixel or focused element); `page_text` the latest snapshot (page-level facts)."""
    key = _key_of(label)
    multi = label in ("double_click", "triple_click") or label.startswith("hold_key:") or repeat > 1

    # Rule 1 (keys): Ctrl/Cmd+Enter anywhere is send; Ctrl/Cmd+S anywhere saves (rule 5).
    if key and key.mod and key.key == "enter":
        return _gated("send", "1.send", "ctrl+enter", multi)
    if key and key.mod and key.key == "s":
        return _gated("submit", "5.confirm", "ctrl+s", multi)

    if not element or not element.get("found"):
        return _gated("submit", "unidentified", "(no element at the target)", multi)

    name = _norm(element.get("name"))
    tag = str(element.get("tag") or "").lower()
    role = str(element.get("role") or "").lower()
    itype = str(element.get("type") or "").lower()
    form = element.get("form")
    in_form = form is not None or element.get("context_kind") == "form"
    page = element.get("page") or {}
    checkout = bool(CHECKOUT.search(f"{page.get('host') or ''}{page.get('path') or ''}") or CHECKOUT.search(page.get("title") or ""))
    editable = tag == "textarea" or (role == "textbox" and tag != "input")
    activatable = role in _ACTIVATABLE_ROLES or tag in ("button", "a") or (tag == "input" and itype not in _TEXT_INPUT_TYPES)

    # A key press is an activation when it can fire something: Enter anywhere, Space on a control.
    # Space in a text field is a space; Enter in a textarea is a newline (rule 7 decides composers).
    if key:
        if key.key == "space" and not activatable:
            return FREE
        if key.key not in ("enter", "space"):
            return FREE
    click_like = label in _CLICKS
    submits = (click_like and bool(element.get("is_submit"))) or \
              (key is not None and in_form and tag in ("input", "button") and not editable)
    payment = payment_form_showing(page_text, form)

    # 1. explicit kind words on the target
    for kind, rx in KIND_WORDS:
        if rx.search(name):
            return _gated(kind, f"1.{kind}", name, multi)

    # 2. positively identified form submissions, free — checked before any catch-all
    if submits:
        if _is_login(form, name):
            return Verdict(False, rule="2.login")
        if _is_search(form, checkout):
            return Verdict(False, rule="2.search")
        if checkout and CART_LEGWORK.search(name):
            return Verdict(False, rule="2.cart")
        if checkout and CONTINUE.search(name) and not payment:
            return Verdict(False, rule="2.shipping")

    # 3. non-submitting legwork, free (continue/next is a buy gate when a payment form shows)
    if not submits:
        if CONTINUE.search(name) and payment:
            return _gated("buy", "3.continue-payment", name, multi)
        if LEGWORK.search(name):
            return Verdict(False, rule="3.legwork")

    # 4. checkout pages: every other button or link click is a buy
    if checkout and activatable and role not in ("checkbox", "radio", "switch", "option", "tab", "treeitem"):
        return _gated("buy", "4.checkout", name, multi)

    # 5. generic confirmations
    if CONFIRM.search(name) or SIGN.search(name):
        return _gated("submit", "5.confirm", name, multi)

    # 6. any other form submission (sign-ups, password changes, "Update" forms, unidentified logins)
    if submits:
        return _gated("submit", "6.form", name, multi)

    # 7. Enter in a composer (textarea / contenteditable) outside a form
    if key and key.key == "enter" and not in_form and editable:
        return _gated("send", "7.composer", name, multi)

    return FREE


def expect_for(label: str, element: dict) -> dict:
    """The `expect` sent with a free checked action: the seven required fields from the element
    we classified, so the computer refuses (409 element_changed) if the target changed between
    our read and the click. Optional context_fp / total are left out for free actions —
    typing between snapshot and click legitimately changes a form's fingerprint."""
    page = element.get("page") or {}
    return {
        "action": label, "host": page.get("host") or "", "path": page.get("path") or "",
        "frame_url": element.get("frame_url"), "role": element.get("role"), "name": element.get("name") or "",
        "form_action": (element.get("form") or {}).get("action"),
    }
