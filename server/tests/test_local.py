"""LOCAL TEST MODE: SQLite file + temporary username/password login (no Firebase, no PostgreSQL)."""
import json
import threading

import pytest
from conftest import FakeBrain, api, commit, scalar

import brain_lite
from app import create_app


@pytest.fixture()
def lc(tmp_path):
    return create_app(local_dir=tmp_path, brain_factory=FakeBrain).test_client()


def signup(c, name, pw="password1", email=None):
    return api(c, "/api/local/register", None, {"username": name, "password": pw, "email": email})


def login(c, name, pw="password1"):
    return api(c, "/api/local/login", None, {"username": name, "password": pw})


def user(c, name):
    assert signup(c, name)[0] == 200
    s, d = login(c, name)
    assert s == 200, d
    return d["token"], d["uid"]


ROOM = {"room": "101", "capacity": 2, "beds": [{"slot": "A", "tenant": None}, {"slot": "B", "tenant": "Ann", "bedEnd": "2099-01-01"}]}


def test_mode_script_and_files_not_served(lc):
    assert b"VT_LOCAL_MODE=true" in lc.get("/mode.js").data
    user(lc, "maria")
    for p in ("/local-data/vacancy.db", "/local-data/secret.key", "/vacancy.db", "/server/app.py", "/legacy/main.py"):
        assert lc.get(p).status_code == 404
    assert lc.get("/seed-data.js").status_code == 200        # local only: powers "Import my existing rooms" on this computer


def test_create_account_gives_unique_username_and_rejects_identical_name(lc):
    s, d = signup(lc, "Maria.Cruz")
    assert s == 200 and d["username"] == "maria.cruz@vecancy.tracker"
    for variant in ("maria.cruz", "MARIA.CRUZ", "Maria.Cruz@vecancy.tracker", " maria.cruz "):
        s, d = signup(lc, variant)
        assert s == 409 and d["error"] == "name_taken" and "was taken" in d["message"], variant
    assert scalar(lc, "select count(*) from accounts") == 1
    assert api(lc, "/api/local/check-name", None, {"username": "maria.cruz"})[1]["available"] is False
    assert api(lc, "/api/local/check-name", None, {"username": "someone.else"})[1]["available"] is True


def test_input_rules_and_email_is_optional_and_never_returned(lc):
    assert signup(lc, "ab")[1]["error"] == "bad_username"
    assert signup(lc, "valid.name", pw="short")[1]["error"] == "weak_password"
    assert signup(lc, "valid.name", email="not-an-email")[1]["error"] == "bad_email"
    assert signup(lc, "valid.name", email="Real@Example.com")[0] == 200
    assert signup(lc, "other.name", email="real@example.com")[1]["error"] == "email_has_account"
    t, _ = user(lc, "third.person")
    s, d = api(lc, "/api/session", t, method="get")
    assert s == 200 and d["username"] == "third.person@vecancy.tracker" and "example.com" not in str(d)


def test_passwords_are_hashed_and_login_errors_are_generic(lc):
    user(lc, "maria")
    h = scalar(lc, "select password_hash from local_credentials")
    assert h.startswith("pbkdf2$") and "password1" not in h
    a = login(lc, "maria", "wrong-password")
    b = login(lc, "nobody.here", "password1")
    assert a[0] == b[0] == 401 and a[1]["message"] == b[1]["message"]          # does not reveal which part was wrong
    assert login(lc, "maria@vecancy.tracker")[0] == 200


def test_rate_limit_stops_password_guessing(lc):
    user(lc, "maria")
    codes = [login(lc, "maria", "guess%d" % i)[0] for i in range(14)]      # (sign-up helper already used 1 of 10)
    assert codes[:9] == [401] * 9 and set(codes[9:]) == {429}
    assert login(lc, "maria")[0] == 429                                       # even the right password is paused


def test_tokens_cannot_be_forged_or_swapped(lc):
    ta, ua = user(lc, "alice")
    tb, ub = user(lc, "bobby")
    assert api(lc, "/api/session", None, method="get")[0] == 401
    assert api(lc, "/api/session", ta + "x", method="get")[0] == 401
    body, sig = ta.split(".")
    other_body = tb.split(".")[0]
    assert api(lc, "/api/session", other_body + "." + sig, method="get")[0] == 401     # signature of a different payload
    assert api(lc, "/api/session", "garbage", method="get")[0] == 401
    # a valid token only ever reaches its own user id, whatever the request says
    assert commit(lc, ta, [{"op": "set", "path": ["users", ua, "rooms", "r1"], "data": ROOM}])[0] == 200
    assert api(lc, "/api/get", tb, {"path": ["users", ua, "rooms", "r1"]})[0] == 403
    assert api(lc, "/api/query", tb, {"path": ["users", ua, "rooms"]})[0] == 403
    assert commit(lc, tb, [{"op": "set", "path": ["users", ua, "rooms", "evil"], "data": ROOM}])[0] == 403
    assert api(lc, "/api/get", ta, {"path": ["users", ua, "rooms", "r1"]})[1]["data"]["beds"][1]["tenant"] == "Ann"


