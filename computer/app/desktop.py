"""The desktop: Xvfb, openbox, x11vnc and Chromium as child processes, xdotool actions, screenshots.

Processes start on demand and stop when idle. The xdotool mapping is ported from Anthropic's
computer-use-demo for the 17 members of `computer_toolset_20260801`.
"""
import asyncio
import io
import os
import signal
import subprocess
import time

import httpx
import mss
import mss.tools
from PIL import Image

DISPLAY = ":1"
WIDTH, HEIGHT = 1280, 800
CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
VIEW_PORT, CONTROL_PORT = 5900, 5901
PROFILES_DIR = "/data/profiles"
CHROMIUM_CACHE_DIR = "/tmp/chromium-cache"
CHROMIUM_CACHE_BYTES = 50 * 1024 * 1024

TOOLSET_MEMBERS = frozenset([
    "key", "hold_key", "type", "cursor_position", "mouse_move", "left_mouse_down", "left_mouse_up",
    "left_click", "left_click_drag", "right_click", "middle_click", "double_click", "triple_click",
    "scroll", "wait", "screenshot", "zoom",
])
CLICK_BUTTONS = {
    "left_click": ["1"],
    "right_click": ["3"],
    "middle_click": ["2"],
    "double_click": ["--repeat", "2", "--delay", "10", "1"],
    "triple_click": ["--repeat", "3", "--delay", "10", "1"],
}
SCROLL_BUTTONS = {"up": "4", "down": "5", "left": "6", "right": "7"}
TYPING_DELAY_MS = 12
TYPING_GROUP_SIZE = 50
KEY_REPEAT_MAX = 100
MAX_DURATION_S = 100


class ActionError(Exception):
    """Bad action input (-> 400)."""


