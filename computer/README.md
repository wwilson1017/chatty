# Chatty virtual computer

A Linux desktop in a container (Chromium, a terminal, a file manager, LibreOffice Writer/Calc) with
a small control API. Chatty's helper loop drives it over the API; people watch or take it over through
a VNC stream relayed by Chatty. The image is independent of the Chatty backend: nothing here imports
from `backend/`.

- Image: `ghcr.io/wwilson1017/chatty-computer:{latest,sha-<short>}`, built for amd64 and arm64 by
  `.github/workflows/computer-image.yml`.
- Volume: `/data` is the only persistent path. `/workspace` → `/data/workspace`, `HOME=/data/home`,
  browser profiles in `/data/profiles/<agent>`, the action journal in `/data/actions.db`.
- Environment: `COMPUTER_SECRET` (required, at least 32 characters, or the server refuses to start),
  `PORT` (default 8080), `HOST` (default `::` for Railway's IPv6 private network; use `0.0.0.0` with
  local Docker).
- Network exposure: only the control API port. Both VNC servers (`:5900` view-only, `:5901` control,
  present only during a takeover) and Chromium's CDP (`127.0.0.1:9222`) are bound to localhost.
- Run locally: `docker run -d --name chatty-computer --shm-size=1g -e COMPUTER_SECRET=<48 chars>
  -e HOST=0.0.0.0 -p 127.0.0.1:8765:8080 -v chatty-computer-data:/data ghcr.io/wwilson1017/chatty-computer`

Spike notes (aria-ref over CDP, mcp-proxy paths, pixel offset) are in `NOTES.md`.

## Conventions

- **Auth.** Every route except `GET /health` needs `Authorization: Bearer $COMPUTER_SECRET`
  (constant-time compare). Missing or wrong → `401 {"error":"unauthorized"}`. The WebSocket uses the
  same header; a bad one is refused before the upgrade (HTTP 403).
- **Errors** are `{"error": "<code>", "detail": "<sentence>", ...extra}` with the HTTP status below;
  anything unexpected is `500 {"error": "internal", "detail"}`. Malformed bodies get FastAPI's `422`.
- **Agent slugs** must match `^[a-z0-9-]{1,64}$` (`400 bad_agent`). `shared` is a slug every agent may
  use for files.
- **`api_version`** is `"1.0"`; Chatty refuses a different major.
- All timestamps are Unix seconds (floats).

## The screen lease

One agent's Chromium is on the screen at a time, and one task owns it. The lease is the lock; Chatty's
single-worker pool is not.

| Route | Body | 200 | Errors |
|---|---|---|---|
| `POST /desktop/activate` | `{agent, task_id?}` | `{lease, epoch, expires_in: 120}` | `409 busy` (`holder: {agent, task_id}`; or `reason: "operation_running"` while an operation under the previous, expired lease is still finishing — its shell process groups were just killed), `409 human_in_control`, `500 desktop_failed` |
| `POST /desktop/lease/renew` | `{lease}` | `{epoch, expires_in: 120, human_in_control, control_ended}` | `409 lease_lost` |
| `POST /desktop/lease/release` | `{lease}` | `{released: bool}` | — |

- Activation starts the desktop if it is idle (Xvfb, openbox, view-only VNC) and switches Chromium to
  `/data/profiles/<agent>` (about 2 s when the agent changes, instant otherwise). Downloads go to
  `/workspace/<agent>/downloads`.
- A lease lasts **120 s**; renew it every 30 s for the whole task, including model calls and takeover
  waits. Renew and release are the only agent calls allowed while a person has control.
- **Epoch** is `<boot_id>:<n>`; `n` increases on every activation and every time control ends. Every
  desktop call carries `{lease, epoch}`. Checks run in this order: `409 lease_lost` (token is not the
  live lease, or it expired), `409 stale_epoch` (body carries `epoch` with the current value), `409
  human_in_control`. A `lease_lost` or a failed renewal means the worker is fenced: send nothing more.
- After control ends, the renew response (and `GET /control/status`) carries the new epoch; use it from
  then on.

## Actions (screenshot-and-click)

`POST /actions` runs one member of Anthropic's `computer_toolset_20260801` on the real screen with
xdotool (mapping ported from the computer-use-demo). Screenshots are native 1280×800 PNGs from mss.