def test_change_password_needs_current_password_and_ends_old_sessions(lc):
    t, uid = user(lc, "maria")
    s, d = api(lc, "/api/local/password", None, {"username": "maria", "currentPassword": "nope-nope", "newPassword": "newpass123"})
    assert s == 401
    assert api(lc, "/api/local/password", None, {"username": "maria", "currentPassword": "password1", "newPassword": "short"})[0] == 400
    s, d = api(lc, "/api/local/password", None, {"username": "maria", "currentPassword": "password1", "newPassword": "newpass123"})
    assert s == 200 and d["username"] == "maria@vecancy.tracker"               # the username never changes
    assert api(lc, "/api/session", t, method="get")[0] == 401                   # old session revoked
    assert login(lc, "maria", "password1")[0] == 401
    s, d = login(lc, "maria", "newpass123")
    assert s == 200 and d["uid"] == uid                                         # same internal user id


def test_firebase_account_routes_are_off_in_local_mode(lc):
    t, _ = user(lc, "maria")
    assert api(lc, "/api/account/register", t, {"username": "x", "password": "password1"})[0] in (400, 401, 403, 404)
    assert api(lc, "/api/account/password", t, {"newPassword": "password2"})[0] in (400, 401, 403, 404)
    assert scalar(lc, "select count(*) from accounts") == 1


def test_concurrent_read_modify_write_loses_nothing(lc):
    t, uid = user(lc, "counter")
    path = ["users", uid, "rooms", "ctr"]
    assert commit(lc, t, [{"op": "set", "path": path, "data": {"room": "ctr", "capacity": 0}}])[0] == 200
    errors = []

    def bump():
        try:
            for _ in range(6):
                for _attempt in range(40):
                    d = api(lc, "/api/get", t, {"path": path})[1]
                    s, _ = commit(lc, t, [{"op": "update", "path": path, "data": {"capacity": d["data"]["capacity"] + 1}}],
                                  reads=[{"path": path, "v": d["v"]}])
                    if s == 200:
                        break
                    assert s == 409
                else:
                    errors.append("gave up")
        except Exception as e:                      # surfaced below
            errors.append(repr(e))

    threads = [threading.Thread(target=bump) for _ in range(6)]
    [x.start() for x in threads]
    [x.join() for x in threads]
    assert not errors, errors
    assert api(lc, "/api/get", t, {"path": path})[1]["data"]["capacity"] == 36


