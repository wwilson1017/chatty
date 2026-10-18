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
count as Enter on the target. Delete / Backspace (additive to PR 3's checked-key
list) are editing keys in a text field and a `delete` gate on any other focused
element: a mail row or a file-manager item is destroyed on that keystroke.
"""

import json
import re
from dataclasses import asdict, dataclass

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
CLICK_MEMBERS = frozenset(c for c in _CLICKS if not c.startswith("act:"))  # the toolset's pixel clicks, checked at press time
_ACTIVATABLE_ROLES = frozenset({"button", "link", "checkbox", "radio", "switch", "menuitem", "menuitemcheckbox",
                                "menuitemradio", "tab", "option", "treeitem"})
_TEXT_INPUT_TYPES = frozenset({"", "text", "search", "email", "url", "tel", "number", "password"})
# Both xdotool (ctrl, super) and Playwright (Control, Meta, ControlOrMeta) spellings.
_MODS = {"ctrl", "control", "cmd", "meta", "super", "command", "controlormeta", "controlorcommand"}
_IGNORED_MODS = {"shift", "alt", "option"}
_ENTER = {"return", "enter", "kp_enter", "numpadenter", "\r", "\n"}
_SPACE = {"space", " "}
_DELETE = {"delete", "del", "backspace", "\x7f", "\b"}  # xdotool and Playwright names; Shift/Ctrl variants included
_EDIT_ROLES = frozenset({"textbox", "searchbox", "combobox"})  # where Delete/Backspace only edit text
# Keys known not to activate anything: navigation keys, function keys, and Playwright's code
# names for printable characters. Anything else is treated as Enter — an alias we didn't
# anticipate must fail closed, not slip through unclassified.
_FREE_KEY = re.compile(r"^(?:arrow(?:up|down|left|right)|up|down|left|right|tab|escape|esc"
                       r"|home|end|pageup|pagedown|page_up|page_down|prior|next|insert|capslock"
                       r"|f(?:[1-9]|1[0-9]|2[0-4])|key[a-z]|digit[0-9]|numpad[0-9]"
                       r"|numpad(?:add|subtract|multiply|divide|decimal))$")
_NEWLINES = "\r\n\x0b\x0c  "


@dataclass(frozen=True)
class _Key:
    key: str   # "enter" | "space" | "delete" | a free key | a single printable character
    mod: bool  # Ctrl/Cmd held


def _key_of(label: str) -> _Key | None:
    """The key a label presses, or None for clicks and acts. `type` labels count as Enter.
    Unknown key names are read as Enter (fail closed)."""
    if label in ("type", "act:type"):
        return _Key("enter", False)
    for prefix in ("key:", "hold_key:", "act:press:"):
        if label.startswith(prefix):
            parts = [p.lower() for p in label[len(prefix):].split("+")]
            names = [p.strip() for p in parts]
            mod = any(n in _MODS for n in names)
            rest = [(n, p) for n, p in zip(names, parts) if n not in _MODS and n not in _IGNORED_MODS]
            name, raw = rest[-1] if rest else ("", "")
            if name in _ENTER or raw in _ENTER:
                return _Key("enter", mod)
            if name in _SPACE or raw in _SPACE:
                return _Key("space", mod)
            if name in _DELETE or raw in _DELETE:
                return _Key("delete", mod)
            if (len(name) == 1 and name.isprintable()) or _FREE_KEY.match(name):
                return _Key(name, mod)
            return _Key("enter", mod)
    return None


def needs_check(label: str, text: str | None = None) -> bool:
    """Whether `label` is a checked action. Screenshots, zoom, mouse moves, scroll, wait,
    cursor position, mouse-up, fill, hover, navigation and tab actions are always free."""
    if label in _CLICKS or label == "act:select":
        return True
    if label in ("type", "act:type"):
        return any(c in (text or "") for c in _NEWLINES)
    key = _key_of(label)
    if key is None:
        return False
    return key.key in ("enter", "space", "delete") or (key.mod and key.key == "s")


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

    # A key press is an activation when it can fire something: Enter anywhere, Space on a control,
    # Delete/Backspace on anything that isn't a text field (a focused mail row or file is destroyed
    # at once; in a field they edit). Space in a text field is a space; Enter in a textarea is a
    # newline (rule 7 decides composers).
    if key:
        if key.key == "delete":
            if editable or (tag == "input" and itype in _TEXT_INPUT_TYPES) or role in _EDIT_ROLES:
                return FREE
            return _gated("delete", "1.delete-key", name or role or tag, multi)
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

    # 7. Enter in a text field. Outside a form it sends (a composer, a chat box, a one-field widget
    #    that posts from a key handler) unless the field is a search box; in a textarea inside a form
    #    it is a newline only when the form was positively identified by rule 2.
    if key and key.key == "enter":
        text_field = editable or (tag == "input" and itype in _TEXT_INPUT_TYPES)
        if not in_form and text_field and itype != "search":
            return _gated("send", "7.composer", name, multi)
        if in_form and editable and not (_is_login(form, name) or _is_search(form, checkout)):
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


# ── approvals: what an approval is bound to ──────────────────────────────────

@dataclass(frozen=True)
class ApprovalBinding:
    """The facts an approval is bound to — exactly the fields the computer re-checks inside the
    click request (`expect`). Built from the STORED gate when the approved action is dispatched,
    never from a fresh observation (which only locates a candidate), so an approved Enter stays an
    Enter and an approved total stays that total. Shared by approvals.py (the card), runner.py
    (dispatch) and the computer (`expect`)."""

    action: str
    host: str
    path: str
    frame_url: str | None
    role: str | None
    name: str
    form_action: str | None
    context_fp: str | None   # form fields, or a composer's recipients + text; None when unreadable
    total: dict | None       # {amount, currency}; None when the page showed no single order total

    @classmethod
    def from_element(cls, action: str, element: dict) -> "ApprovalBinding":
        page = element.get("page") or {}
        total = element.get("total")
        return cls(action, page.get("host") or "", page.get("path") or "", element.get("frame_url"),
                   element.get("role"), element.get("name") or "", (element.get("form") or {}).get("action"),
                   element.get("context_fp"),
                   {"amount": total["amount"], "currency": total["currency"]} if isinstance(total, dict) else None)

    @classmethod
    def from_gate(cls, gate: dict) -> "ApprovalBinding":
        total = json.loads(gate["total_json"]) if gate.get("total_json") else None
        return cls(gate.get("action") or "", gate.get("host") or "", gate.get("path") or "", gate.get("frame_url"),
                   gate.get("role"), gate.get("name") or "", gate.get("form_action"), gate.get("context_fp"),
                   {"amount": total["amount"], "currency": total["currency"]} if isinstance(total, dict) else None)

    def expect(self) -> dict:
        """The computer's `expect`: the seven required fields plus context_fp / total when bound."""
        x = asdict(self)
        if not x["context_fp"]:
            del x["context_fp"]
        if not x["total"]:
            del x["total"]
        return x

    def mismatches(self, other: "ApprovalBinding") -> list[str]:
        """Fields where `other` differs (name compared like the computer: case/whitespace-insensitive)."""
        out = []
        for k in ("action", "host", "path", "frame_url", "role", "form_action", "context_fp", "total"):
            if getattr(self, k) != getattr(other, k):
                out.append(k)
        if _norm(self.name).lower() != _norm(other.name).lower():
            out.append("name")
        return out