```json
{"action_id": "<ULID>", "lease": "…", "epoch": "…", "name": "left_click",
 "input": {"coordinate": [400, 317]}, "expect": {…optional, see below…}}
```

Members and inputs: `key {text, repeat?}`, `hold_key {text, duration}`, `type {text}`,
`cursor_position {}`, `mouse_move {coordinate}`, `left_mouse_down {coordinate?}`,
`left_mouse_up {coordinate?}`, `left_click|right_click|middle_click|double_click|triple_click
{coordinate?, text?}` (`text` is a held modifier chord such as `ctrl`), `left_click_drag
{start_coordinate, coordinate, text?}`, `scroll {coordinate?, scroll_direction, scroll_amount, text?}`,
`wait {duration}`, `screenshot {}`, `zoom {region: [x0, y0, x1, y1], scale?}` (scale is accepted and
ignored; the crop is scaled to fit 1280×800, aspect kept). Coordinates are screen pixels inside
1280×800; durations are 0–100 s; `repeat` is 1–100.

Responses:

| Status | Body |
|---|---|
| `200` | `{action_id, status: "done", result}` — `result` is `{image: "<base64 PNG>", width, height}` for `screenshot`, `{image}` for `zoom`, `{x, y}` for `cursor_position`, `{ok: true}` otherwise |
| `400 action_id_invalid` / `400 action_id_expired` | not a ULID, or created more than 24 h ago (not journaled) |
| `400 bad_input` | bad member or input; journaled as `failed` |
| `409 lease_lost` / `409 stale_epoch` / `409 human_in_control` | refused before anything is journaled |
| `409 action_conflict` | this `action_id` was already used with a different payload |
| `409 element_changed` | the `expect` check failed; journaled as `failed`, nothing was clicked. Body adds `mismatches: [field…]`, `expected`, `actual` |
| `409 outcome_unknown` | a repeat of an id whose outcome is `unknown` (restart mid-action) or still in flight after 60 s |
| `500 action_failed` | xdotool or browser failure; journaled as `failed` |

### The action journal

- The id is reserved atomically with `sha256(canonical JSON of {name, input, expect})` before anything
  runs (`/browser/act` hashes `{kind, …params, expect}`). Status moves `reserved → executing → done |
  failed`.
- The **same id with the same payload** returns the stored status and body and never acts again
  (concurrent repeats wait for the first and then get the same answer). Images are not stored: a
  replayed `screenshot`/`zoom` returns `result.image: null, image_omitted: true`.
- The same id with a **different payload** → `409 action_conflict`. Use a fresh ULID for a changed action.
- Rows still `reserved` or `executing` when the process died become `unknown` at the next start and are
  never re-run. Rows are pruned after 7 days; ids older than 24 h (or more than 5 minutes in the future)
  are rejected, so a pruned id can't come back as a new action.
- `GET /actions/{id}` → `{action_id, status, http_status, response}` (`404 unknown_action` if never seen).

### `expect` — binding an action to what was approved

Send `expect` with any click, mouse-down, drag start, `key`, `hold_key`, `type`, or `/browser/act`
`click|fill|type|press|select|hover`. Right before acting, in the same request, the computer describes
the element the action would hit — the pixel under the click (or under the cursor for a click without a
coordinate), the focused element for keys and typing, the ref for browser acts — and compares:

| Field | Compared with |
|---|---|
| `action` | the action label: the member name (`left_click`), `key:<text>` / `hold_key:<text>` for keys, `act:<kind>` for browser acts, `act:press:<key>` for a browser press |
| `host`, `path` | the page's URL host and path (`""` for non-URL pages such as `data:`) |
| `frame_url` | the URL of the frame the element is in |
| `role`, `name` | the element's role and accessible name (name compared case- and whitespace-insensitively) |
| `form_action` | the enclosing form's resolved `action` URL, or `null` |
| `context_fp` (optional) | the context fingerprint, when not `null` |
| `total` (optional) | `{amount, currency}` must equal the page's single order total, as `/browser/element` returned it (`amount` is a string with two decimals, e.g. `"45.00"`; `currency` an ISO code) |
| `box` (optional) | `{x, y, w, h}` in screen pixels, when not `null`: each of the four must be within 4 px of the element's `screen_box` (send a mark's `box` when pressing it) |

All seven required fields must be present and equal; any difference, or no element at the target, is
`409 element_changed` with `mismatches`. This narrows the race between reading the DOM and the OS-level
click but can't make them atomic against page scripts: best effort. Two controls with the same role,
name and position can't be told apart.

## Marked screenshot

**`POST /screen/marked`** `{lease, epoch}` → `{observation_id, epoch, image, marks: [{n, role, name, box,
point}]}`. A desktop call like the others (`409 lease_lost` / `stale_epoch` / `human_in_control`); not
journaled.

- `image` is the 1280×800 screen as a base64 PNG, each mark's box outlined with its number on a tab at
  the top-left corner. `observation_id` (`o<hex>`) is new on every call; `epoch` is the one it was taken
  under.
- Marks are the visible interactive elements — links, buttons, inputs, selects, textareas,
  `[role=button|link|tab|menuitem|checkbox]`, `[onclick]` — of every frame, cross-origin iframes
  included, numbered top to bottom then left to right, at most 150.
- Each candidate is hit-tested at `point`, a screen pixel at the centre of its visible part (of its
  first line that hits it, for a link that wraps), the way `/browser/element {x, y}` reads it. The mark
  is what that read finds there: `role`, `name` (its first 80 characters) and `box` (its `screen_box`).
  That can be a child of the control: a `<span>` inside a `<button>` is `generic`, an icon is often
  `generic` with no name. A candidate covered by something else, or in an iframe covered in its parent,
  gets no mark; a frame that can't be read within 5 s is left out.
- To press a mark, click its `point` with `expect.box` set to its `box`.
- A plain screenshot with `marks: []` when no browser is attached, another program's window (a
  terminal, a desktop app or its dialog) is in front of Chromium, or the page can't be read within 15 s.
  Chromium's own windows (a `window.open` popup, a file chooser) count as Chromium: marks and pixel
  reads then describe the foreground tab underneath, not the popup on top.

## Browser (DOM)

All three take `{lease, epoch}` and act on the foreground tab.

**`POST /browser/snapshot`** `{max_chars?: 40000}` → `{url, title, snapshot, truncated, total, tabs:
[{index, url, title, active}]}`. `snapshot` is Playwright's `aria_snapshot(mode="ai")` with `[ref=eN]`
markers (iframe content gets `fNeM` refs). **Password-field values are removed** before the text leaves
the computer; other textbox values stay. `total` is parsed as below. `409 no_browser` when no Chromium is
attached.

**`POST /browser/act`** `{action_id, kind, ref?, text?, key?, value?, url?, index?, dx?, dy?, expect?}`
→ `{action_id, status: "done", result: {url, title}}`, journaled exactly like `/actions`. Kinds:
`click ref`, `fill ref text`, `type [ref] text`, `press [ref] key`, `select ref value|[values]`,
`hover ref`, `scroll [ref | dx dy]`, `navigate url`, `back`, `forward`, `reload`, `new_tab [url]`,
`switch_tab index`, `close_tab [index]`. Acting uses `aria-ref=` locators; a stale ref fails
(`500 action_failed`) rather than hitting something else.

**`POST /browser/element`** `{ref}` | `{x, y}` (screen pixel; walks shadow roots and iframes,
cross-origin ones included) | `{focused: true}` →

```json
{"found": true, "ref": "e10", "tag": "button", "role": "button", "name": "Place order", "type": "submit",
 "href": null, "is_submit": true,
 "form": {"action": "https://shop.example/order", "method": "post", "role": null,
          "text": "qty password subtotal $40.00 total $45.00 place order",
          "fields": [{"name": "qty", "type": "text", "autocomplete": null, "visible": true},
                     {"name": "pw", "type": "password", "autocomplete": "current-password", "visible": true}]},
 "frame_url": "https://shop.example/checkout", "page": {"host": "shop.example", "path": "/checkout", "title": "Checkout"},
 "context_kind": "form", "context_fp": "<sha256>", "total": {"amount": "45.00", "currency": "USD", "text": "Total $45.00"},
 "box": {"x": 300, "y": 200, "w": 200, "h": 60}, "screen_box": {"x": 300, "y": 287, "w": 200, "h": 60}}
```

