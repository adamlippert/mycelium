"""Admin actions on the TorBox account pool, behind /ui/api/torbox-accounts."""
import logging
import sqlite3

import db
import torbox_pool

log = logging.getLogger(__name__)

_MAX_LABEL_LEN = 40


def list_accounts() -> list[dict]:
    counts = db.count_items_by_account()
    out = []
    for a in torbox_pool.accounts(enabled_only=False):
        h = torbox_pool.health(a.id)
        out.append({"id": a.id, "label": a.label, "enabled": a.enabled, "key_hint": a.api_key[-4:],
                    "items": counts.get(a.id, 0),
                    "health": {k: h[k] for k in ("rate_limited_until", "auth_failed_at", "budget_left")}})
    return out


def add(label: str, api_key: str) -> dict:
    label, api_key = (label or "").strip()[:_MAX_LABEL_LEN], (api_key or "").strip()
    if not label or not api_key:
        return {"ok": False, "message": "label and API key are required"}
    if any(a.label == label for a in torbox_pool.accounts(enabled_only=False)):
        return {"ok": False, "message": f"an account labelled {label!r} exists"}
    try:
        new_id = db.insert_torbox_account(label, api_key)
    except sqlite3.IntegrityError:
        log.debug("TorBox account add: label %r collided at insert (race)", label)
        return {"ok": False, "message": f"an account labelled {label!r} exists"}
    torbox_pool.invalidate()
    db.log_activity("added", "TorBox account", label, True)
    return {"ok": True, "id": new_id, "message": f"account {label} added"}


def update(account_id: int, *, label=None, api_key=None, enabled=None) -> dict:
    if db.get_torbox_account(account_id) is None:
        return {"ok": False, "message": "unknown account"}
    if label is not None:
        label = label.strip()[:_MAX_LABEL_LEN]
        if not label:
            return {"ok": False, "message": "label is required"}
    if api_key is not None:
        api_key = api_key.strip()
    if account_id == 1 and api_key is not None:
        import settings
        settings.set("TORBOX_API_KEY", api_key)   # mirrors into row 1
        api_key = None
    db.update_torbox_account(account_id, label=label, api_key=api_key, enabled=enabled)
    torbox_pool.invalidate()
    return {"ok": True, "message": "saved"}


def delete(account_id: int) -> dict:
    if account_id == 1:
        return {"ok": False, "message": "account 1 is the configured TorBox API key; change it in Settings instead"}
    if db.get_torbox_account(account_id) is None:
        return {"ok": False, "message": "unknown account"}
    homed = db.count_items_by_account().get(account_id, 0)
    if homed:
        return {"ok": False, "message": f"{homed} title{'s' if homed != 1 else ''} still on this account; disable it instead, they move on their next play"}
    db.delete_torbox_account(account_id)
    torbox_pool.invalidate()
    return {"ok": True, "message": "account removed"}


def test(account_id: int) -> dict:
    import service_tests
    acct = torbox_pool.account(account_id)
    if acct is None:
        return {"ok": False, "message": "unknown account"}
    return service_tests.run("torbox", {"TORBOX_API_KEY": acct.api_key})
