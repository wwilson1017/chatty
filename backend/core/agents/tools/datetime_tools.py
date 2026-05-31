from datetime import datetime
from zoneinfo import ZoneInfo

CT_TZ = ZoneInfo("America/Chicago")


def get_current_datetime() -> dict:
    now = datetime.now(CT_TZ)
    dst_state = "CDT" if now.dst() else "CST"
    offset = now.strftime("%z")
    return {
        "iso": now.isoformat(),
        "human": now.strftime(f"%A, %B %d, %Y at %I:%M %p {dst_state}"),
        "day_of_week": now.strftime("%A"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timezone": "America/Chicago",
        "dst_state": dst_state,
        "utc_offset": offset[:3] + ":" + offset[3:],
    }
