"""Monthly request quota for the Requests page card.

users.quota_monthly of 0 has always meant 'no cap'; that surfaces here as
unlimited=true so the UI hides the card instead of rendering '14 of 0'.
"""
from datetime import datetime, timezone


def _first_of_next_month() -> str:
    now = datetime.now(timezone.utc)
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return f"{year:04d}-{month:02d}-01T00:00:00Z"


def get_quota(user: dict | None) -> dict:
    import db

    limit = int(user.get("quota_monthly") or 0) if user else 0
    used = db.count_user_requests_this_month(user["id"]) if user else 0
    return {
        "used": used,
        "limit": limit,
        "resets_at": _first_of_next_month(),
        "unlimited": limit == 0,
    }
