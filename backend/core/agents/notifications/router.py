"""REST API for notifications and push subscriptions."""

from fastapi import APIRouter, Depends

from core.auth import get_current_user

from . import service, subscriptions
from .vapid import get_vapid_public_key

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    agent: str | None = None,
    status: str = "active",
    limit: int = 10,
    user=Depends(get_current_user),
):
    return service.list_notifications(agent=agent, status=status, limit=min(limit, 50))


@router.post("/{notification_id}/dismiss")
async def dismiss_notification(notification_id: str, user=Depends(get_current_user)):
    return service.dismiss_notification(notification_id)


@router.post("/dismiss-all")
async def dismiss_all(body: dict | None = None, user=Depends(get_current_user)):
    agent = (body or {}).get("agent")
    count = service.dismiss_all(agent=agent)
    return {"ok": True, "dismissed": count}


@router.post("/push/subscribe")
async def push_subscribe(body: dict, user=Depends(get_current_user)):
    from fastapi import HTTPException

    endpoint = body.get("endpoint", "")
    keys = body.get("keys", {})
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")
    user_agent = body.get("user_agent", "")

    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="endpoint, keys.p256dh, and keys.auth are required")

    return subscriptions.save_subscription(endpoint, p256dh, auth, user_agent)


@router.post("/push/unsubscribe")
async def push_unsubscribe(body: dict, user=Depends(get_current_user)):
    from fastapi import HTTPException

    endpoint = body.get("endpoint", "")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint is required")
    return subscriptions.remove_subscription(endpoint)


@router.get("/push/vapid-public-key")
async def vapid_public_key():
    return {"public_key": get_vapid_public_key()}
