#!/usr/bin/env python3
"""Smoke test for the computer image. Standard library only.

Runs against a container started with a persistent /data volume (see README.md) and uses the docker
CLI for the restart and cross-container checks. Takes about 11 minutes: the lease, keepalive,
long-takeover and grace checks wait real time.

Env: COMPUTER_URL, COMPUTER_SECRET, CONTAINER (docker name), IMAGE (for the other-container probe).
"""
import base64
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ.get("COMPUTER_URL", "http://127.0.0.1:8765").rstrip("/")
SECRET = os.environ["COMPUTER_SECRET"]
CONTAINER = os.environ.get("CONTAINER", "chatty-computer-test")
IMAGE = os.environ.get("IMAGE", "chatty-computer:test")
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
failures: list[str] = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        failures.append(what)
    return cond


def ulid(ms=None) -> str:
    t = int((time.time() if ms is None else ms / 1000) * 1000)
    head = ""
    for _ in range(10):
        head, t = ALPHABET[t % 32] + head, t // 32
    r = int.from_bytes(os.urandom(10), "big")
    tail = ""
    for _ in range(16):
        tail, r = ALPHABET[r % 32] + tail, r // 32
    return head + tail


def api(method, path, body=None, *, auth=True, raw=False, data=None, timeout=180):
    payload = data if data is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(URL + path, data=payload, method=method)
    if auth:
        req.add_header("Authorization", f"Bearer {SECRET}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = r.read()
            return r.status, (content if raw else json.loads(content))
    except urllib.error.HTTPError as e:
        content = e.read()
        try:
            return e.code, json.loads(content)
        except ValueError:
            return e.code, content


def docker(*args, check_rc=False):
    r = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check_rc and r.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)}: {r.stderr}")
    return r


def port_open_in_container(port: int) -> bool:
    return docker("exec", CONTAINER, "bash", "-c", f"exec 3<>/dev/tcp/127.0.0.1/{port}").returncode == 0


