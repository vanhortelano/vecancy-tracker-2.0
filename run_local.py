"""Run the whole app on THIS computer, for trying it out. No Firebase, no PostgreSQL, no sign-up
anywhere: data goes in a SQLite file (local-data/vacancy.db) and the login is a temporary
username + password kept on this computer.

    python run_local.py          then open  http://127.0.0.1:8080

Needs only:  python -m pip install flask      (scikit-learn is optional; without it the
assistant uses a built-in backup matcher that needs nothing)
The page is only reachable from this computer. For real use, run server/app.py with PostgreSQL
and Firebase sign-in (see SETUP-GUIDE.md)."""
import logging
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "server"))

try:
    import flask  # noqa: F401
except ImportError:
    sys.exit("Flask is not installed. Run:  python -m pip install flask")

from app import create_app  # noqa: E402
from localauth import SAMPLE_EMAILS, SAMPLES, LocalAuth, ensure_samples, load_secret  # noqa: E402
from localdb import LocalPool  # noqa: E402

def check_port(port):
    """Preview pages (VS Code Live Server) always talk to 127.0.0.1:8080. If something already uses
    that port, say exactly what it is instead of quietly starting somewhere else."""
    # "Is something listening there?" (a test bind would also fail for a few seconds after a
    # normal restart, while the old connections close, and wrongly refuse to start)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex(("127.0.0.1", port)) != 0:
            return port
    other = "another program"
    try:
        import json
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port, timeout=3) as r:
            info = json.loads(r.read().decode())
        if info.get("app") == "vacancy-tracker":
            from app import APP_VERSION
            if info.get("version") == APP_VERSION and info.get("local"):
                sys.exit("\n  The app is ALREADY RUNNING on http://127.0.0.1:%d - just use it (or close that window first).\n" % port)
            other = "an OLDER copy of this app"
    except SystemExit:
        raise
    except Exception:
        pass
    sys.exit("\n  Port %d is used by %s.\n  Close the other black window / VS Code terminal that runs the app,\n"
             "  or restart the computer, then start this again.\n" % (port, other))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = check_port(int(os.environ.get("PORT", "8080")))
    easy = os.environ.get("VT_EASY_LOGIN", "1") != "0"
    data = HERE / "local-data"
    ensure_samples(LocalAuth(LocalPool(data / "vacancy.db"), load_secret(data)))   # sample logins always exist
    marker = data / ".sample-rooms-added"
    if not marker.exists():                       # once: 24+ sample rooms and tenants for sample.one
        try:
            from sample_data import seed_account
            added = seed_account(LocalPool(data / "vacancy.db"))
            marker.write_text("added %d rooms\n" % added)
            if added:
                print("  Added %d sample rooms with tenants to sample.one." % added)
        except Exception as error:               # never block the app over sample data
            print("  (Sample rooms were not added: %s)" % error)
    print("\n  Vacancy Tracker (LOCAL TEST MODE)\n  Open  http://127.0.0.1:%d  in your browser.\n"
          "  Data file: %s\n\n  Sign in with:\n%s\n  Press Ctrl+C to stop.\n"
          % (port, data / "vacancy.db",
             "".join("    %s   password: %s\n" % (SAMPLE_EMAILS.get(n, n), p) for n, p in SAMPLES)))
    if easy:
        print("  EASY LOGIN is ON: any email (or username) and any password signs in (a new email gets a new account).\n"
              "  To require real passwords again, start with  VT_EASY_LOGIN=0\n")
    app = create_app(local_dir=data, easy_login=easy)
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.5, webbrowser.open, args=("http://127.0.0.1:%d" % port,)).start()
    app.run(host="127.0.0.1", port=port, threaded=True)
