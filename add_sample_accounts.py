"""Creates two SAMPLE accounts for LOCAL TEST MODE so you can sign in right away.

    python add_sample_accounts.py

  sample.one@example.com   password: Sample1234   (username sample.one@vecancy.tracker)
  sample.two@example.com   password: Sample5678   (username sample.two@vecancy.tracker)

The passwords are public (they are written here), so use these only on your own computer for trying
the app. Each account has its own private workspace; they cannot see each other's data.
Safe to run again: accounts that already exist are skipped."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "server"))

from localauth import LocalAuth, SAMPLE_EMAILS, SAMPLES, ensure_samples, load_secret  # noqa: E402
from localdb import LocalPool  # noqa: E402

if __name__ == "__main__":
    data = HERE / "local-data"
    made = ensure_samples(LocalAuth(LocalPool(data / "vacancy.db"), load_secret(data)))
    for name, pw in SAMPLES:
        print("%s  %s   password: %s" % ("created" if name in made else "exists ", SAMPLE_EMAILS[name], pw))
    print("\n(run_local.py now creates these automatically every time it starts.)")
