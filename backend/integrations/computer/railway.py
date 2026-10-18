"""
Chatty — "Add computer to this Railway project": creates the computer service
next to Chatty, in the Railway project Chatty itself runs in, with a Railway API
token the user pastes once. The token is used for these calls only: never
stored, never logged, never echoed in an error.

Mutations, checked against the live schema by introspection (Oct 2026):
  serviceCreate(input: {projectId!, environmentId, name, source: {image}, variables})
  volumeCreate(input: {projectId!, environmentId, serviceId, mountPath!})
  serviceInstanceDeployV2(serviceId!, environmentId!) -> deployment id
Creating from an image and attaching a volume may each start a deployment of
their own; the explicit deploy at the end guarantees one that has the volume.
"""

import logging
import os
import secrets
import time

import httpx
from fastapi import HTTPException

from core.config import settings
from integrations.registry import get_credentials, save_credentials

logger = logging.getLogger(__name__)

RAILWAY_API = "https://backboard.railway.com/graphql/v2"
IMAGE = "ghcr.io/wwilson1017/chatty-computer:latest"
SERVICE_NAME = "computer"
PORT = 8080
INTERNAL_URL = f"http://{SERVICE_NAME}.railway.internal:{PORT}"  # Railway's private domain is <service>.railway.internal
BAD_TOKEN = ("Railway rejected the token. Use an account or workspace token from "
             "railway.com/account/tokens (project tokens can't create services).")
transport: httpx.AsyncBaseTransport | None = None  # tests inject a MockTransport

SERVICE_CREATE = "mutation ($input: ServiceCreateInput!) { serviceCreate(input: $input) { id name } }"
VOLUME_CREATE = "mutation ($input: VolumeCreateInput!) { volumeCreate(input: $input) { id } }"
DEPLOY = ("mutation ($serviceId: String!, $environmentId: String!) "
          "{ serviceInstanceDeployV2(serviceId: $serviceId, environmentId: $environmentId) }")


class RailwayError(Exception):
    def __init__(self, detail: str, status: int = 502):
        super().__init__(detail)
        self.status = status


async def _gql(http: httpx.AsyncClient, query: str, variables: dict, step: str) -> dict:
    """One GraphQL call. Railway reports authorization failures both as HTTP 401/403 and as a
    200 with `errors`, so both are checked. Nothing from the request (the token lives in a
    header) is ever put in an error message."""
    try:
        r = await http.post(RAILWAY_API, json={"query": query, "variables": variables})
    except httpx.HTTPError as e:
        raise RailwayError(f"Couldn't reach Railway's API while {step}: {e.__class__.__name__}") from e
    if r.status_code in (401, 403):
        raise RailwayError(BAD_TOKEN, 400)
    if r.status_code == 429:
        raise RailwayError("Railway's API rate limit was hit. Try again in a minute.")
    try:
        body = r.json()
    except ValueError:
        body = {}
    errors = body.get("errors") if isinstance(body, dict) else None
    if errors:
        msg = str((errors[0] or {}).get("message") or "unknown error")[:300]
        if "authoriz" in msg.lower() or "authenticat" in msg.lower():
            raise RailwayError(BAD_TOKEN, 400)
        raise RailwayError(f"Railway refused {step}: {msg}")
    if r.status_code >= 400:
        raise RailwayError(f"Railway answered HTTP {r.status_code} while {step}.")
    return body.get("data") or {}


async def add_to_railway(token: str) -> dict:
    """Create the `computer` service in this project and point Chatty at it (no redeploy needed)."""
    token = token.strip()
    if not settings.is_railway:
        raise HTTPException(status_code=400, detail="This Chatty isn't running on Railway. See docs/computer.md for the Docker setup.")
    if os.getenv("COMPUTER_URL") or os.getenv("COMPUTER_SECRET"):
        # Env wins over saved credentials (even half a pair), so anything saved here would be ignored.
        raise HTTPException(status_code=409, detail="COMPUTER_URL / COMPUTER_SECRET are set on the chatty service already. Change them there instead.")
    if settings.computer.is_configured:
        raise HTTPException(status_code=409, detail="A computer is already configured.")
    project_id, environment_id = os.getenv("RAILWAY_PROJECT_ID", ""), os.getenv("RAILWAY_ENVIRONMENT_ID", "")
    if not (project_id and environment_id):
        raise HTTPException(status_code=400, detail="Railway didn't give this service RAILWAY_PROJECT_ID / RAILWAY_ENVIRONMENT_ID.")
    if not token:
        raise HTTPException(status_code=400, detail="Paste a Railway API token.")

    secret = secrets.token_urlsafe(36)  # 48 chars; the computer refuses anything under 32
    async with httpx.AsyncClient(timeout=30, transport=transport, headers={"Authorization": f"Bearer {token}"}) as http:
        try:
            data = await _gql(http, SERVICE_CREATE, {"input": {
                "projectId": project_id, "environmentId": environment_id, "name": SERVICE_NAME,
                "source": {"image": IMAGE}, "variables": {"COMPUTER_SECRET": secret, "PORT": str(PORT)},
            }}, "creating the service")
        except RailwayError as e:
            raise HTTPException(status_code=e.status, detail=str(e)) from e
        service_id = str((data.get("serviceCreate") or {}).get("id") or "")
        if not service_id:
            raise HTTPException(status_code=502, detail="Railway created no service (empty reply).")
        # The service exists with this secret from here on, so save the pair now: a failure below
        # leaves a setup the user can finish in the dashboard instead of an orphaned service.
        save_credentials("computer", {**get_credentials("computer"), "url": INTERNAL_URL, "api_key": secret,
                                      "enabled": True, "setup_at": time.time()})
        try:
            await _gql(http, VOLUME_CREATE, {"input": {
                "projectId": project_id, "environmentId": environment_id, "serviceId": service_id, "mountPath": "/data",
            }}, "attaching the volume")
            await _gql(http, DEPLOY, {"serviceId": service_id, "environmentId": environment_id}, "deploying")
        except RailwayError as e:
            raise HTTPException(status_code=e.status, detail=(
                f"The computer service was created, but {str(e)[0].lower()}{str(e)[1:]} Finish in the Railway "
                f"dashboard: give the computer service a volume at /data and deploy it.")) from e
    logger.info("Computer: created Railway service %s (%s)", service_id, INTERNAL_URL)
    return {"ok": True, "service_id": service_id, "url": INTERNAL_URL}