`{"found": false, "page": {…}}` when nothing is there, and for any pixel while another program's
window (a terminal, a desktop app or its dialog) is in front of Chromium. `box` is in the element's frame viewport;
`screen_box` is in screen pixels (what `/actions` coordinates use). `form` is `null` outside a form;
inside one it also carries the form's `role` attribute, its own visible `text` (innerText, normalised,
lowercased, ≤ 1000 chars: headings, legends and button labels, never input values) and `fields`, the
shape of every non-button control (`name`, `type` — `password`, `hidden`, `select`, `textarea`, … —
`autocomplete`, `visible`), which is what Chatty's login/search exemptions count. No field value appears
in any of these.

- **Context fingerprint**: for an element inside a form, sha256 of the sorted `[name, normalised value]`
  pairs of the form's visible fields (hidden, password, file and button inputs excluded; checkbox/radio
  as on/off; contenteditables inside the form included). For a composer outside a form, the nearest
  ancestor holding an editor: its recipient-like chips (`[email]`, `[data-hovercard-id]`, `role=option|
  listitem`, chip/recipient/token classes) and its editors' text. `null` when neither applies.
- **Order total**: the single snapshot line containing "total" but not "subtotal" with exactly one money
  amount (`$`, `€`, `£`, `¥` or an ISO code; `1,234.56` style). `{amount, currency, text}` when exactly
  one such line exists, `"ambiguous"` when lines mention a total but none or several qualify, `null` when
  no line mentions a total.

## Shell and files

**`POST /shell`** `{lease, epoch, command, timeout?: 120 (≤ 600), cwd?}` → `{exit_code, stdout, stderr,
truncated, timed_out, killed}`. Runs `bash -lc` as the `computer` user (passwordless sudo) in its own
process group; default cwd `/workspace/<agent>`; output capped at 64 KB per stream. The response comes
back when the command exits: a server it leaves running in the background (`cmd &`) keeps running and
doesn't hold the response up, even if it kept stdout open. On `timeout` the whole process group is
killed. `killed` is true when the group was killed because the lease expired and another activation
arrived. Subject to `human_in_control`.

Files need no lease (the agent fetches results after a task). `path` is relative to
`/workspace/<agent>` or absolute under `/workspace/…`; the real path, symlinks followed, must stay inside
`/workspace/<agent>` or `/workspace/shared` (`403 path_forbidden`). Transfers over 25 MB → `413 too_large`.

| Route | Result |
|---|---|
| `GET /files?agent=&path=.` | `{path, entries: [{name, type: "file"\|"dir", size, mtime}]}` (`404 not_a_directory`) |
| `GET /files/content?agent=&path=` | raw bytes, `application/octet-stream`, `X-File-Name`, `X-File-Path` (`404 not_found`) |
| `PUT /files/content?agent=&path=` | body = raw bytes → `{path, size}`; parent directories are created |

## Browser profiles (sites with stored data)

| Route | Result |
|---|---|
| `GET /profiles/{agent}/sites` | `{agent, sites: [{domain, cookies}], live}` — from the running browser over CDP when that agent is on screen (`live: true`, immediate), otherwise from the profile's Cookies database (which Chromium flushes lazily, so a just-stopped browser's list can lag by ~30 s) |
| `DELETE /profiles/{agent}/sites/{domain}` | `{cleared: true, live: bool}` — cookies for the domain and its subdomains plus `Storage.clearDataForOrigin` (all storage) over CDP; `live` says whether that agent's Chromium was on the screen, otherwise the stored profile is opened headless on a side port for the clear (a few seconds) |
| `DELETE /profiles/{agent}` | `{reset: true}` — removes the whole profile; `409 busy` / `409 human_in_control` while that agent is on the screen |

Clearing removes cookies for the host and its subdomains and all storage (localStorage, IndexedDB,
cache, service workers) for the host's standard-port origins (`https://host`, `http://host`) — the same
whether the browser is running or stopped. It does not sign the account out on the site's servers, and
storage held under a non-standard port is out of scope (real sites use 443/80).

## Takeover (one protocol for the viewer and the helper)

| Route | Body | 200 | Errors |
|---|---|---|---|
| `POST /control/start` | `{agent, task_id?}` | `{control_session_id, expires_in: 900, epoch}` | `409 control_active`, `409 lease_mismatch` (the live lease belongs to another agent, or to another task when `task_id` is given), `409 busy` (an action was still running after 30 s), `500 desktop_failed` |
| `POST /control/end` | `{control_session_id}` | `{ended: true, epoch}` | `404 no_such_session` |
| `GET /control/status` | — | `{human_in_control, control: {control_session_id, agent, task_id, connected, started_at, expires_in} \| null, control_ended: {at, reason, agent, task_id, epoch} \| null, epoch, lease: {agent, task_id, expires_in} \| null}` (`/health` shows the same `control` without the id) | — |

