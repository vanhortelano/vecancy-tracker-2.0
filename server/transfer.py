"""Account data transfer, done on the server in ONE database transaction.

Why: the browser used to copy every record with many separate requests and then delete the old
ones. If anything failed half-way (closed tab, network, one bad record) the transfer was left
"approved" for ever: the old account showed "Working…" with no buttons, the new account waited for
ever, and some records existed twice. Here everything moves or nothing does.

Rules (same as before): only the account that created the code can complete it, only after the
receiving account requested it, and only into an EMPTY receiving account (nothing is overwritten).
The Viewer Access server ("settings/viewerAccess") and the Super Admin link stay with the old account.
"""
from datetime import datetime, timezone

from accounts import ApiError
from store import KINDS, fetch, list_docs, remove, write

MOVED = ["rooms", "shapes", "prospects", "temporary_dorm_clients", "tenant_history", "bed_transfers", "settings", "tenants"]
KEEP = {("settings", "viewerAccess")}


def _records(cur, uid):
    out = {}
    for kind in MOVED:
        out[kind] = [(i, doc) for i, doc, _v in list_docs(cur, KINDS[kind], [uid], limit=5000)
                     if (kind, i) not in KEEP]
    return out


def complete(conn, uid, code):
    code = str(code or "").strip().upper()
    if not code or len(code) > 40:
        raise ApiError(400, "bad_code", "Enter the transfer code.")
    now = datetime.now(timezone.utc)
    with conn.transaction():
        cur = conn.cursor()
        t, _v = fetch(cur, KINDS["accountTransfers"], (code,), lock=True)
        if not t or t.get("fromUid") != uid:
            raise ApiError(404, "not_found", "That transfer code was not found for this account.")
        if t.get("status") == "done":
            raise ApiError(409, "already_done", "This transfer was already completed.")
        if t.get("status") not in ("requested", "approved") or not t.get("toUid"):
            raise ApiError(409, "not_requested", "The new account has not requested this transfer yet.")
        to_uid = t["toUid"]
        if to_uid == uid:
            raise ApiError(400, "same_account", "You can't transfer to yourself.")
        inc, _v = fetch(cur, KINDS["incomingTransfer"], (to_uid,), lock=True)
        if not inc or inc.get("code") != code or inc.get("fromUid") != uid:
            raise ApiError(409, "not_requested", "The new account's request does not match this code.")
        theirs = _records(cur, to_uid)
        if any(theirs.values()):
            raise ApiError(409, "not_empty", "The new account already has data, so nothing was moved. "
                                             "It must be empty to receive a transfer.")
        mine = _records(cur, uid)
        counts = {}
        for kind, rows in mine.items():
            spec = KINDS[kind]
            for doc_id, doc in rows:
                write(cur, spec, (to_uid, doc_id), doc, now, lenient=True)      # same id, same content
            # verify inside the same transaction before removing anything
            copied = {i for i, _d in _records(cur, to_uid)[kind]}
            if not {i for i, _d in rows} <= copied:
                raise ApiError(500, "copy_failed", "Copying %s failed. Nothing was moved." % kind)
            for doc_id, _doc in rows:
                remove(cur, spec, (uid, doc_id))
            counts[kind] = len(rows)
        cur.execute("UPDATE tenant_photos SET owner_uid=%s WHERE owner_uid=%s", (to_uid, uid))   # photos follow their tenants
        cur.execute("UPDATE tenant_files SET owner_uid=%s WHERE owner_uid=%s", (to_uid, uid))    # and so do their documents
        done = dict(t, status="done")
        write(cur, KINDS["accountTransfers"], (code,), done, now, lenient=True)
    return {"ok": True, "moved": counts, "toEmail": t.get("toEmail") or ""}
