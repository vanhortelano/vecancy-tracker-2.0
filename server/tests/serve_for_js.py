"""Test-only: starts the real app on port 8099 with a FAKE Firebase (no network). Never used in production."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import conftest
from app import create_app
import psycopg

with psycopg.connect(conftest.DB, autocommit=True) as c:
    tables = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")]
    c.execute("TRUNCATE " + ",".join(tables) + " CASCADE")
fb = conftest.FakeFirebase()
app = create_app(database_url=conftest.DB, verifier=fb.verify, fb=fb, brain_factory=conftest.FakeBrain)
app.run(host="127.0.0.1", port=8099, threaded=True)
