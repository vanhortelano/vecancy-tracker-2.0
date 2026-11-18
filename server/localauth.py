"""TEMPORARY LOCAL LOGIN (no Firebase), for trying the whole app on one computer.

Same rules as the real system: a unique generated username (name@vecancy.tracker), a password that
is only ever stored as a salted PBKDF2 hash, an unguessable signed session token, rate limiting,
and the user id comes only from a verified token. Passwords can only be changed by someone who
proves the current password. Switched on by run_local.py; production uses Firebase instead.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from accounts import DOMAIN, ApiError, RateLimiter, check_password, clean_username
from store import new_id

log = logging.getLogger("vacancy")
ITERATIONS = 310_000
TOKEN_SECONDS = 12 * 3600
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password, stored):
    try:
        _scheme, iters, salt, digest = stored.split("$")
        again = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(iters))
        return hmac.compare_digest(again, _unb64(digest))
    except Exception:
        return False


_DUMMY = hash_password("not-a-real-password")          # so unknown names cost the same time as wrong passwords


def load_secret(data_dir):
    """Signing key for session tokens: environment first, else a random key kept in local-data/."""
    env = os.environ.get("VT_LOCAL_SECRET")
    if env:
        return env.encode()
    path = Path(data_dir) / "secret.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(secrets.token_bytes(32))
    return path.read_bytes()


def easy_name(raw):
    """Easy login: turn any typed name into a valid username ('Juan Cruz' -> 'juan.cruz')."""
    name = str(raw or "").strip().lower()
    if name.endswith(DOMAIN):
        name = name[: -len(DOMAIN)]
    name = re.sub(r"[^a-z0-9._-]+", ".", name).strip("._-")
    name = re.sub(r"\.{2,}", ".", name)[:30]
    if len(name) < 3:
        name = (name + "user")[:30] if name else "user"
    if not name[0].isalnum():
        name = "u" + name[1:]
    return clean_username(name)


def is_email(raw):
    """True for an ordinary email address (the front page signs in with email); False for name@vecancy.tracker."""
    t = str(raw or "").strip().lower()
    return bool(_EMAIL_RE.match(t)) and not t.endswith(DOMAIN)


class LocalAuth:
    def __init__(self, pool, secret, easy=False):
        self.pool, self.secret = pool, secret
        self.easy = easy          # EASY LOGIN (local test mode only): any name + any password signs in
        self.limit_login = RateLimiter(10, 600)
        self.limit_other = RateLimiter(20, 600)

    # ----------------------------------------------------------- tokens
    def _sign(self, payload):
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        return body + "." + _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())

    def issue(self, uid, username, token_version):
        exp = int(time.time()) + TOKEN_SECONDS
        return self._sign({"uid": uid, "u": username, "tv": token_version, "exp": exp}), exp

    def verify(self, token):
        """Same contract as the Firebase verifier: returns claims or raises."""
        body, _, sig = token.partition(".")
        good = _b64(hmac.new(self.secret, body.encode(), hashlib.sha256).digest())
        if not sig or not hmac.compare_digest(sig, good):
            raise ValueError("bad token")
        p = json.loads(_unb64(body))
        if int(p["exp"]) < time.time():
            raise ValueError("expired")
        with self.pool.connection() as conn:
            row = conn.execute("SELECT token_version FROM local_credentials WHERE user_id=%s", (p["uid"],)).fetchone()
        if not row or row["token_version"] != p["tv"]:      # password changed or account gone
            raise ValueError("revoked")
        return {"uid": p["uid"], "email": p["u"], "email_verified": True}

    # ----------------------------------------------------------- accounts
    def check_name(self, ip, raw):
        self.limit_other.check(("name", ip))
        _name, full = clean_username(raw)
        with self.pool.connection() as conn:
            taken = conn.execute("SELECT 1 FROM accounts WHERE username_lower=%s", (full.lower(),)).fetchone()
        return {"username": full, "available": taken is None}

    def _free_name(self, conn, email):
        """A unique username made from the email ('ana.cruz@gmail.com' -> 'ana.cruz', then 'ana.cruz2', ...)."""
        base, _full = easy_name(email.split("@")[0])
        for n in range(1, 200):
            name = base if n == 1 else (base[:27] + str(n))
            full = name + DOMAIN
            if not conn.execute("SELECT 1 FROM accounts WHERE username_lower=%s", (full.lower(),)).fetchone():
                return full
        raise ApiError(409, "name_taken", "Could not make a username for this email. Please try again.")

    SURVEY_SOURCES = {"youtube", "tiktok", "facebook", "instagram", "search", "friend", "other"}
    SURVEY_PROBLEMS = {"free_beds", "double_booking", "checkouts", "agents_asking", "paper_records", "head_office", "other"}

    def _clean_survey(self, survey):
        """Only known choices and short text are kept; anything else is dropped (the survey is optional)."""
        if not isinstance(survey, dict):
            return None
        txt = lambda v: str(v or "").strip()[:200]
        src = txt(survey.get("source")).lower()
        probs = survey.get("problems") if isinstance(survey.get("problems"), list) else []
        probs = [p for p in dict.fromkeys(str(x).lower() for x in probs) if p in self.SURVEY_PROBLEMS][:7]
        if src not in self.SURVEY_SOURCES and not probs:
            return None
        return {"source": src if src in self.SURVEY_SOURCES else "", "source_other": txt(survey.get("sourceOther")),
                "problems": json.dumps(probs), "problem_other": txt(survey.get("problemOther"))}

    def register(self, ip, username, password, email=None, survey=None):
        self.limit_other.check(("reg", ip))
        email = (email or "").strip()
        if not str(username or "").strip() and is_email(email):
            with self.pool.connection() as conn:          # front page: the email is the key, the username is made for you
                username = self._free_name(conn, email)
        _name, full = clean_username(username)
        check_password(password)
        if email:
            if not _EMAIL_RE.match(email) or email.lower().endswith(DOMAIN):
                raise ApiError(400, "bad_email", "Enter a valid email address, or leave it empty.")
        uid = "local_" + new_id()
        stored_email = email or f"{uid}@local.invalid"        # placeholder keeps the column unique
        with self.pool.connection() as conn:
            with conn.transaction():
                cur = conn.cursor()
                if cur.execute("SELECT 1 FROM accounts WHERE username_lower=%s", (full.lower(),)).fetchone():
                    raise ApiError(409, "name_taken", "This name was taken. Please choose another.")
                try:
                    cur.execute(
                        "INSERT INTO accounts (user_id, username, username_lower, original_email, original_email_lower, "
                        "verified_via) VALUES (%s,%s,%s,%s,%s,'local')",
                        (uid, full, full.lower(), stored_email, stored_email.lower()))
                except sqlite3.IntegrityError as e:
                    if "username_lower" in str(e):
                        raise ApiError(409, "name_taken", "This name was taken. Please choose another.") from e
                    raise ApiError(409, "email_has_account", "That email already has an account here.") from e
                cur.execute("INSERT INTO local_credentials (user_id, password_hash) VALUES (%s,%s)",
                            (uid, hash_password(password)))
                sv = self._clean_survey(survey)
                if sv:
                    cur.execute("INSERT INTO signup_survey (user_id, source, source_other, problems, problem_other) "
                                "VALUES (%s,%s,%s,%s,%s)", (uid, sv["source"], sv["source_other"], sv["problems"], sv["problem_other"]))
        return {"username": full}

    def _name_for_email(self, email):
        with self.pool.connection() as conn:
            row = conn.execute("SELECT username FROM accounts WHERE original_email_lower=%s",
                               (str(email).strip().lower(),)).fetchone()
        return row["username"] if row else None

    def login(self, ip, username, password):
        if self.easy:
            return self._easy_login(username, password)
        if is_email(username):                            # sign in with the email the account was created with
            self.limit_login.check(("login", ip, str(username).strip().lower()))
            username = self._name_for_email(username) or ""
            if not username:
                verify_password(str(password or ""), _DUMMY)
                raise ApiError(401, "bad_login", "The email or password is incorrect.")
        try:
            _name, full = clean_username(username)
        except ApiError:
            full = ""
        self.limit_login.check(("login", ip, full))
        if not isinstance(password, str) or not full:
            raise ApiError(401, "bad_login", "The username or password is incorrect.")
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT a.user_id, a.username, c.password_hash, c.token_version FROM accounts a "
                "JOIN local_credentials c ON c.user_id=a.user_id WHERE a.username_lower=%s", (full.lower(),)).fetchone()
        ok = verify_password(password, row["password_hash"] if row else _DUMMY)
        if not row or not ok:
            log.warning("local login failed for %r: %s", full, "no such account" if not row else "wrong password")
            raise ApiError(401, "bad_login", "The username or password is incorrect.")
        token, exp = self.issue(row["user_id"], row["username"], row["token_version"])
        return {"token": token, "uid": row["user_id"], "username": row["username"], "expiresAt": exp}

    def _easy_login(self, username, password):
        """Any username and any password signs in. A new name gets a new (empty) account; an existing
        name opens that account without checking the password. Only ever used in local test mode.
        An email opens the account made with that email, or makes one (the email is kept as the key)."""
        email = None
        if is_email(username):
            email = str(username).strip()
            found = self._name_for_email(email)
            if found:
                username, email = found, None
            else:
                with self.pool.connection() as conn:
                    username = self._free_name(conn, email)
        _name, full = easy_name(username)
        password = password if isinstance(password, str) else ""
        with self.pool.connection() as conn:
            sql = ("SELECT a.user_id, a.username, c.token_version FROM accounts a "
                   "JOIN local_credentials c ON c.user_id=a.user_id WHERE a.username_lower=%s")
            row = conn.execute(sql, (full.lower(),)).fetchone()
            if not row:
                uid = "local_" + new_id()
                placeholder = email or f"{uid}@local.invalid"
                try:
                    with conn.transaction():
                        conn.execute("INSERT INTO accounts (user_id, username, username_lower, original_email, "
                                     "original_email_lower, verified_via) VALUES (%s,%s,%s,%s,%s,'local')",
                                     (uid, full, full.lower(), placeholder, placeholder))
                        conn.execute("INSERT INTO local_credentials (user_id, password_hash) VALUES (%s,%s)",
                                     (uid, hash_password(password)))
                    log.info("easy login: created account %r", full)
                except sqlite3.IntegrityError:            # created at the same moment by another request
                    pass
                row = conn.execute(sql, (full.lower(),)).fetchone()
        token, exp = self.issue(row["user_id"], row["username"], row["token_version"])
        return {"token": token, "uid": row["user_id"], "username": row["username"], "expiresAt": exp}

    def change_password(self, ip, username, current, new):
        """Identity is proven with the CURRENT password (no email can be sent in local mode)."""
        try:
            _name, full = clean_username(username)
        except ApiError:
            full = ""
        self.limit_login.check(("pw", ip, full))
        check_password(new)
        with self.pool.connection() as conn:
            with conn.transaction():
                cur = conn.cursor()
                row = cur.execute(
                    "SELECT a.user_id, a.username, c.password_hash FROM accounts a "
                    "JOIN local_credentials c ON c.user_id=a.user_id WHERE a.username_lower=%s", (full.lower(),)).fetchone()
                ok = verify_password(current if isinstance(current, str) else "", row["password_hash"] if row else _DUMMY)
                if not row or not ok:
                    raise ApiError(401, "bad_login", "The username or current password is incorrect.")
                cur.execute("UPDATE local_credentials SET password_hash=%s, token_version=token_version+1, updated_at=now() "
                            "WHERE user_id=%s", (hash_password(new), row["user_id"]))
                cur.execute("UPDATE accounts SET password_changed_at=now() WHERE user_id=%s", (row["user_id"],))
        return {"username": row["username"]}


SAMPLES = [("sample.one", "Sample1234"), ("sample.two", "Sample5678")]
SAMPLE_EMAILS = {"sample.one": "sample.one@example.com", "sample.two": "sample.two@example.com"}


def ensure_samples(auth):
    """Create the two public sample accounts if they are missing (local test mode only). Existing
    accounts are never touched. Returns the names that were created."""
    made = []
    for name, pw in SAMPLES:
        email = SAMPLE_EMAILS.get(name)
        try:
            auth.register("127.0.0.1", name, pw, email)
            made.append(name)
        except ApiError as e:
            if e.code != "name_taken":
                raise
            # older sample accounts had no email: give them their sample email so they can sign in with it
            with auth.pool.connection() as conn:
                with conn.transaction():
                    conn.execute("UPDATE accounts SET original_email=%s, original_email_lower=%s "
                                 "WHERE username_lower=%s AND original_email_lower LIKE %s AND NOT EXISTS "
                                 "(SELECT 1 FROM accounts b WHERE b.original_email_lower=%s)",
                                 (email, email, name + DOMAIN, "%@local.invalid", email))
    return made