def test_assistant_works_with_the_backup_matcher_and_stores_history_in_sql(tmp_path):
    c = create_app(local_dir=tmp_path, brain_factory=brain_lite.Brain).test_client()
    t, uid = user(c, "maria")
    commit(c, t, [{"op": "set", "path": ["users", uid, "rooms", "r1"], "data": ROOM}])
    s, d = api(c, "/api/assistant", t, {"question": "how many vacant beds do I have?"})
    assert s == 200 and d["intent"] == "live_vacant" and "1 vacant" in d["response"]
    cid = d["conversationId"]
    s, d2 = api(c, "/api/assistant", t, {"question": "how do I add a room", "conversationId": cid})
    assert d2["intent"] == "add_room" and d2["conversationId"] == cid
    assert api(c, "/api/assistant", t, {"question": "what is the capital of France"})[1]["scope"] == "unrelated"
    assert api(c, "/api/assistant", t, {"question": "asdf qwerty zxcv"})[1]["scope"] == "uncertain"
    msgs = api(c, "/api/assistant/history", t, {"conversationId": cid})[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert scalar(c, "select count(*) from ai_messages") == 8
    assert scalar(c, "select count(*) from ai_insights where kind='live_vacant'") == 1
    t2, _ = user(c, "other.one")
    assert api(c, "/api/assistant/history", t2, {"conversationId": cid})[1]["messages"] == []
    assert api(c, "/api/assistant", None, {"question": "hi"})[0] == 401


def test_backup_matcher_agrees_with_the_trained_model_on_its_own_examples():
    import json
    from pathlib import Path
    data = json.loads((Path(__file__).resolve().parents[2] / "intents.json").read_text(encoding="utf-8"))
    b = brain_lite.Brain()
    wrong = [(p, i["tag"]) for i in data["intents"] for p in i["patterns"] if b.answer(p)[0] != i["tag"]]
    assert not wrong, wrong[:5]


def test_scripts_and_styles_get_correct_types_even_if_windows_maps_js_to_text_plain(lc, monkeypatch):
    import mimetypes
    mimetypes.init()
    monkeypatch.setitem(mimetypes.types_map, ".js", "text/plain")        # what a misconfigured Windows registry does
    monkeypatch.setitem(mimetypes.types_map, ".css", "text/plain")
    for path, want in (("/auth-ui.js", "javascript"), ("/styles.css", "text/css"), ("/index.html", "text/html"), ("/", "text/html")):
        r = lc.get(path)
        assert r.status_code == 200 and want in r.headers["Content-Type"], (path, r.headers["Content-Type"])


def test_files_inside_folders_are_served(lc):
    for path in ("/js/proof.js", "/js/02-auth-boot.js", "/js/99-main.js"):
        r = lc.get(path)
        assert r.status_code == 200 and "javascript" in r.headers["Content-Type"], path


def test_sample_accounts_are_created_automatically_and_can_log_in(lc):
    from localauth import LocalAuth, ensure_samples, load_secret
    pool = lc.application.extensions["pool"]
    auth = LocalAuth(pool, b"x" * 32)
    assert sorted(ensure_samples(auth)) == ["sample.one", "sample.two"]
    assert ensure_samples(auth) == []                                  # second start changes nothing
    assert login(lc, "sample.one", "Sample1234")[0] == 200
    assert login(lc, "sample.two@vecancy.tracker", "Sample5678")[0] == 200
    assert login(lc, "sample.one", "Sample5678")[0] == 401


def test_preview_tools_on_another_local_port_can_use_the_local_server(lc):
    h = {"Origin": "http://127.0.0.1:5500", "Access-Control-Request-Method": "POST",
         "Access-Control-Request-Headers": "authorization, content-type"}
    r = lc.options("/api/local/login", headers=h)
    assert r.status_code == 200 and r.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5500"
    assert "Authorization" in r.headers["Access-Control-Allow-Headers"]
    r = lc.post("/api/local/login", headers={"Origin": "http://localhost:3000"}, json={"username": "x", "password": "y"})
    assert r.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
    for bad in ("https://evil.example", "null", "http://127.0.0.1.evil.example"):
        r = lc.post("/api/local/login", headers={"Origin": bad}, json={"username": "x", "password": "y"})
        assert "Access-Control-Allow-Origin" not in r.headers, bad


def test_easy_login_lets_any_name_and_password_in_but_only_when_switched_on(tmp_path):
    easy = create_app(local_dir=tmp_path / "e", brain_factory=FakeBrain, easy_login=True).test_client()
    assert b"VT_EASY_LOGIN=true" in easy.get("/mode.js").data
    s, d = login(easy, "Juan Cruz", "x")                       # brand-new name, any password
    assert s == 200 and d["username"] == "juan.cruz@vecancy.tracker"
    s, d2 = login(easy, "juan.cruz", "something else")         # same account, different password
    assert s == 200 and d2["uid"] == d["uid"]
    assert login(easy, "ab", "")[0] == 200                     # even very short names work
    assert api(easy, "/api/session", d2["token"], method="get")[0] == 200
    # the normal local mode still checks passwords
    strict = create_app(local_dir=tmp_path / "s", brain_factory=FakeBrain).test_client()
    assert b"VT_EASY_LOGIN=false" in strict.get("/mode.js").data
    assert login(strict, "juan.cruz", "x")[0] == 401


def test_sample_rooms_for_sample_one_are_added_once_and_never_overwrite(tmp_path):
    from localdb import LocalPool
    from localauth import LocalAuth, ensure_samples, load_secret
    from sample_data import seed_account
    from store import KINDS, list_docs
    pool = LocalPool(tmp_path / "v.db")
    ensure_samples(LocalAuth(pool, load_secret(tmp_path)))
    assert seed_account(pool) == 24
    assert seed_account(pool) == 0                       # already 24: nothing added, nothing changed
    with pool.connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM accounts WHERE username_lower='sample.one@vecancy.tracker'")
        uid = cur.fetchone()["user_id"]
        rooms = [d for _i, d, _v in list_docs(cur, KINDS["rooms"], [uid], limit=100)]
        tenants = sum(1 for r in rooms for b in r["beds"] if b.get("tenant"))
    assert len(rooms) == 24 and tenants >= 24


def test_front_page_signs_in_with_email_as_the_key(lc, tmp_path):
    from localauth import LocalAuth, ensure_samples
    pool = lc.application.extensions["pool"]
    ensure_samples(LocalAuth(pool, b"x" * 32))
    s, d = login(lc, "sample.one@example.com", "Sample1234")           # sample account by its email
    assert s == 200 and d["username"] == "sample.one@vecancy.tracker"
    assert login(lc, "SAMPLE.ONE@example.com ", "Sample1234")[0] == 200  # email is not case sensitive
    assert login(lc, "sample.one@example.com", "Sample5678")[0] == 401  # still checks the password
    assert login(lc, "nobody@example.com", "Sample1234")[0] == 401
    # create an account with only an email: a username is made for it, and it stays (never deleted)
    r = lc.post("/api/local/register", json={"username": "", "email": "Ana.Cruz@gmail.com", "password": "password1"})
    assert r.status_code == 200 and r.get_json()["username"] == "ana.cruz@vecancy.tracker"
    r = lc.post("/api/local/register", json={"username": "", "email": "ana.cruz@yahoo.com", "password": "password1"})
    assert r.get_json()["username"] == "ana.cruz2@vecancy.tracker"     # same name, different email: next free name
    r = lc.post("/api/local/register", json={"username": "", "email": "ana.cruz@gmail.com", "password": "password1"})
    assert r.status_code == 409                                         # one account per email
    s, d = login(lc, "ana.cruz@gmail.com", "password1")
    assert s == 200 and api(lc, "/api/session", d["token"], method="get")[0] == 200


def test_easy_login_with_an_email_keeps_one_account_per_email(tmp_path):
    easy = create_app(local_dir=tmp_path / "e", brain_factory=FakeBrain, easy_login=True).test_client()
    s, d = login(easy, "maria@example.com", "")
    assert s == 200 and d["username"] == "maria@vecancy.tracker"
    s, d2 = login(easy, "Maria@Example.com", "anything")
    assert d2["uid"] == d["uid"]
    s, d3 = login(easy, "maria@other.org", "")
    assert d3["uid"] != d["uid"] and d3["username"] == "maria2@vecancy.tracker"


def test_old_sample_accounts_get_their_sample_email(tmp_path):
    from localdb import LocalPool
    from localauth import LocalAuth, ensure_samples
    pool = LocalPool(tmp_path / "v.db")
    auth = LocalAuth(pool, b"x" * 32)
    auth.register("127.0.0.1", "sample.one", "Sample1234")               # made before samples had emails
    ensure_samples(auth)
    assert auth.login("127.0.0.1", "sample.one@example.com", "Sample1234")["username"] == "sample.one@vecancy.tracker"


def test_front_page_and_admin_page_are_served(lc):
    front = lc.get("/").data.decode()
    assert "login.html" in front and "firebasejs" not in front          # the front page never loads Firebase in its HTML
    login = lc.get("/login.html").data.decode()
    assert "login.js" in login and 'id="vSource"' in login and 'id="roles"' in login and "firebasejs" not in login   # survey, then log in with roles
    admin = lc.get("/admin.html").data.decode()
    assert 'id="authGate"' in admin and "roleScreen" not in admin and "entrance.js" in admin
    for page in ("viewer.html", "superadmin.html", "marketing.html"):
        assert "entrance.js" in lc.get("/" + page).data.decode(), page


def test_get_started_survey_is_saved_with_the_new_account(lc):
    r = lc.post("/api/local/register", json={"username": "", "email": "rosa@example.com", "password": "password1",
               "survey": {"source": "TikTok", "problems": ["free_beds", "checkouts", "bogus"], "problemOther": "x" * 500}})
    assert r.status_code == 200
    pool = lc.application.extensions["pool"]
    with pool.connection() as conn:
        row = conn.execute("SELECT s.* FROM signup_survey s JOIN accounts a ON a.user_id = s.user_id "
                           "WHERE a.original_email_lower = %s", ("rosa@example.com",)).fetchone()
    assert row["source"] == "tiktok" and json.loads(row["problems"]) == ["free_beds", "checkouts"]
    assert len(row["problem_other"]) == 200                              # short text only
    # the survey is optional
    assert lc.post("/api/local/register", json={"username": "", "email": "sam@example.com", "password": "password1"}).status_code == 200
