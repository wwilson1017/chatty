# Spike findings (PR 1)

Measured on 2026-10-17 with Playwright 1.64.0, mcp-proxy 0.13.0 and the Debian trixie Chromium
(155.0.8059.79) inside this image, Xvfb 1280×800×24 + openbox.

## (a) `aria-ref=` locators over `connect_over_cdp`

Yes. Launch Chromium ourselves with `--remote-debugging-port=9222`, attach with
`chromium.connect_over_cdp("http://127.0.0.1:9222")`, take `page.locator("body").aria_snapshot(mode="ai")`,
and `page.locator("aria-ref=e10").click()` clicks the element the snapshot labelled `[ref=e10]`.

- Elements inside iframes get frame-prefixed refs (`[ref=f1e2]`) and `aria-ref=f1e2` resolves and
  clicks them too.
- A ref whose element was removed fails safely (`TimeoutError`), never clicks something else.
- **The `mode="ai"` snapshot includes textbox values, password fields included**
  (`- textbox "Password" [ref=e7]: s3cret-value`), whether the value was set by the page or typed
  with xdotool. `browser.py` therefore checks every value-carrying `textbox`/`searchbox`/
  `combobox`/`spinbutton` line's element (`e.type === 'password'`) and drops the value before the
  snapshot leaves the computer. Password values are never read (`.value`) anywhere in `browser.py`.

## (b) mcp-proxy's streamable-HTTP path for a named server

`mcp-proxy --named-server <name> '<command string>' --port <p> --host 127.0.0.1 --pass-environment`
serves:

- **`/servers/<name>/mcp`** — streamable HTTP (POST `initialize` → 200 with `Mcp-Session-Id`; the
  trailing-slash form works too). Verified end to end: `initialize`, `tools/list`, `tools/call`.
- `/servers/<name>/sse` — legacy SSE.
- `/status` — JSON with `server_instances` (the readiness probe `main.py` uses).

Named servers only inherit the proxy's environment with `--pass-environment`, so the control API
starts each proxy with a minimal environment (PATH, HOME, LANG) plus the user's variables, in memory
only. The command string is split by mcp-proxy itself (shlex), so `npx -y @scope/server --flag`
works as one string. mcp-proxy 0.13.0 needs `uvicorn>=0.47`, which is why `requirements.txt` pins
newer FastAPI/uvicorn than the Chatty backend.

## (c) Pixel → DOM offset at 1280×800 under Xvfb + openbox

With Chromium maximised and frameless (openbox rule `class="Chromium*"`: `decor=no`,
`maximized=yes`) and the `--no-sandbox` infobar suppressed by `--test-type`, the page's top-left
pixel is **(0, 87)**: `window.screenX/Y = 0`, `outerWidth − innerWidth = 0`,
`outerHeight − innerHeight = 87` (tab strip + toolbar). An xdotool click at the predicted pixel of
a button centred at DOM (400, 230) arrived as `clientX/Y = 400, 230` exactly, `elementFromPoint`
of the inverse mapping returned the button, and the mss screenshot (1280×800) showed the button's
colour at that pixel.

Two traps found on the way, both now handled:

- Without the openbox rule Chromium draws its own frame: `innerWidth` was 1272 (a 4 px border on
  every side), and `outerHeight − innerHeight` included the bottom border, so the naive
  `oy = oh − ih` was 4 px low. `browser.page_offset()` subtracts the side border from the vertical
  difference as well (`side = (ow − iw) / 2`), which is exact in both the framed and the frameless case.
- `--no-sandbox` shows a 57 px infobar ("unsupported command-line flag") that shifts the page down
  until someone closes it; `--test-type` suppresses it.

## Other things learned

- Debian trixie is the base (`python:3.12-slim-trixie`): it is current stable and ships Chromium
  155; bookworm still gets Chromium through proposed-updates but is in LTS.
- `mss.mss()` is deprecated in mss 10; the class is `mss.MSS(display=":1")`.
- xdotool `type` handles non-ASCII (`héllo wörld` arrived intact).
- Image size: about 2.7 GB on disk for amd64 (LibreOffice Writer/Calc, pcmanfm/GTK and Chromium are
  most of it; the plan guessed 1.4 GB).