PIXEL_KINDS = frozenset({"left_click"})  # dispatch kinds that go through /actions (a toolset member), not /browser/act


def dispatch_for(action: str) -> tuple[str, dict] | None:
    """The ONE activation an approved action label is re-sent as — `(kind, extra params)`: a browser
    act, or for a pixel gate a single `left_click` at the located control's centre (runner.dispatch
    sends it through /actions with the stored `expect`, whose `action` must equal the member the
    computer sees — so only a plain left_click replays). None when the label can't be re-sent as one
    activation with the approved `expect`: multi-clicks, held keys, typed text, selects, mouse-down and
    drag presses, and pixel Enter/Space, whose focused target can't be restored without a click.
    # simplification: those become "take over to do this yourself" cards; upgrade: focus the located
    control via /browser/act and press with expect.action rewritten."""
    if action == "act:click":
        return "click", {}
    if action == "left_click":
        return "left_click", {}
    if action.startswith("act:press:"):
        key = _key_of(action)
        if key and key.key in ("enter", "space") and not key.mod:
            return "press", {"key": action[len("act:press:"):]}
    return None


def unbindable_reason(gate: dict) -> str | None:
    """Why an approval of this gate can't be bound to page facts — so the card becomes "take over
    to do this yourself" — or None when it can be dispatched by Chatty. We never pretend an
    approval is bound to details we couldn't read."""
    element = json.loads(gate["element_json"]) if gate.get("element_json") else None
    if not element or not element.get("found"):
        return "no page element could be read for this action"
    if dispatch_for(gate.get("action") or "") is None:
        return f"{gate.get('action') or 'the action'} can't be re-sent as one plain click or key press"
    b = ApprovalBinding.from_gate(gate)
    if gate["kind"] in ("send", "post") and not b.context_fp:
        return "no form or message composer could be read, so the recipient and text can't be pinned down"
    if gate["kind"] == "buy" and not b.total:
        return "the page shows no single order total (it is missing or ambiguous)"
    return None


def change_reason(bound: ApprovalBinding, fresh: ApprovalBinding | None) -> str:
    """One line for the new gate when the approved action can't be sent as approved."""
    if fresh is None:
        return "page changed: the approved control is no longer on the page"
    diff = bound.mismatches(fresh)
    if "total" in diff:
        fmt = lambda t: f"{t['amount']} {t['currency']}" if t else "none"  # noqa: E731
        return f"total changed {fmt(bound.total)} → {fmt(fresh.total)}"
    if "context_fp" in diff:
        return "form changed: the fields, recipients or text differ from what was approved"
    if {"host", "path", "frame_url", "form_action"} & set(diff):
        return "page changed: the control now belongs to a different page or form"
    return "control changed: " + ", ".join(diff)


_SNAPSHOT_LINE = re.compile(r'^\s*-\s*([a-z]+)\s+"((?:[^"\\]|\\.)*)"[^\n]*?\[ref=([A-Za-z0-9]+)\]', re.M)


def locate(snapshot: str, role: str | None, name: str) -> list[str]:
    """Refs in a fresh aria snapshot whose role and name match the approved control — candidates
    only; the binding (and the computer) decide which, if any, is the approved one."""
    want_role, want_name = (role or "").lower(), _norm(name).lower()
    return [m.group(3) for m in _SNAPSHOT_LINE.finditer(snapshot or "")
            if m.group(1).lower() == want_role and _norm(m.group(2).replace('\\"', '"')).lower() == want_name]
