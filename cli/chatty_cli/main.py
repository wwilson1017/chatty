"""chatty: chat with your Chatty agents from a terminal."""

import argparse
import asyncio
import sys

import httpx

from . import __version__, commands, config
from .api import Api, ApiError
from .login import cmd_login, cmd_logout
from .render import console, note
from .repl import Session, run, why


async def open_session(api: Api, args, cfg: dict) -> Session | None:
    """Pick the agent (-a, the only one, the remembered one, or ask) and, with -c, its latest conversation."""
    agents = await api.agents()
    if not agents:
        print("No agents yet. Create one in Chatty first.", file=sys.stderr)
        return None
    if args.agent:
        agent = next((a for a in agents if a["slug"] == args.agent), None)
        if not agent:
            print(f"No agent {args.agent!r}. Agents: {', '.join(a['slug'] for a in agents)}", file=sys.stderr)
            return None
    elif len(agents) == 1:
        agent = agents[0]
    else:
        agent = (next((a for a in agents if a["id"] == cfg.get("last_agent_id")), None)
                 or await commands.pick(agents, commands.agent_label))
        if not agent:
            return None
    session = Session(api, cfg, agent)
    commands.set_agent(session, agent)
    if args.cont:
        convs = await api.conversations(agent["id"])
        if convs:
            await commands.open_conversation(session, convs[0]["id"])
        else:
            note("No conversations yet; starting a new one.")
    return session


async def chat(args, cfg: dict) -> int:
    api = Api(cfg["url"], cfg["device_token"])
    try:
        session = await open_session(api, args, cfg)
        if not session:
            return 1
        console.print(f"[bold]{session.agent['agent_name']}[/] [dim]· {cfg['url']} · {session.mode} mode · "
                      "/help for commands, Ctrl+D to exit[/]")
        await run(session)
        return 0
    except (ApiError, httpx.HTTPError) as e:
        print(f"{cfg['url']}: {why(e)}", file=sys.stderr)
        return 1
    finally:
        await api.http.aclose()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="chatty", description="Chat with your Chatty agents from a terminal.")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-a", "--agent", metavar="SLUG", help="chat with this agent (remembered)")
    ap.add_argument("-c", "--continue", dest="cont", action="store_true",
                    help="continue this agent's most recent conversation")
    ap.add_argument("--power", action="store_true", help="power mode: write tools run without asking (remembered)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("login", help="log in by scanning a QR code with your phone")
    p.add_argument("url", nargs="?", help="your Chatty URL (default: the saved one)")
    p.add_argument("--password", action="store_true", help="log in with the password (and 2FA code) instead")
    sub.add_parser("logout", help="revoke and forget this terminal's login")
    args = ap.parse_args(argv)
    if args.cmd == "login":
        return cmd_login(args.url, args.password)
    if args.cmd == "logout":
        return cmd_logout()
    cfg = config.load()
    if not cfg.get("device_token"):
        print("Not logged in. Run: chatty login <your Chatty URL>", file=sys.stderr)
        return 1
    if args.power:
        cfg["mode"] = "power"
        config.save(cfg)
    try:
        return asyncio.run(chat(args, cfg))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
