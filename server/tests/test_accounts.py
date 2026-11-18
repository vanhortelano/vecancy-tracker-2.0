from conftest import api, mkuser, register, tok


def test_create_account_and_login_session(env_pg):
    c, fb = env_pg
    s, d = register(c, "u1", "Maria.Cruz")
    assert s == 200 and d["username"] == "maria.cruz@vecancy.tracker"
    assert fb.users["u1"]["email"] == "maria.cruz@vecancy.tracker"      # Firebase holds only the login
    assert "u1" in fb.revoked                                           # proof session ended
    s, d = api(c, "/api/session", tok("u1", "maria.cruz@vecancy.tracker"), method="get")
    assert s == 200 and d["username"] == "maria.cruz@vecancy.tracker" and d["roles"]["superAdmin"] is False
    assert "original" not in str(d).lower() and "gmail" not in str(d)  # original email never returned here


def test_identical_name_is_rejected_with_warning(env_pg):
    c, _ = env_pg
    assert register(c, "u1", "joy")[0] == 200
    for variant in ("joy", "JOY", " Joy ", "joy@vecancy.tracker", "JOY@VECANCY.TRACKER"):
        s, d = register(c, "u2", variant, email="other@gmail.com")
        assert s == 409 and d["error"] == "name_taken", variant
        assert d["message"] == "This name was taken. Please choose another."
    # u2 can still register with a free name afterwards (nothing half-created)
    assert register(c, "u2", "joy2", email="other@gmail.com")[0] == 200


def test_name_taken_in_firebase_creates_nothing(env_pg):
    c, fb = env_pg
    fb.taken_emails.add("ghost@vecancy.tracker")
    s, d = register(c, "u1", "ghost")
    assert s == 409 and d["error"] == "name_taken"
    s, d = api(c, "/api/session", tok("u1"), method="get")
    assert s == 403                                                      # no account row left behind


def test_one_account_per_email_and_check_name_hint(env_pg):
    c, _ = env_pg
    assert register(c, "u1", "first", email="same@gmail.com")[0] == 200
    s, d = register(c, "u9", "second", email="SAME@gmail.com")
    assert s == 409 and d["error"] == "email_has_account"
    s, d = api(c, "/api/account/check-name", tok("u3"), {"username": "FIRST"})
    assert d["available"] is False
    s, d = api(c, "/api/account/check-name", tok("u3"), {"username": "fresh-name"})
    assert d["available"] is True


def test_registration_needs_verified_recent_identity_and_good_input(env_pg):
    c, _ = env_pg
    s, d = api(c, "/api/account/register", tok("u1", verified=False), {"username": "abc", "password": "password1"})
    assert s == 403 and d["error"] == "email_not_verified"
    s, d = api(c, "/api/account/register", tok("u1", age=4000), {"username": "abc", "password": "password1"})
    assert s == 401 and d["error"] == "reauth"
    s, d = api(c, "/api/account/register", tok("u1", "x@vecancy.tracker"), {"username": "abc", "password": "password1"})
    assert s == 400 and d["error"] == "wrong_identity"
    assert register(c, "u1", "ab")[1]["error"] == "bad_username"
    assert register(c, "u1", "bad name!")[1]["error"] == "bad_username"
    assert register(c, "u1", "okname", pw="short")[1]["error"] == "weak_password"
    assert api(c, "/api/account/register", None, {"username": "abc", "password": "password1"})[0] == 401
    assert api(c, "/api/account/register", "bad|x|1|g|0", {"username": "abc", "password": "password1"})[0] == 401


def test_update_account_shows_username_and_changes_password(env_pg):
    c, fb = env_pg
    register(c, "u1", "joy", email="joy@gmail.com")
    proof = tok("temp-proof", "joy@gmail.com")                          # fresh Google/email verification
    s, d = api(c, "/api/account/lookup", proof, {})
    assert s == 200 and d == {"username": "joy@vecancy.tracker"}        # username shown, unchanged
    s, d = api(c, "/api/account/password", proof, {"newPassword": "brand-new-pass"})
    assert s == 200 and fb.users["u1"]["password"] == "brand-new-pass"
    assert fb.users["u1"]["email"] == "joy@vecancy.tracker"             # username untouched
    assert "temp-proof" in fb.deleted
    # someone else's verified email cannot change joy's password
    s, d = api(c, "/api/account/password", tok("evil", "evil@gmail.com"), {"newPassword": "hacked-pass1"})
    assert s == 404 and fb.users["u1"]["password"] == "brand-new-pass"
    # unverified / stale proof is refused, and weak passwords too
    assert api(c, "/api/account/password", tok("t", "joy@gmail.com", verified=False), {"newPassword": "longenough1"})[0] == 403
    assert api(c, "/api/account/password", tok("t", "joy@gmail.com", age=9999), {"newPassword": "longenough1"})[0] == 401
    assert api(c, "/api/account/password", proof, {"newPassword": "x"})[1]["error"] == "weak_password"


def test_data_api_requires_a_registered_account(env_pg):
    c, _ = env_pg
    s, d = api(c, "/api/get", tok("legacy-user"), {"path": ["users", "legacy-user", "rooms", "a"]})
    assert s == 403 and d["error"] == "account_required"
    assert api(c, "/api/get", None, {"path": ["users", "x", "rooms", "a"]})[0] == 401


def test_rate_limit_on_account_endpoints(env_pg):
    c, _ = env_pg
    codes = [api(c, "/api/account/lookup", tok("p%d" % i, "n%d@gmail.com" % i), {})[0] for i in range(14)]
    assert 429 in codes
