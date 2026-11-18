"""Vacancy Tracker server: serves the pages and the JSON API on top of PostgreSQL.

Run:  DATABASE_URL=postgresql://... FIREBASE_SERVICE_ACCOUNT_JSON='{...}' python app.py
Firebase is used ONLY to verify sign-ins and to hold the generated username/password.
"""
import logging
import os
import re
import sys
from pathlib import Path

from flask import Flask, g, jsonify, request, send_from_directory

import accounts
import ai
import engine
from datetime import datetime, timezone

from store import KINDS, Aborted, Denied, Invalid, fetch, write

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))                # brain.py (the assistant) lives in the project root
STATIC_EXT = {".html", ".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".webp", ".woff", ".woff2", ".txt"}
# Content types are fixed here, not taken from the operating system: on some Windows PCs the registry maps
# .js to text/plain, and with nosniff the browser then refuses to run the scripts (blank white page).
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".ico": "image/x-icon", ".webp": "image/webp", ".woff": "font/woff",
        ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8"}
BLOCKED_NAMES = {"seed-data.js"}                 # real tenant data: never served by a hosted server (local test mode only)
log = logging.getLogger("vacancy")
APP_VERSION = "2026.11.12-easy"

HTTP = {Denied: (403, "permission-denied", "You do not have access to that."),
        Aborted: (409, "aborted", "The data changed. Please retry."),
        Invalid: (400, "invalid-argument", "That request was not valid."),
        engine.NotFound: (404, "not-found", "That record was not found."),
        engine.AlreadyExists: (409, "already-exists", "That record already exists.")}


class _Pool:
    """Minimal connection pool (one connection per request)."""
    def __init__(self, url, max_size=10):
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
        self.pool = ConnectionPool(url, min_size=1, max_size=max_size, open=True, timeout=15,
                                   kwargs={"row_factory": dict_row, "autocommit": True})

    def connection(self):
        return self.pool.connection()


def create_app(database_url=None, verifier=None, fb=None, brain_factory=None, pool=None, local_dir=None,
               easy_login=False):
    """local_dir switches on LOCAL TEST MODE: SQLite file in that folder + the temporary username/
    password login (no Firebase, no PostgreSQL). It is never enabled by default."""
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024        # file uploads; JSON bodies are held to 2 MB in body()
    local = None
    if local_dir:
        import localauth
        from localdb import LocalPool
        pool = LocalPool(Path(local_dir) / "vacancy.db")
        local = localauth.LocalAuth(pool, localauth.load_secret(local_dir), easy=easy_login)
        verifier = local.verify

        class _NoFirebase:                      # Firebase account routes do not exist in local mode
            def __getattr__(self, _name):
                raise accounts.ApiError(404, "not_available", "Not available in local test mode.")
        fb = _NoFirebase()
    else:
        pool = pool or _Pool(database_url or os.environ["DATABASE_URL"])
        if fb is None:
            fb = accounts.FirebaseOps()
        verifier = verifier or fb.verify
    app.extensions["pool"] = pool
    state = {"brain": None}
    limit_auth = accounts.RateLimiter(12, 600)
    limit_ai = accounts.RateLimiter(20, 60)

    def brain():
        if state["brain"] is None:
            if brain_factory:
                state["brain"] = brain_factory()
            else:
                try:
                    state["brain"] = __import__("brain").Brain()
                except ImportError as e:      # scikit-learn missing or blocked on this computer
                    log.warning("scikit-learn unavailable (%s); using the built-in backup matcher", e)
                    state["brain"] = __import__("brain_lite").Brain()
        return state["brain"]

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    if local:
        LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?$")

        @app.after_request
        def local_preview_cors(resp):
            """Local test mode only: VS Code Live Server / Live Preview pages (another port on this
            computer) may call this server. Never enabled on a hosted server."""
            origin = request.headers.get("Origin", "")
            if LOCAL_ORIGIN.match(origin):
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-File-Name"
                resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
                resp.headers["Access-Control-Max-Age"] = "600"
                resp.headers["Vary"] = "Origin"
            return resp

    @app.errorhandler(accounts.ApiError)
    def api_error(e):
        return jsonify({"error": e.code, "message": e.message}), e.status

    @app.errorhandler(Exception)
    def other_error(e):
        for cls, (status, code, msg) in HTTP.items():
            if isinstance(e, cls):
                return jsonify({"error": code, "message": msg}), status
        if hasattr(e, "code") and isinstance(getattr(e, "code"), int):   # werkzeug HTTPException
            return jsonify({"error": "http", "message": "Request failed."}), e.code
        log.exception("unhandled error")                   # details stay in the server log
        return jsonify({"error": "internal", "message": "Something went wrong. Please try again."}), 500

    def token_claims():
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer ") or len(header) > 4000:
            raise accounts.ApiError(401, "unauthenticated", "Please sign in.")
        try:
            claims = verifier(header[7:])
        except Exception:
            raise accounts.ApiError(401, "unauthenticated", "Your sign-in expired. Please sign in again.")
        if not claims.get("uid"):
            raise accounts.ApiError(401, "unauthenticated", "Please sign in.")
        return claims

    def account_uid(conn):
        """The user id comes ONLY from the verified token, and must belong to a registered account."""
        claims = token_claims()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM accounts WHERE user_id=%s", (claims["uid"],))
        if not cur.fetchone():
            raise accounts.ApiError(403, "account_required",
                                    "This sign-in is not linked to a Vecancy account yet. Use Create Account first.")
        return claims["uid"]

    def body():
        if (request.content_length or 0) > 2 * 1024 * 1024:
            raise Invalid("request too large")
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise Invalid("json body required")
        return data

    @app.get("/mode.js")
    def mode_js():
        """Tells the login screen whether this is the temporary local test mode."""
        resp = app.response_class("window.VT_LOCAL_MODE=%s;window.VT_EASY_LOGIN=%s;" % (
                                      "true" if local else "false", "true" if local and local.easy else "false"),
                                  mimetype="application/javascript")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ------------------------------------------------------------------ local test login
    if local:
        @app.post("/api/local/check-name")
        def local_check_name():
            return jsonify(local.check_name(request.remote_addr, body().get("username")))

        @app.post("/api/local/register")
        def local_register():
            d = body()
            return jsonify(local.register(request.remote_addr, d.get("username"), d.get("password"), d.get("email"),
                                          d.get("survey")))

        @app.post("/api/local/login")
        def local_login():
            d = body()
            return jsonify(local.login(request.remote_addr, d.get("username"), d.get("password")))

        @app.post("/api/local/password")
        def local_password():
            d = body()
            return jsonify(local.change_password(request.remote_addr, d.get("username"),
                                                 d.get("currentPassword"), d.get("newPassword")))

    # ------------------------------------------------------------------ accounts
    @app.post("/api/account/register")
    def register():
        claims = token_claims()
        limit_auth.check(("reg", request.remote_addr))
        data = body()
        with pool.connection() as conn:
            return jsonify(accounts.register(conn, fb, claims, data.get("username"), data.get("password")))

    @app.post("/api/account/lookup")
    def lookup():
        claims = token_claims()
        limit_auth.check(("look", request.remote_addr))
        with pool.connection() as conn:
            return jsonify(accounts.lookup(conn, claims))

    @app.post("/api/account/password")
    def password():
        claims = token_claims()
        limit_auth.check(("pw", request.remote_addr))
        with pool.connection() as conn:
            return jsonify(accounts.change_password(conn, fb, claims, body().get("newPassword")))

    @app.post("/api/account/check-name")
    def check_name():
        """Live 'is this name free?' hint while typing. The real guarantee is the database."""
        token_claims()
        limit_auth.check(("name", request.remote_addr))
        _name, full = accounts.clean_username(body().get("username"))
        with pool.connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM accounts WHERE username_lower=%s", (full.lower(),))
            return jsonify({"username": full, "available": cur.fetchone() is None})

    @app.get("/api/session")
    def session():
        claims = token_claims()
        with pool.connection() as conn:
            return jsonify(accounts.session(conn, claims["uid"]))

    # ------------------------------------------------------------------ data
    @app.post("/api/get")
    def get_doc():
        with pool.connection() as conn:
            return jsonify(engine.get_doc(conn, account_uid(conn), body().get("path")))

    @app.post("/api/query")
    def query():
        data = body()
        with pool.connection() as conn:
            uid = account_uid(conn)
            rows = engine.query(conn, uid, data.get("path"), data.get("where"), data.get("orderBy"), data.get("limit"))
            return jsonify({"docs": rows})

    @app.post("/api/read")
    def read_many():
        data = body()
        with pool.connection() as conn:
            uid = account_uid(conn)
            return jsonify({"results": engine.read_many(conn, uid, data.get("ops"))})

    @app.post("/api/commit")
    def commit():
        data = body()
        with pool.connection() as conn:
            uid = account_uid(conn)
            return jsonify({"ok": engine.commit(conn, uid, data.get("reads") or [], data.get("writes") or [])})

    # ------------------------------------------------------------------ tenant photographs
    PHOTO_TYPES = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n", "image/webp": b"RIFF"}
    PHOTO_MAX = 1_500_000

    def _tenant_id(raw):
        if not isinstance(raw, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", raw):
            raise Invalid("bad tenant id")
        return raw

    @app.put("/api/tenant-photo/<tenant_id>")
    def tenant_photo_put(tenant_id):
        """Save or replace a tenant's photograph. Only the admin who owns the tenant record may do this;
        only real JPEG / PNG / WebP images up to 1.5 MB are accepted."""
        tenant_id = _tenant_id(tenant_id)
        mime = (request.mimetype or "").lower()
        data = request.get_data(cache=False)
        magic = PHOTO_TYPES.get(mime)
        if not magic or not data or len(data) > PHOTO_MAX or not data.startswith(magic) \
                or (mime == "image/webp" and data[8:12] != b"WEBP"):
            raise accounts.ApiError(400, "bad_photo", "Use a JPEG, PNG or WebP photo up to 1.5 MB.")
        with pool.connection() as conn:
            uid = account_uid(conn)
            limit_ai.check(("photo", uid))
            with conn.transaction():
                cur = conn.cursor()
                doc, _v = fetch(cur, KINDS["tenants"], (uid, tenant_id), lock=True)
                if doc is None:
                    raise accounts.ApiError(404, "not_found", "Save the tenant's information first.")
                cur.execute("DELETE FROM tenant_photos WHERE owner_uid=%s AND tenant_id=%s", (uid, tenant_id))
                cur.execute("INSERT INTO tenant_photos (owner_uid, tenant_id, mime, size, data) VALUES (%s,%s,%s,%s,%s)",
                            (uid, tenant_id, mime, len(data), data))
                version = int(datetime.now(timezone.utc).timestamp() * 1000)
                write(cur, KINDS["tenants"], (uid, tenant_id), dict(doc, photoVersion=version), datetime.now(timezone.utc))
        return jsonify({"ok": True, "photoVersion": version})

    @app.get("/api/tenant-photo/<tenant_id>")
    def tenant_photo_get(tenant_id):
        tenant_id = _tenant_id(tenant_id)
        with pool.connection() as conn:
            uid = account_uid(conn)
            row = conn.cursor().execute("SELECT mime, data FROM tenant_photos WHERE owner_uid=%s AND tenant_id=%s",
                                        (uid, tenant_id)).fetchone()
        if not row:
            return jsonify({"error": "not-found", "message": "No photo."}), 404
        resp = app.response_class(bytes(row["data"]), mimetype=row["mime"])
        resp.headers["Cache-Control"] = "private, no-store"
        resp.headers["Content-Disposition"] = "inline"
        return resp

    # ------------------------------------------------------------------ dormitory photo (Central Link)
    @app.put("/api/branch-photo")
    def branch_photo_put():
        """The Branch Admin's dormitory picture, shown on the Super Admin's dormitory card. Only for a
        dormitory that is linked to a Super Admin (a branches record exists for this account)."""
        mime = (request.mimetype or "").lower()
        data = request.get_data(cache=False)
        magic = PHOTO_TYPES.get(mime)
        if not magic or not data or len(data) > PHOTO_MAX or not data.startswith(magic) \
                or (mime == "image/webp" and data[8:12] != b"WEBP"):
            raise accounts.ApiError(400, "bad_photo", "Use a JPEG, PNG or WebP photo up to 1.5 MB.")
        with pool.connection() as conn:
            uid = account_uid(conn)
            limit_ai.check(("photo", uid))
            with conn.transaction():
                cur = conn.cursor()
                doc, _v = fetch(cur, KINDS["branches"], (uid,), lock=True)
                if doc is None:
                    raise accounts.ApiError(404, "not_found", "Link this dormitory to a Super Admin first.")
                cur.execute("DELETE FROM branch_photos WHERE branch_uid=%s", (uid,))
                cur.execute("INSERT INTO branch_photos (branch_uid, mime, size, data) VALUES (%s,%s,%s,%s)", (uid, mime, len(data), data))
                version = int(datetime.now(timezone.utc).timestamp() * 1000)
                write(cur, KINDS["branches"], (uid,), dict(doc, photoVersion=version), datetime.now(timezone.utc))
        return jsonify({"ok": True, "photoVersion": version})

    @app.get("/api/branch-photo/<branch_uid>")
    def branch_photo_get(branch_uid):
        """Readable by the dormitory itself and by the Super Admin who requested the connection."""
        branch_uid = _tenant_id(branch_uid)
        with pool.connection() as conn:
            uid = account_uid(conn)
            cur = conn.cursor()
            doc, _v = fetch(cur, KINDS["branches"], (branch_uid,))
            sup = cur.execute("SELECT 1 FROM super_admins WHERE uid=%s", (uid,)).fetchone()
            if not doc or not (uid == branch_uid or (sup and doc.get("requestedBy") == uid)):
                return jsonify({"error": "not-found", "message": "No photo."}), 404
            row = cur.execute("SELECT mime, data FROM branch_photos WHERE branch_uid=%s", (branch_uid,)).fetchone()
        if not row:
            return jsonify({"error": "not-found", "message": "No photo."}), 404
        resp = app.response_class(bytes(row["data"]), mimetype=row["mime"])
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    # ------------------------------------------------------------------ open a dorm from the Marketing Directory
    @app.post("/api/central/open-dorm")
    def central_open_dorm():
        """A viewer of a Super Admin's directory server opens a listed dormitory as a Dormitory Viewer without the
        dorm code or password (feedback A-0027). Allowed only when ALL of these hold, checked here on the server:
          - the caller joined that directory server (centralAccess/{central}/viewers/{uid}) with the current
            password, is not blocked, and the server is switched on;
          - the dormitory is linked to that same Super Admin and its Branch Admin approved Directory;
          - the dormitory's own Viewer Access is switched on (the same name-free page its viewers see).
        The caller is then added to that dormitory's viewer list (the Branch Admin sees and can remove them)."""
        body = request.get_json(silent=True) or {}
        central, branch = str(body.get("central") or ""), str(body.get("branch") or "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{1,29}", central) or not re.fullmatch(r"[A-Za-z0-9_.\-]{1,128}", branch):
            raise accounts.ApiError(400, "bad_request", "Unknown dormitory.")
        deny = accounts.ApiError(403, "permission-denied", "This dormitory can't be opened from here. Ask its Branch Admin for the dorm code.")
        with pool.connection() as conn:
            uid = account_uid(conn)
            with conn.transaction():
                cur = conn.cursor()
                acc = fetch(cur, KINDS["centralAccess"], (central,))[0]
                sec = fetch(cur, KINDS["centralSecrets"], (central,))[0]
                me = fetch(cur, KINDS["central_viewers"], (central, uid))[0]
                if not acc or acc.get("enabled") is not True or not me or not sec or me.get("proof") != sec.get("passwordHash") \
                        or fetch(cur, KINDS["central_blocked"], (central, uid))[0] is not None:
                    raise deny
                b = fetch(cur, KINDS["branches"], (branch,))[0]
                if not b or b.get("requestedBy") != acc.get("ownerUid") or b.get("dirStatus") != "approved":
                    raise deny
                row = cur.execute("SELECT code FROM dorms WHERE owner_uid=%s AND enabled IS TRUE ORDER BY updated_at DESC LIMIT 1", (branch,)).fetchone()
                if not row:
                    raise accounts.ApiError(404, "not_found", "This dormitory has no viewer page switched on.")
                code = row["code"]
                if fetch(cur, KINDS["dorm_blocked"], (code, uid))[0] is not None:
                    raise deny
                dsec = fetch(cur, KINDS["dormSecrets"], (code,))[0] or {}
                now = datetime.now(timezone.utc)
                if fetch(cur, KINDS["dorm_viewers"], (code, uid))[0] is None:
                    write(cur, KINDS["dorm_viewers"], (code, uid), {"proof": dsec.get("passwordHash"), "name": me.get("name") or "",
                          "email": me.get("email") or "", "joinedAt": {"__ts": int(now.timestamp() * 1000)}, "via": "directory:" + central}, now, lenient=True)
        return jsonify({"ok": True, "code": code})

    # ------------------------------------------------------------------ tenant supporting documents
    FILE_TYPES = {"application/pdf": b"%PDF-", "image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n",
                  "image/webp": b"RIFF", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": b"PK\x03\x04"}
    FILE_MAX, FILES_PER_TENANT = 5 * 1024 * 1024, 10

    def _file_upload():
        from urllib.parse import unquote
        mime = (request.mimetype or "").lower()
        data = request.get_data(cache=False)
        magic = FILE_TYPES.get(mime)
        if not magic or not data or len(data) > FILE_MAX or not data.startswith(magic) \
                or (mime == "image/webp" and data[8:12] != b"WEBP"):
            raise accounts.ApiError(400, "bad_file", "Use a PDF, Word (.docx), JPEG, PNG or WebP file up to 5 MB.")
        name = unquote(request.headers.get("X-File-Name", "") or "file")
        name = re.sub(r"[^\w .()\-]+", "_", name).strip()[:120] or "file"
        return name, mime, data

    def _tenant_or_404(cur, uid, tenant_id):
        if fetch(cur, KINDS["tenants"], (uid, tenant_id))[0] is None:
            raise accounts.ApiError(404, "not_found", "Save the tenant's information first.")

    @app.get("/api/tenant-files/<tenant_id>")
    def tenant_files_list(tenant_id):
        tenant_id = _tenant_id(tenant_id)
        with pool.connection() as conn:
            uid = account_uid(conn)
            rows = conn.cursor().execute("SELECT id, name, mime, size, uploaded_at FROM tenant_files WHERE owner_uid=%s AND tenant_id=%s "
                                         "ORDER BY uploaded_at", (uid, tenant_id)).fetchall()
        return jsonify({"files": [{"id": r["id"], "name": r["name"], "mime": r["mime"], "size": r["size"],
                                   "uploadedAt": r["uploaded_at"].isoformat()} for r in rows]})

    @app.post("/api/tenant-files/<tenant_id>")
    def tenant_files_add(tenant_id):
        tenant_id = _tenant_id(tenant_id)
        name, mime, data = _file_upload()
        with pool.connection() as conn:
            uid = account_uid(conn)
            limit_ai.check(("file", uid))
            with conn.transaction():
                cur = conn.cursor()
                _tenant_or_404(cur, uid, tenant_id)
                count = cur.execute("SELECT count(*) AS n FROM tenant_files WHERE owner_uid=%s AND tenant_id=%s", (uid, tenant_id)).fetchone()["n"]
                if count >= FILES_PER_TENANT:
                    raise accounts.ApiError(409, "too_many", "A tenant can have up to %d documents. Remove one first." % FILES_PER_TENANT)
                from store import new_id
                fid = new_id()
                cur.execute("INSERT INTO tenant_files (owner_uid, tenant_id, id, name, mime, size, data) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (uid, tenant_id, fid, name, mime, len(data), data))
        return jsonify({"ok": True, "id": fid})

    @app.route("/api/tenant-files/<tenant_id>/<file_id>", methods=["GET", "PUT", "DELETE"])
    def tenant_file_one(tenant_id, file_id):
        tenant_id, file_id = _tenant_id(tenant_id), _tenant_id(file_id)
        upload = _file_upload() if request.method == "PUT" else None
        with pool.connection() as conn:
            uid = account_uid(conn)
            with conn.transaction():
                cur = conn.cursor()
                row = cur.execute("SELECT name, mime, data FROM tenant_files WHERE owner_uid=%s AND tenant_id=%s AND id=%s",
                                  (uid, tenant_id, file_id)).fetchone()
                if not row:
                    return jsonify({"error": "not-found", "message": "That document was not found."}), 404
                if request.method == "DELETE":
                    cur.execute("DELETE FROM tenant_files WHERE owner_uid=%s AND tenant_id=%s AND id=%s", (uid, tenant_id, file_id))
                    return jsonify({"ok": True})
                if request.method == "PUT":
                    name, mime, data = upload
                    cur.execute("UPDATE tenant_files SET name=%s, mime=%s, size=%s, data=%s, uploaded_at=now() "
                                "WHERE owner_uid=%s AND tenant_id=%s AND id=%s", (name, mime, len(data), data, uid, tenant_id, file_id))
                    return jsonify({"ok": True, "id": file_id})
        resp = app.response_class(bytes(row["data"]), mimetype=row["mime"])
        resp.headers["Cache-Control"] = "private, no-store"
        resp.headers["Content-Disposition"] = 'attachment; filename="%s"' % row["name"].replace('"', "")
        return resp

    # ------------------------------------------------------------------ account data transfer
    @app.post("/api/transfer/complete")
    def transfer_complete():
        """The old account approves: everything moves in one database transaction (or nothing does)."""
        import transfer
        with pool.connection() as conn:
            uid = account_uid(conn)
            limit_auth.check(("transfer", uid))
            return jsonify(transfer.complete(conn, uid, body().get("code")))

    # ------------------------------------------------------------------ assistant
    @app.post("/api/assistant")
    def assistant():
        with pool.connection() as conn:
            uid = account_uid(conn)
            limit_ai.check(("ai", uid))
            data = body()
            full = str(data.get("question", "")).strip()
            question, unread = full[:ai.understand.MAX_CHARS], full[ai.understand.MAX_CHARS:]   # anything past the limit is reported, never silently dropped
            if not question:
                raise accounts.ApiError(400, "empty", "Ask a question first.")
            cid = data.get("conversationId")
            ctx = data.get("context") if isinstance(data.get("context"), dict) else None
            return jsonify(ai.answer(conn, brain, uid, question, cid if isinstance(cid, str) else None, ctx, unread=unread))

    @app.post("/api/assistant/history")
    def assistant_history():
        with pool.connection() as conn:
            uid = account_uid(conn)
            cid = body().get("conversationId")
            return jsonify({"messages": ai.history(conn, uid, cid) if isinstance(cid, str) else []})

    @app.post("/api/assistant/recent")
    def assistant_recent():
        with pool.connection() as conn:
            uid = account_uid(conn)
            return jsonify(ai.recent(conn, uid))

    @app.post("/api/assistant/memory")
    def assistant_memory():
        """List or clear THIS account's assistant memory. The owner comes from the verified token only."""
        import agent
        with pool.connection() as conn:
            uid = account_uid(conn)
            if body().get("clear") is True:
                with conn.transaction():
                    agent.mem_del(conn.cursor(), uid)
            with conn.transaction():
                return jsonify({"items": agent.memory_list(conn, uid)})

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "app": "vacancy-tracker", "version": APP_VERSION, "local": bool(local)})

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def home():
        return send_from_directory(ROOT, "index.html", mimetype=MIME[".html"])

    @app.get("/<path:name>")
    def static_file(name):
        p = (ROOT / name).resolve()
        ok = (ROOT in p.parents and p.is_file() and p.suffix.lower() in STATIC_EXT
              and (local or p.name not in BLOCKED_NAMES) and p.relative_to(ROOT).parts[0] not in ("server", "legacy")
              and not any(part.startswith(".") for part in p.relative_to(ROOT).parts))
        if not ok:
            return jsonify({"error": "not-found", "message": "Not found."}), 404
        resp = send_from_directory(ROOT, p.relative_to(ROOT).as_posix(), mimetype=MIME.get(p.suffix.lower()))
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