- Starting control waits for any running action to finish, brings up the agent's browser if nothing
  holds the screen for it, starts the input-accepting VNC server on `:5901`, and from then on every agent
  desktop call (actions, browser, shell) gets `409 human_in_control`. Renew, release and control status
  are exempt. No new lease is granted during control.
- One control session at a time. It ends on `POST /control/end`, 60 s after its WebSocket dropped
  without a reconnect (the same 60 s runs from `start` if no viewer ever attaches), or after 15
  minutes — each stops `:5901`, bumps the epoch, and records
  `control_ended` (`reason`: `done`, `disconnected`, `timeout`, `shutdown`), visible in `/health`,
  `/control/status` and renew responses.
- `GET /health`.`human_in_control` is true for the whole session, including the reconnect grace.
- What a takeover does not do: stop processes already running on the computer. Command MCP servers
  and background shell jobs keep running as the same `computer` user and could, in principle, read
  the screen or the DOM while a person types. That is the one-user, no-wall trust model the design
  accepts; the API blocks the helper's own calls, not a determined process on the box.

**`WS /vnc?mode=view|control[&control_session_id=…]`** relays raw RFB bytes to `127.0.0.1:5900`
(view-only, exists while the desktop runs) or `:5901` (control). Offer the `binary` subprotocol (noVNC
does). Refused before the upgrade when the bearer is wrong, `mode=control` carries an id that isn't the
current session, or `mode=view` finds no running desktop. A control reconnect within the grace period
must present the same `control_session_id`; a second control socket replaces the first.

## Command MCP servers

One `mcp-proxy` process per server, environment kept in memory and passed only at start.

| Route | Result |
|---|---|
| `PUT /mcp/servers/{name}` `{command, env?}` | starts (or restarts) `mcp-proxy --named-server <name> '<command>'`; waits for it (`502 mcp_start_failed` with a log tail otherwise) → `{name, command, running, started_at, url: "/mcp/<name>/mcp"}`. `name` matches `^[a-z0-9_-]{1,64}$` |
| `GET /mcp/servers`, `GET /mcp/servers/{name}` | the same objects (never `env`); `404 mcp_server_not_running` |
| `DELETE /mcp/servers/{name}` | `{stopped: bool}` |
| `ANY /mcp/{name}/{path}` | streamed reverse proxy to the server; the streamable-HTTP endpoint is **`/mcp/{name}/mcp`** (SSE at `/mcp/{name}/sse`). `404 mcp_server_not_running` after a restart — start it again |

What the API can't promise: a command server can print or save its own environment, and any process on
the computer (the helper's sudo shell included) can read another's.

## Health, settings, idle

`GET /health` (no auth) → `{api_version, boot_id, epoch, chromium_version, desktop_running, active_agent,
lease, human_in_control, control, control_ended, idle_minutes, disk: {total, used, free}, mcp_servers}`.

`PUT /settings {idle_minutes}` → `{idle_minutes}`; persisted in `/data/settings.json`. `0` keeps the
desktop always on; otherwise a 60-second loop stops Chromium, VNC, openbox and Xvfb after that many
minutes with no authenticated request, no open `/vnc` viewer, no live lease and no control session. The
container stays up and the next activation brings everything back.

## Smoke test

`smoke_test.py` (stdlib only) runs against a container started with a persistent `/data` volume and
needs the `docker` CLI for the restart and cross-container checks:

```bash
docker network create computer-net && docker volume create computer-data
docker run -d --name chatty-computer-test --network computer-net --shm-size=1g \
  -e COMPUTER_SECRET=smoke-test-secret-0123456789abcdef0123456789abcdef -e HOST=0.0.0.0 \
  -p 127.0.0.1:8765:8080 -v computer-data:/data chatty-computer:test
COMPUTER_URL=http://127.0.0.1:8765 COMPUTER_SECRET=smoke-test-secret-0123456789abcdef0123456789abcdef \
  CONTAINER=chatty-computer-test IMAGE=chatty-computer:test python3 computer/smoke_test.py
```

It takes about 11 minutes: the lease, renew-keepalive, long-takeover and grace checks wait real time.