def wait_health(changed_from=None, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            st, h = api("GET", "/health", auth=False, timeout=5)
            if st == 200 and h["boot_id"] != changed_from:
                return h
        except (urllib.error.URLError, ConnectionError, socket.timeout, OSError):
            pass
        time.sleep(1)
    raise RuntimeError("computer did not come back")


# ----- a tiny WebSocket client (handshake + unfragmented frames) --------------------------------

def ws_connect(path, headers=None):
    u = urllib.parse.urlsplit(URL)
    sock = socket.create_connection((u.hostname, u.port or 80), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    lines = [f"GET {path} HTTP/1.1", f"Host: {u.hostname}:{u.port or 80}", "Upgrade: websocket", "Connection: Upgrade",
             f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13", "Sec-WebSocket-Protocol: binary"]
    for k, v in (headers or {}).items():
        lines.append(f"{k}: {v}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            break
        resp += chunk
    status = int(resp.split(b" ", 2)[1]) if resp.startswith(b"HTTP/1.1 ") else 0
    if status != 101:
        sock.close()
        return None, status
    return sock, 101


def ws_recv(sock, timeout=10) -> bytes:
    sock.settimeout(timeout)
    head = sock.recv(2)
    if len(head) < 2:
        return b""
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", sock.recv(8))[0]
    data = b""
    while len(data) < length:
        more = sock.recv(length - len(data))
        if not more:
            break
        data += more
    return data


def ws_send(sock, data: bytes):
    mask = os.urandom(4)
    header = bytes([0x82]) + (bytes([0x80 | len(data)]) if len(data) < 126 else bytes([0x80 | 126]) + struct.pack(">H", len(data)))
    sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def rfb_handshake(sock):
    """Complete the RFB 3.8 handshake through the bridge (x11vnc drops clients that never do) and
    return (banner, (width, height)) from ServerInit."""
    buf = bytearray()

    def take(n):
        nonlocal buf
        while len(buf) < n:
            data = ws_recv(sock)
            if not data:
                raise RuntimeError("stream closed during the RFB handshake")
            buf += data
        out, buf = bytes(buf[:n]), buf[n:]
        return out

    banner = take(12)
    ws_send(sock, b"RFB 003.008\n")
    take(take(1)[0])  # security types; -nopw offers None
    ws_send(sock, b"\x01")
    take(4)  # SecurityResult
    ws_send(sock, b"\x01")  # ClientInit: shared
    size = struct.unpack(">HH", take(4))
    take(16)
    take(struct.unpack(">I", take(4))[0])
    return banner, size


# ----- the fixture page ---------------------------------------------------------------------------

PAGE = """<title>Demo shop</title><h1>Demo shop</h1>
<form id="f" action="/order" method="post" onsubmit="event.preventDefault();window.n=(window.n||0)+1;document.getElementById('c').textContent='Orders placed: '+window.n;return false;">
<label>Qty <input name="qty" value="2"></label>
<label>Password <input type="password" name="pw" value="s3cret-value-xyz"></label>
<div>Subtotal $40.00</div><div>Total $45.00</div>
<button type="submit" id="b">Place order</button></form>
<div id="c">Orders placed: 0</div>"""
DATA_URL = "data:text/html," + urllib.parse.quote(PAGE)


def activate(agent="tom", task="t1"):
    st, r = api("POST", "/desktop/activate", {"agent": agent, "task_id": task})
    assert st == 200, (st, r)
    return r["lease"], r["epoch"]


def orders_placed(lease, epoch) -> int:
    st, snap = api("POST", "/browser/snapshot", {"lease": lease, "epoch": epoch})
    assert st == 200, (st, snap)
    m = re.search(r"Orders placed: (\d+)", snap["snapshot"])
    return int(m.group(1)) if m else -1


def keep_renewing(lease, stop: threading.Event, seen: list):
    while not stop.wait(30):
        st, r = api("POST", "/desktop/lease/renew", {"lease": lease})
        seen.append((st, r))
        if st != 200:
            return


def main():
    t_start = time.time()
    h = wait_health()
    check(h["api_version"] == "1.0", "health reports api_version 1.0")

    # --- auth ---
    st, _ = api("GET", "/control/status", auth=False)
    check(st == 401, "request without the bearer gets 401")

    # --- lease + fixture ---
    lease, epoch = activate()
    st, r = api("POST", "/desktop/activate", {"agent": "ann", "task_id": "t2"})
    check(st == 409 and r["error"] == "busy", "a second lease gets 409 busy")
    st, r = api("POST", "/browser/act", {"action_id": ulid(), "lease": lease, "epoch": epoch, "kind": "navigate", "url": DATA_URL})
    check(st == 200, f"navigate to the fixture page ({st})")
    st, snap = api("POST", "/browser/snapshot", {"lease": lease, "epoch": epoch})
    check(st == 200 and 'button "Place order"' in snap["snapshot"], "Place order button appears in the snapshot")
    check("s3cret-value-xyz" not in snap["snapshot"], "snapshot of a filled password field has no password value")
    tot = snap.get("total")
    check(isinstance(tot, dict) and tot["amount"] == "45.00" and tot["currency"] == "USD",
          f"order total parsed as 45.00 USD, not the subtotal ({tot})")
    ref = re.search(r'button "Place order" \[ref=([a-z0-9]+)\]', snap["snapshot"]).group(1)

    # --- screenshot ---
    st, shot = api("POST", "/actions", {"action_id": ulid(), "lease": lease, "epoch": epoch, "name": "screenshot", "input": {}})
    png = base64.b64decode(shot["result"]["image"]) if st == 200 else b""
    check(png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (1280, 800), "screenshot is a 1280x800 PNG")

    # --- element by ref / pixel ---
    st, el = api("POST", "/browser/element", {"lease": lease, "epoch": epoch, "ref": ref})
    check(st == 200 and el["found"] and el["name"] == "Place order" and el["is_submit"], "element by ref describes the button")
    cx = el["screen_box"]["x"] + el["screen_box"]["w"] // 2
    cy = el["screen_box"]["y"] + el["screen_box"]["h"] // 2
    st, at = api("POST", "/browser/element", {"lease": lease, "epoch": epoch, "x": cx, "y": cy})
    check(st == 200 and at["found"] and at["name"] == "Place order" and at["tag"] == "button",
          "/browser/element at the button's pixel returns that button")
    expect = {"action": "left_click", "host": el["page"]["host"], "path": el["page"]["path"], "frame_url": el["frame_url"],
              "role": el["role"], "name": el["name"], "form_action": el["form"]["action"], "context_fp": el["context_fp"],
              "total": {"amount": "45.00", "currency": "USD"}}
    click = {"name": "left_click", "input": {"coordinate": [cx, cy]}}

    # --- expect refusals ---
    for field, bad in (("name", "Buy now"), ("context_fp", "0" * 64), ("total", {"amount": "40.00", "currency": "USD"})):
        st, r = api("POST", "/actions", {"action_id": ulid(), "lease": lease, "epoch": epoch, **click, "expect": {**expect, field: bad}})
        check(st == 409 and r.get("error") == "element_changed" and field in r.get("mismatches", []),
              f"a click with the wrong expect.{field} returns 409 element_changed")
    check(orders_placed(lease, epoch) == 0, "refused clicks did not click")

    # --- journal: replay, conflict, concurrency ---
    aid = ulid()
    st, r = api("POST", "/actions", {"action_id": aid, "lease": lease, "epoch": epoch, **click, "expect": expect})
    check(st == 200 and r["status"] == "done", "a click with the right expect goes through")
    st2, r2 = api("POST", "/actions", {"action_id": aid, "lease": lease, "epoch": epoch, **click, "expect": expect})
    check(st2 == 200 and r2 == r and orders_placed(lease, epoch) == 1, "a repeated action_id doesn't click twice")
    st3, r3 = api("POST", "/actions", {"action_id": aid, "lease": lease, "epoch": epoch, "name": "left_click",
                                       "input": {"coordinate": [cx + 1, cy]}, "expect": expect})
    check(st3 == 409 and r3.get("error") == "action_conflict", "the same id with a different payload gets 409")
    st4, r4 = api("GET", f"/actions/{aid}")
    check(st4 == 200 and r4["status"] == "done" and r4["http_status"] == 200, "GET /actions/{id} reports the outcome")
    bid, results = ulid(), []

    def one():
        results.append(api("POST", "/actions", {"action_id": bid, "lease": lease, "epoch": epoch, **click, "expect": expect}))

    threads = [threading.Thread(target=one) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check(all(s == 200 for s, _ in results) and orders_placed(lease, epoch) == 2,
          f"six concurrent requests with one id produce a single click ({[s for s, _ in results]})")

    # --- shell + files ---
    st, r = api("POST", "/shell", {"lease": lease, "epoch": epoch, "command": "echo hi; echo oops >&2; exit 3"})
    check(st == 200 and r["stdout"].strip() == "hi" and r["stderr"].strip() == "oops" and r["exit_code"] == 3, "shell round-trip")
    st, r = api("PUT", "/files/content?agent=tom&path=notes/hello.txt", data=b"hello from the smoke test")
    check(st == 200 and r["size"] == 25, "PUT a file")
    st, r = api("GET", "/files/content?agent=tom&path=notes/hello.txt", raw=True)
    check(st == 200 and r == b"hello from the smoke test", "GET the file back")
    st, r = api("GET", "/files?agent=tom&path=notes")
    check(st == 200 and [e["name"] for e in r["entries"]] == ["hello.txt"], "list the directory")
    st, r = api("PUT", "/files/content?agent=tom&path=/workspace/shared/handoff.txt", data=b"shared")
    check(st == 200, f"the shared workspace is writable on a fresh volume ({st})")
    st, _ = api("GET", "/files/content?agent=tom&path=../../etc/passwd")
    st_abs, _ = api("GET", "/files/content?agent=tom&path=/etc/passwd")
    api("POST", "/shell", {"lease": lease, "epoch": epoch, "command": "ln -sfn /etc /workspace/tom/escape"})
    st_link, _ = api("GET", "/files?agent=tom&path=escape")
    check(st == 403 and st_abs == 403 and st_link == 403, "path escapes (relative, absolute, symlink) are refused")
    st, r = api("GET", "/files/content?agent=tom&path=/workspace/shared/nothing-here")
    check(st == 404, "missing file is 404, not an escape")

    # --- no other container can reach VNC or CDP ---
    ip = docker("inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", CONTAINER, check_rc=True).stdout.strip()
    net = docker("inspect", "-f", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}", CONTAINER, check_rc=True).stdout.strip()

    def reachable(port):
        return docker("run", "--rm", "--network", net, "--entrypoint", "bash", IMAGE, "-c",
                      f"timeout 3 bash -c 'exec 3<>/dev/tcp/{ip}/{port}'").returncode == 0

    check(reachable(8080) and not reachable(5900) and not reachable(9222), "VNC and CDP aren't reachable from another container")

    # --- restart: in-flight action becomes unknown, files survive ---
    cid = ulid()
    def long_wait():
        try:
            api("POST", "/actions", {"action_id": cid, "lease": lease, "epoch": epoch, "name": "wait", "input": {"duration": 40}}, timeout=60)
        except OSError:
            pass  # the restart cuts the connection

    threading.Thread(target=long_wait, daemon=True).start()
    time.sleep(2)
    st, r = api("GET", f"/actions/{cid}")
    check(st == 200 and r["status"] == "executing", "the long action is executing before the restart")
    old_boot = h["boot_id"]
    docker("restart", "-t", "5", CONTAINER, check_rc=True)
    wait_health(changed_from=old_boot)
    st, r = api("GET", f"/actions/{cid}")
    check(st == 200 and r["status"] == "unknown", "after a restart, an executing id reads unknown")
    st, r = api("GET", "/files/content?agent=tom&path=notes/hello.txt", raw=True)
    mounts = docker("inspect", "-f", "{{range .Mounts}}{{.Destination}} {{end}}", CONTAINER, check_rc=True).stdout.split()
    on_volume = docker("exec", CONTAINER, "test", "-f", "/data/workspace/tom/notes/hello.txt").returncode == 0
    check(st == 200 and r == b"hello from the smoke test" and "/data" in mounts and on_volume,
          "files under /workspace survive a container restart and live on the /data volume")
    st, r = api("POST", "/browser/snapshot", {"lease": lease, "epoch": epoch})
    check(st == 409 and r["error"] == "lease_lost", "the old lease is gone after a restart")

    # --- expiry: calls refused, no new lease while the old lease's shell runs ---
    lease, epoch = activate()
    shell_result = []
    threading.Thread(target=lambda: shell_result.append(api("POST", "/shell", {"lease": lease, "epoch": epoch, "command": "sleep 170", "timeout": 300}, timeout=400)),
                     daemon=True).start()
    print("... waiting 125 s for the lease to expire", flush=True)
    time.sleep(125)
    st, r = api("POST", "/browser/snapshot", {"lease": lease, "epoch": epoch})
    check(st == 409 and r["error"] == "lease_lost", "an expired lease's calls are refused")
    st, r = api("POST", "/desktop/lease/renew", {"lease": lease})
    check(st == 409, "an expired lease can't be renewed")
    st, r = api("POST", "/desktop/activate", {"agent": "ann", "task_id": "t2"})
    check(st == 409 and r.get("reason") == "operation_running", "no new lease while the old lease's shell command is still running")
    deadline = time.time() + 15
    while not shell_result and time.time() < deadline:
        time.sleep(0.5)
    check(bool(shell_result) and shell_result[0][1].get("killed") is True, "the old lease's shell was killed")
    lease, epoch = activate("ann", "t2")
    check(True, "a new lease is granted once the old operation finished")

    # --- keepalive: a lease renewed every 30 s survives 200 s of silence ---
    stop, seen = threading.Event(), []
    renewer = threading.Thread(target=keep_renewing, args=(lease, stop, seen), daemon=True)
    renewer.start()
    print("... renewing every 30 s for 200 s", flush=True)
    time.sleep(200)
    st, r = api("POST", "/browser/snapshot", {"lease": lease, "epoch": epoch})
    check(st == 200 and all(s == 200 for s, _ in seen), f"a lease kept alive by renew survives a 200-second idle ({len(seen)} renews)")

    # --- takeover ---
    check(not port_open_in_container(5901), ":5901 is closed before any control session")
    st, r = api("POST", "/control/start", {"agent": "tom"})
    check(st == 409 and r["error"] == "lease_mismatch", "control start is refused for an agent that doesn't hold the lease")
    st, c = api("POST", "/control/start", {"agent": "ann", "task_id": "t2"})
    check(st == 200 and "control_session_id" in c, "control start for the lease holder's agent")
    csid = c["control_session_id"]
    check(port_open_in_container(5901), ":5901 answers while a control session exists")
    check(not reachable(5901), ":5901 isn't reachable from another container either")
    sock, status = ws_connect("/vnc?mode=control&control_session_id=wrong", {"Authorization": f"Bearer {SECRET}"})
    check(sock is None and status != 101, f"a control connection with a wrong control_session_id is refused ({status})")
    sock, status = ws_connect("/vnc?mode=control&control_session_id=" + csid, {"Authorization": f"Bearer {SECRET}"})
    banner, size = rfb_handshake(sock) if sock else (b"", None)
    check(sock is not None and banner.startswith(b"RFB ") and size == (1280, 800),
          f"the control stream completes an RFB handshake for a 1280x800 screen ({banner[:12]!r}, {size})")
    st, r = api("POST", "/browser/snapshot", {"lease": lease, "epoch": epoch})
    check(st == 409 and r["error"] == "human_in_control", "agent desktop calls get 409 human_in_control during takeover")
    st, r = api("POST", "/desktop/lease/renew", {"lease": lease})
    check(st == 200 and r["human_in_control"] is True, "renew is exempt during takeover")
    print("... holding control for 130 s while renewing", flush=True)
    time.sleep(130)
    st, r = api("POST", "/desktop/lease/renew", {"lease": lease})
    check(st == 200 and r["human_in_control"] is True, "a takeover longer than 120 s keeps the lease")
    st, e = api("POST", "/control/end", {"control_session_id": csid})
    check(st == 200 and e["epoch"] != epoch, "control end bumps the epoch")
    stop.set()
    st, r = api("POST", "/browser/snapshot", {"lease": lease, "epoch": epoch})
    check(st == 409 and r["error"] == "stale_epoch", "the old epoch is refused after handback")
    st, r = api("POST", "/desktop/lease/renew", {"lease": lease})
    check(st == 200 and r["epoch"] == e["epoch"] and r["control_ended"]["reason"] == "done", "renew reports control ended with the new epoch")
    epoch = r["epoch"]
    st, r = api("POST", "/browser/snapshot", {"lease": lease, "epoch": epoch})
    check(st == 200, "the lease holder continues with the new epoch")
    check(not port_open_in_container(5901), ":5901 stops when control ends")
    try:
        sock.close()
    except OSError:
        pass

    # --- grace period and fencing ---
    st, c = api("POST", "/control/start", {"agent": "ann", "task_id": "t2"})
    csid = c["control_session_id"]
    sock, status = ws_connect("/vnc?mode=control&control_session_id=" + csid, {"Authorization": f"Bearer {SECRET}"})
    rfb_handshake(sock)
    sock.close()  # the phone dropped off
    t_drop = time.time()
    print("... waiting through the 60 s reconnect grace (and 120 s lease expiry)", flush=True)
    time.sleep(30)
    st, s = api("GET", "/control/status")
    check(s["human_in_control"] and port_open_in_container(5901), ":5901 stays up through the 60-second grace")
    sock2, status = ws_connect("/vnc?mode=control&control_session_id=" + csid, {"Authorization": f"Bearer {SECRET}"})
    check(sock2 is not None and rfb_handshake(sock2)[0].startswith(b"RFB "), "a reconnect with the same control_session_id is accepted")
    sock2.close()
    time.sleep(max(0, t_drop + 105 - time.time()))
    st, s = api("GET", "/control/status")
    check(not s["human_in_control"] and s["control_ended"]["reason"] == "disconnected" and not port_open_in_container(5901),
          "control ends and :5901 stops when the grace runs out")
    time.sleep(max(0, t_drop + 130 - time.time()))
    st, r = api("POST", "/desktop/lease/renew", {"lease": lease})
    check(st == 409 and r["error"] == "lease_lost", "a lease that expired during control fences its owner")

    print(f"\n{len(failures)} failure(s) in {time.time() - t_start:.0f} s")
    for f in failures:
        print("  -", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
