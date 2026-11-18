"""LOCAL TEST DATABASE: SQLite behind the same small interface the server uses for PostgreSQL.

Why: some PCs block the PostgreSQL driver, and SQLite ships inside Python. The schema is built from
the same schema.sql, so the tables are identical in meaning. Production uses PostgreSQL; this
exists so the whole app can be tried on one computer. The file lives in local-data/ and is never
served over the web.

What it translates, per statement: %s placeholders, `= ANY(%s)` lists, FOR UPDATE (SQLite
serializes writers instead), COLLATE "C", now(), transaction_timestamp(). Stored values: JSONB as
JSON text, TIMESTAMPTZ as UTC ISO text, BOOLEAN as 0/1; they come back as the same Python types
PostgreSQL returns.
"""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dbcompat import Jsonb

NOW_SQL = "(strftime('%Y-%m-%d %H:%M:%f','now') || '+00:00')"
SCHEMA = Path(__file__).with_name("schema.sql")

# Local-only: password hashes for the temporary no-Firebase login. Never created on PostgreSQL.
LOCAL_EXTRA = """
CREATE TABLE IF NOT EXISTS local_credentials (
  user_id        TEXT PRIMARY KEY REFERENCES accounts(user_id) ON DELETE CASCADE,
  password_hash  TEXT NOT NULL,
  token_version  INTEGER NOT NULL DEFAULT 1,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now') || '+00:00')
);
-- Local-only: the short "Get started" survey (how they found us, what is hard for them), saved with the new account.
CREATE TABLE IF NOT EXISTS signup_survey (
  user_id        TEXT PRIMARY KEY REFERENCES accounts(user_id) ON DELETE CASCADE,
  source         TEXT NOT NULL DEFAULT '',
  source_other   TEXT NOT NULL DEFAULT '',
  problems       TEXT NOT NULL DEFAULT '[]',
  problem_other  TEXT NOT NULL DEFAULT '',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now') || '+00:00')
);
"""


def _adapt_dt(d):
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat(sep=" ", timespec="milliseconds")


sqlite3.register_adapter(datetime, _adapt_dt)
sqlite3.register_adapter(Jsonb, lambda j: json.dumps(j.obj, ensure_ascii=False, separators=(",", ":")))
sqlite3.register_converter("TIMESTAMPTZ", lambda b: datetime.fromisoformat(b.decode()))
sqlite3.register_converter("JSONB", lambda b: json.loads(b))
sqlite3.register_converter("BOOLEAN", lambda b: bool(int(b)))


def sqlite_schema(pg_sql):
    """schema.sql (PostgreSQL) -> the same tables for SQLite."""
    s = pg_sql.replace("DEFAULT now()", "DEFAULT " + NOW_SQL)
    s = re.sub(r"\bJSONB\b", "JSONB TEXT", s)               # TEXT affinity keeps JSON text exact
    s = re.sub(r"\bBIGSERIAL PRIMARY KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", s)
    return s


_ANY = re.compile(r"=\s*ANY\(\s*$")


def translate(sql, params):
    sql = sql.replace(" FOR UPDATE", "").replace('COLLATE "C"', "COLLATE BINARY")
    sql = sql.replace("transaction_timestamp()", NOW_SQL).replace("now()", NOW_SQL)
    parts = sql.split("%s")
    if len(parts) == 1:
        return sql, tuple(params or ())
    params = list(params or ())
    if len(parts) != len(params) + 1:
        raise ValueError("placeholder count does not match parameters")
    out, flat = parts[0], []
    for i, p in enumerate(params):
        if isinstance(p, (list, tuple)) and _ANY.search(out):
            out = _ANY.sub("IN (", out) + (",".join("?" * len(p)) if p else "NULL")
            flat.extend(p)
        else:
            out += "?"
            flat.append(p)
        out += parts[i + 1]
    return out, tuple(flat)


class LocalCursor:
    def __init__(self, conn):
        self._cur = conn.raw.cursor()

    def execute(self, sql, params=()):
        sql, params = translate(sql, params)
        self._cur.execute(sql, params)
        return self

    def _row(self, row):
        if row is None:
            return None
        return {d[0]: v for d, v in zip(self._cur.description, row)}

    def fetchone(self):
        return self._row(self._cur.fetchone())

    def fetchall(self):
        return [self._row(r) for r in self._cur.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def rowcount(self):
        return self._cur.rowcount


class LocalConn:
    def __init__(self, path):
        self.raw = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES, isolation_level=None,
                                   timeout=30, check_same_thread=False)
        self.raw.execute("PRAGMA foreign_keys=ON")
        self.depth = 0

    def cursor(self):
        return LocalCursor(self)

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    @contextmanager
    def transaction(self):
        """BEGIN IMMEDIATE: one writer at a time, like the row locks PostgreSQL takes."""
        if self.depth:
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1
            return
        self.raw.execute("BEGIN IMMEDIATE")
        self.depth = 1
        try:
            yield
        except BaseException:
            self.raw.execute("ROLLBACK")
            raise
        else:
            self.raw.execute("COMMIT")
        finally:
            self.depth = 0

    def close(self):
        self.raw.close()


class LocalPool:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        try:
            raw.execute("PRAGMA journal_mode=WAL")
            raw.execute("PRAGMA synchronous=NORMAL")
            raw.executescript(sqlite_schema(SCHEMA.read_text(encoding="utf-8")) + LOCAL_EXTRA)
        finally:
            raw.close()

    @contextmanager
    def connection(self):
        conn = LocalConn(self.path)
        try:
            yield conn
        finally:
            conn.close()
