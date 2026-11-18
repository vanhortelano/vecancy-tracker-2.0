import os
import sys
import time
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import accounts  # noqa: E402
from app import create_app  # noqa: E402

DB = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@/vt?host=/tmp/pgtest&port=5544")


class FakeFirebase:
    """Stands in for Firebase Admin in tests (no network)."""
    EmailExists = accounts.FirebaseOps.EmailExists

    def __init__(self):
        self.users, self.deleted, self.revoked = {}, [], []
        self.taken_emails = set()          # emails that already exist in Firebase Auth

    def verify(self, token):
        # token format  "uid|email|verified|provider|age_seconds"
        uid, email, verified, provider, age = token.split("|")
        if uid == "bad":
            raise ValueError("invalid token")
        return {"uid": uid, "email": email or None, "email_verified": verified == "1",
                "auth_time": int(time.time()) - int(age), "name": uid.title(),
                "firebase": {"sign_in_provider": provider}}

    def finalize_account(self, uid, email, password, display_name):
        if email in self.taken_emails:
            raise self.EmailExists()
        self.users[uid] = {"email": email, "password": password}
        self.revoked.append(uid)

    def set_password(self, uid, password):
        self.users[uid]["password"] = password

    def delete_user(self, uid):
        self.deleted.append(uid)


def tok(uid, email=None, verified=True, provider="google.com", age=5):
    return f"{uid}|{email if email is not None else uid + '@gmail.com'}|{1 if verified else 0}|{provider}|{age}"


class FakeBrain:
    def answer(self, message):
        m = message.lower()
        if "vacant" in m:
            return "live_vacant", 0.9, "x"
        if "weather" in m:
            return "offtopic", 0.9, "I can only help with the tracker."
        return "how_to", 0.8, "Press + Add room."


@pytest.fixture(scope="session")
def schema():
    with psycopg.connect(DB, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        c.execute((Path(__file__).resolve().parent.parent / "schema.sql").read_text())


@pytest.fixture()
def env_pg(schema):
    """PostgreSQL only (account flows that use Firebase-specific database errors, and the importer)."""
    with psycopg.connect(DB, autocommit=True) as c:
        tables = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")]
        c.execute("TRUNCATE " + ",".join(tables) + " CASCADE")
    fb = FakeFirebase()
    app = create_app(database_url=DB, verifier=fb.verify, fb=fb, brain_factory=FakeBrain)
    yield app.test_client(), fb
    app.extensions["pool"].pool.close()


@pytest.fixture(params=["pg", "sqlite"])
def env(request, schema, tmp_path):
    """Data, sharing and assistant tests run against BOTH databases: PostgreSQL (production) and
    SQLite (the local test mode), so the two cannot drift apart."""
    fb = FakeFirebase()
    if request.param == "pg":
        with psycopg.connect(DB, autocommit=True) as c:
            tables = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")]
            c.execute("TRUNCATE " + ",".join(tables) + " CASCADE")
        app = create_app(database_url=DB, verifier=fb.verify, fb=fb, brain_factory=FakeBrain)
    else:
        from localdb import LocalPool
        app = create_app(pool=LocalPool(tmp_path / "t.db"), verifier=fb.verify, fb=fb, brain_factory=FakeBrain)
    yield app.test_client(), fb
    if request.param == "pg":
        app.extensions["pool"].pool.close()


def scalar(client, sql):
    """First column of the first row, through the app's own pool (works on either database)."""
    with client.application.extensions["pool"].connection() as conn:
        return list(conn.execute(sql).fetchone().values())[0]


def api(client, path, token=None, json=None, method="post"):
    h = {"Authorization": "Bearer " + token} if token else {}
    r = getattr(client, method)(path, headers=h, json=json)
    return r.status_code, r.get_json()


def register(client, uid, username, pw="password1", email=None):
    return api(client, "/api/account/register", tok(uid, email), {"username": username, "password": pw})


def mkuser(client, uid, username=None):
    username = username or "user-" + uid.lower()
    s, d = register(client, uid, username)
    assert s == 200, d
    return tok(uid, f"{username}@vecancy.tracker")


def commit(client, token, writes, reads=None):
    return api(client, "/api/commit", token, {"writes": writes, "reads": reads or []})


def ts(ms):
    return {"__ts": ms}


SV = {"__sv": 1}