class Desktop:
    def __init__(self):
        self.procs: dict[str, subprocess.Popen] = {}
        self.active_agent: str | None = None
        self.chromium_version: str | None = None
        self._env = {**os.environ, "DISPLAY": DISPLAY}

    # ----- processes -----------------------------------------------------------------------

    def _alive(self, name: str) -> bool:
        p = self.procs.get(name)
        return p is not None and p.poll() is None

    @property
    def running(self) -> bool:
        return self._alive("xvfb")

    def _spawn(self, name: str, cmd: list[str], **kw):
        self.procs[name] = subprocess.Popen(
            cmd, env=self._env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, **kw,
        )

    async def _stop(self, name: str, grace: float = 5.0):
        p = self.procs.pop(name, None)
        if p is None or p.poll() is not None:
            return
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + grace
        while p.poll() is None and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()

    async def ensure_display(self):
        """Xvfb + openbox + the view-only VNC server, started once and kept until idle."""
        if not self._alive("xvfb"):
            # a killed Xvfb (container restart) leaves its lock and socket behind, and the new one
            # refuses to start while they exist
            for stale in (f"/tmp/.X{DISPLAY[1:]}-lock", f"/tmp/.X11-unix/X{DISPLAY[1:]}"):
                try:
                    os.unlink(stale)
                except FileNotFoundError:
                    pass
            self._spawn("xvfb", ["Xvfb", DISPLAY, "-screen", "0", f"{WIDTH}x{HEIGHT}x24", "-ac",
                                 "-nolisten", "tcp", "-dpi", "96"])
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                r = await asyncio.create_subprocess_exec("xdpyinfo", "-display", DISPLAY, env=self._env,
                                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if await r.wait() == 0:
                    break
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Xvfb did not start")
        if not self._alive("openbox"):
            self._spawn("openbox", ["openbox"])
        if not self._alive("vnc_view"):
            self._spawn("vnc_view", self._x11vnc_cmd(VIEW_PORT, viewonly=True))
            await self._wait_port(VIEW_PORT)

    @staticmethod
    def _x11vnc_cmd(port: int, viewonly: bool) -> list[str]:
        cmd = ["x11vnc", "-display", DISPLAY, "-rfbport", str(port), "-localhost", "-shared", "-forever",
               "-nopw", "-quiet", "-wait", "50"]
        if viewonly:
            cmd.append("-viewonly")
        return cmd

    async def _wait_port(self, port: int, timeout: float = 5.0):
        """x11vnc takes a moment to listen; a viewer connects right after /control/start."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                return
            except OSError:
                await asyncio.sleep(0.05)
        raise RuntimeError(f"VNC server on :{port} did not start")

    async def start_control_vnc(self):
        if not self._alive("vnc_control"):
            self._spawn("vnc_control", self._x11vnc_cmd(CONTROL_PORT, viewonly=False))
            await self._wait_port(CONTROL_PORT)

    async def stop_control_vnc(self):
        await self._stop("vnc_control", grace=2)

    async def start_chromium(self, agent: str):
        """Switch the screen's Chromium to `agent`'s profile (a no-op if it's already up)."""
        if self.active_agent == agent and self._alive("chromium"):
            return
        await self.stop_chromium()
        os.makedirs(os.path.join(PROFILES_DIR, agent), exist_ok=True)
        self._spawn("chromium", [
            "chromium",
            f"--user-data-dir={os.path.join(PROFILES_DIR, agent)}",
            f"--remote-debugging-port={CDP_PORT}", "--remote-debugging-address=127.0.0.1",
            "--no-sandbox", "--disable-dev-shm-usage",
            "--window-position=0,0", f"--window-size={WIDTH},{HEIGHT}",
            "--no-first-run", "--no-default-browser-check", "--password-store=basic",
            "--hide-crash-restore-bubble", "--disable-session-crashed-bubble",
            "--test-type",  # hides the "--no-sandbox is unsupported" infobar that would shift the page

            f"--disk-cache-dir={CHROMIUM_CACHE_DIR}", f"--disk-cache-size={CHROMIUM_CACHE_BYTES}",
            "about:blank",
        ])
        async with httpx.AsyncClient(timeout=1.0) as client:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if not self._alive("chromium"):
                    raise RuntimeError("Chromium exited during startup")
                try:
                    r = await client.get(f"{CDP_URL}/json/version")
                    self.chromium_version = r.json().get("Browser")
                    break
                except (httpx.HTTPError, ValueError):
                    await asyncio.sleep(0.2)
            else:
                await self.stop_chromium()
                raise RuntimeError("Chromium did not open its debugging port")
        self.active_agent = agent

    async def stop_chromium(self):
        await self._stop("chromium")
        self.active_agent = None

    async def stop_all(self):
        for name in ("chromium", "vnc_control", "vnc_view", "openbox", "xvfb"):
            await self._stop(name, grace=3)
        self.active_agent = None

    # ----- screenshots ---------------------------------------------------------------------

    def _grab(self):
        with mss.MSS(display=DISPLAY) as sct:
            return sct.grab(sct.monitors[1])

    async def screenshot_png(self) -> bytes:
        img = await asyncio.to_thread(self._grab)
        return mss.tools.to_png(img.rgb, img.size)

    async def zoom_png(self, region) -> bytes:
        """Crop `region` (x0, y0, x1, y1 in screen pixels) and scale it to fit the screen frame."""
        x0, y0, x1, y1 = region
        img = await asyncio.to_thread(self._grab)
        pil = Image.frombytes("RGB", img.size, img.rgb).crop((x0, y0, x1, y1))
        scale = min(WIDTH / pil.width, HEIGHT / pil.height)
        pil = pil.resize((max(1, round(pil.width * scale)), max(1, round(pil.height * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()

    # ----- xdotool -------------------------------------------------------------------------

    async def _xdotool(self, *args: str) -> str:
        p = await asyncio.create_subprocess_exec("xdotool", *args, env=self._env,
                                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = await asyncio.wait_for(p.communicate(), timeout=MAX_DURATION_S + 30)
        if p.returncode != 0:
            raise RuntimeError(f"xdotool failed: {err.decode(errors='replace').strip()[:300]}")
        return out.decode(errors="replace")

    async def cursor_position(self) -> tuple[int, int]:
        out = await self._xdotool("getmouselocation", "--shell")
        vals = dict(line.split("=", 1) for line in out.split() if "=" in line)
        return int(vals["X"]), int(vals["Y"])

    @staticmethod
    def _coord(value, what="coordinate") -> tuple[int, int]:
        if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(isinstance(v, int) and v >= 0 for v in value):
            raise ActionError(f"{what} must be [x, y] with non-negative integers")
        x, y = value
        if x >= WIDTH or y >= HEIGHT:
            raise ActionError(f"{what} {value} is outside the {WIDTH}x{HEIGHT} screen")
        return x, y

    @staticmethod
    def _duration(value) -> float:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= MAX_DURATION_S:
            raise ActionError(f"duration must be a number between 0 and {MAX_DURATION_S}")
        return float(value)

    @staticmethod
    def _text(inp) -> str:
        text = inp.get("text")
        if not isinstance(text, str) or not text:
            raise ActionError("text is required")
        return text

    def action_target(self, name: str, inp: dict) -> str | None:
        """Where the action lands, for the pre-action element check: "point", "cursor",
        "focused" or None (not applicable)."""
        if name in CLICK_BUTTONS or name == "left_click_drag":
            key = "start_coordinate" if name == "left_click_drag" else "coordinate"
            return "point" if inp.get(key) is not None else "cursor"
        if name == "left_mouse_down":
            return "point" if inp.get("coordinate") is not None else "cursor"
        if name in ("key", "hold_key", "type"):
            return "focused"
        return None

    async def run_action(self, name: str, inp: dict) -> dict:
        """Execute one toolset member. Returns a JSON-able result."""
        if name not in TOOLSET_MEMBERS:
            raise ActionError(f"unknown action {name!r}")
        if name == "screenshot":
            return {"image": await self.screenshot_png(), "width": WIDTH, "height": HEIGHT}
        if name == "zoom":
            region = inp.get("region")
            if (not isinstance(region, (list, tuple)) or len(region) != 4
                    or not all(isinstance(c, int) and c >= 0 for c in region)
                    or region[2] <= region[0] or region[3] <= region[1]
                    or region[2] > WIDTH or region[3] > HEIGHT):
                raise ActionError("region must be [x0, y0, x1, y1] inside the screen with x0 < x1 and y0 < y1")
            return {"image": await self.zoom_png(region)}
        if name == "cursor_position":
            x, y = await self.cursor_position()
            return {"x": x, "y": y}
        if name == "wait":
            await asyncio.sleep(self._duration(inp.get("duration")))
            return {"ok": True}
        if name == "mouse_move":
            x, y = self._coord(inp.get("coordinate"))
            await self._xdotool("mousemove", "--sync", str(x), str(y))
            return {"ok": True}
        if name == "key":
            text = self._text(inp)
            repeat = inp.get("repeat", 1)
            if not isinstance(repeat, int) or not 1 <= repeat <= KEY_REPEAT_MAX:
                raise ActionError(f"repeat must be an integer between 1 and {KEY_REPEAT_MAX}")
            await self._xdotool("key", "--", *([text] * repeat))
            return {"ok": True}
        if name == "hold_key":
            text = self._text(inp)
            duration = self._duration(inp.get("duration"))
            await self._xdotool("keydown", "--", text, "sleep", str(duration), "keyup", "--", text)
            return {"ok": True}
        if name == "type":
            text = self._text(inp)
            for i in range(0, len(text), TYPING_GROUP_SIZE):
                await self._xdotool("type", "--delay", str(TYPING_DELAY_MS), "--", text[i:i + TYPING_GROUP_SIZE])
            return {"ok": True}
        if name in ("left_mouse_down", "left_mouse_up"):
            args = []
            if inp.get("coordinate") is not None:
                x, y = self._coord(inp["coordinate"])
                args += ["mousemove", "--sync", str(x), str(y)]
            args += ["mousedown" if name == "left_mouse_down" else "mouseup", "1"]
            await self._xdotool(*args)
            return {"ok": True}
        if name == "scroll":
            direction = inp.get("scroll_direction")
            amount = inp.get("scroll_amount")
            if direction not in SCROLL_BUTTONS:
                raise ActionError("scroll_direction must be up, down, left or right")
            if not isinstance(amount, int) or not 0 <= amount <= 100:
                raise ActionError("scroll_amount must be an integer between 0 and 100")
            args = []
            if inp.get("coordinate") is not None:
                x, y = self._coord(inp["coordinate"])
                args += ["mousemove", "--sync", str(x), str(y)]
            modifier = inp.get("text")
            if modifier:
                args += ["keydown", "--", modifier]
            if amount:
                args += ["click", "--repeat", str(amount), SCROLL_BUTTONS[direction]]
            if modifier:
                args += ["keyup", "--", modifier]
            if args:
                await self._xdotool(*args)
            return {"ok": True}
        if name == "left_click_drag":
            sx, sy = self._coord(inp.get("start_coordinate"), "start_coordinate")
            ex, ey = self._coord(inp.get("coordinate"))
            modifier = inp.get("text")
            args = (["keydown", "--", modifier] if modifier else []) + [
                "mousemove", "--sync", str(sx), str(sy), "mousedown", "1",
                "mousemove", "--sync", str(ex), str(ey), "mouseup", "1",
            ] + (["keyup", "--", modifier] if modifier else [])
            await self._xdotool(*args)
            return {"ok": True}
        # the click family: optional coordinate, optional held modifier chord in `text`
        args = []
        if inp.get("coordinate") is not None:
            x, y = self._coord(inp["coordinate"])
            args += ["mousemove", "--sync", str(x), str(y)]
        modifier = inp.get("text")
        if modifier:
            args += ["keydown", "--", modifier]
        args += ["click", *CLICK_BUTTONS[name]]
        if modifier:
            args += ["keyup", "--", modifier]
        await self._xdotool(*args)
        return {"ok": True}
