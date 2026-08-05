"""
Chatty — shared web app manifest for the no-login todo surfaces.

/capture and /todo both install as standalone home-screen apps; the only
differences are the name, description, and icon set.
"""

import json

from fastapi.responses import Response


def manifest_response(*, name: str, description: str, icon_prefix: str, base_path: str) -> Response:
    """Web app manifest so Add to Home Screen installs a standalone app.

    start_url/scope carry the secret path when one is set, so the installed
    app always opens already "authenticated" — the token is baked into the
    launch URL. That is also why the response is no-store: it must never
    outlive a regenerate.
    """
    manifest = {
        "name": name,
        "short_name": name,
        "description": description,
        # No trailing slash on purpose: the page is served (and the settings
        # UI copies the link) at exactly base_path, and a base_path + "/"
        # scope would put the install page itself outside its own manifest
        # scope, degrading installability. Cost: the tokenless /todo scope
        # also prefix-matches /todos (cosmetic, non-default mode).
        "start_url": base_path,
        "scope": base_path,
        "display": "standalone",
        "background_color": "#0A0C0F",
        "theme_color": "#0A0C0F",
        "icons": [
            {"src": f"{icon_prefix}-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": f"{icon_prefix}-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    return Response(
        json.dumps(manifest),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )
