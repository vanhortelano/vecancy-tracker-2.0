from conftest import SV, api, commit, mkuser, ts


def room(n="101", **kw):
    return {"room": n, "type": "Room", "gender": "Mixed", "ac": True, "demographic": "Mixed",
            "tenancyMode": "Bedspace", "capacity": 2, "x": 20, "y": 20,
            "beds": [{"slot": "Bed 1", "tenant": "Ann", "start": "2026-01-01", "end": "2026-12-31",
                      "reservedFor": None, "residentType": "Student", "residentGender": "Female", "custom": {"a": 1}},
                     {"slot": "Bed 2", "tenant": None, "start": None, "end": None}], **kw}


def put(c, tkn, uid, rid, doc, op="set"):
    return commit(c, tkn, [{"op": op, "path": ["users", uid, "rooms", rid], "data": doc}])


def test_room_roundtrip_with_beds_and_unknown_fields(env):
    c, _ = env
    a = mkuser(c, "A")
    assert put(c, a, "A", "r1", room())[0] == 200
    s, d = api(c, "/api/get", a, {"path": ["users", "A", "rooms", "r1"]})
    assert s == 200 and d["exists"]
    r = d["data"]
    assert r["room"] == "101" and r["ac"] is True and r["capacity"] == 2
    assert [b["slot"] for b in r["beds"]] == ["Bed 1", "Bed 2"]
    assert r["beds"][0]["tenant"] == "Ann" and r["beds"][0]["custom"] == {"a": 1}   # unknown bed field kept
    s, d = api(c, "/api/query", a, {"path": ["users", "A", "rooms"], "orderBy": [["room", "asc"]]})
    assert [x["id"] for x in d["docs"]] == ["r1"]


def test_users_cannot_touch_each_others_records(env):
    c, _ = env
    a, b = mkuser(c, "A"), mkuser(c, "B")
    put(c, a, "A", "r1", room())
    # B tries every way to reach A's data, including by guessing A's id or username
    assert api(c, "/api/get", b, {"path": ["users", "A", "rooms", "r1"]})[0] == 403
    assert api(c, "/api/query", b, {"path": ["users", "A", "rooms"]})[0] == 403
    assert put(c, b, "A", "r1", room("HACK"))[0] == 403
    assert put(c, b, "A", "r2", room("NEW"))[0] == 403
    assert commit(c, b, [{"op": "delete", "path": ["users", "A", "rooms", "r1"]}])[0] == 403
    assert api(c, "/api/get", b, {"path": ["users", "a@vecancy.tracker", "rooms", "r1"]})[0] in (400, 403)   # username is not a key
    # and a failed attempt inside a batch undoes the legitimate writes beside it
    s, _ = commit(c, b, [{"op": "set", "path": ["users", "B", "rooms", "ok"], "data": room("B1")},
                         {"op": "set", "path": ["users", "A", "rooms", "bad"], "data": room("X")}])
    assert s == 403
    assert api(c, "/api/get", b, {"path": ["users", "B", "rooms", "ok"]})[1]["exists"] is False
    s, d = api(c, "/api/get", a, {"path": ["users", "A", "rooms", "r1"]})
    assert d["data"]["room"] == "101"


def test_owner_is_never_taken_from_the_request(env):
    c, _ = env
    a, b = mkuser(c, "A"), mkuser(c, "B")
    # even a user-id smuggled inside the document body cannot move data to another account
    put(c, a, "A", "r1", {**room(), "owner_uid": "B", "ownerUid": "B"})
    assert api(c, "/api/query", b, {"path": ["users", "B", "rooms"]})[1]["docs"] == []
    assert len(api(c, "/api/query", a, {"path": ["users", "A", "rooms"]})[1]["docs"]) == 1


def test_stale_transaction_is_aborted_not_overwritten(env):
    c, _ = env
    a = mkuser(c, "A")
    put(c, a, "A", "r1", room())
    v = api(c, "/api/get", a, {"path": ["users", "A", "rooms", "r1"]})[1]["v"]
    assert commit(c, a, [{"op": "update", "path": ["users", "A", "rooms", "r1"], "data": {"room": "202"}}],
                  reads=[{"path": ["users", "A", "rooms", "r1"], "v": v}])[0] == 200
    s, d = commit(c, a, [{"op": "update", "path": ["users", "A", "rooms", "r1"], "data": {"room": "303"}}],
                  reads=[{"path": ["users", "A", "rooms", "r1"], "v": v}])      # saw the old version
    assert s == 409 and d["error"] == "aborted"
    assert api(c, "/api/get", a, {"path": ["users", "A", "rooms", "r1"]})[1]["data"]["room"] == "202"


def test_update_merges_set_replaces_and_beds_replace(env):
    c, _ = env
    a = mkuser(c, "A")
    put(c, a, "A", "r1", room())
    commit(c, a, [{"op": "update", "path": ["users", "A", "rooms", "r1"], "data": {"gender": "Female"}}])
    d = api(c, "/api/get", a, {"path": ["users", "A", "rooms", "r1"]})[1]["data"]
    assert d["gender"] == "Female" and d["room"] == "101" and len(d["beds"]) == 2   # merged
    commit(c, a, [{"op": "update", "path": ["users", "A", "rooms", "r1"],
                   "data": {"beds": [{"slot": "Bed 1", "tenant": "Zed"}], "capacity": 1}}])
    d = api(c, "/api/get", a, {"path": ["users", "A", "rooms", "r1"]})[1]["data"]
    assert [b["tenant"] for b in d["beds"]] == ["Zed"] and d["capacity"] == 1
    assert commit(c, a, [{"op": "update", "path": ["users", "A", "rooms", "nope"], "data": {"x": 1}}])[0] == 404


def test_history_timestamps_ordering_and_purge_query(env):
    c, _ = env
    a = mkuser(c, "A")
    import time
    now = int(time.time() * 1000)
    for i, (name, left, exp) in enumerate([("old", now - 5000, now - 1000), ("mid", now - 3000, now + 1000), ("new", now - 1000, now + 5000)]):
        commit(c, a, [{"op": "set", "path": ["users", "A", "tenant_history", "h%d" % i],
                       "data": {"tenant": name, "leftAt": ts(left), "expireAt": ts(exp), "start": "2026-01-01"}}])
    s, d = api(c, "/api/query", a, {"path": ["users", "A", "tenant_history"], "orderBy": [["leftAt", "desc"]], "limit": 2})
    assert [x["data"]["tenant"] for x in d["docs"]] == ["new", "mid"] and d["docs"][0]["data"]["leftAt"] == ts(now - 1000)
    s, d = api(c, "/api/query", a, {"path": ["users", "A", "tenant_history"], "where": [["expireAt", "<=", ts(now)]]})
    assert [x["data"]["tenant"] for x in d["docs"]] == ["old"]
    commit(c, a, [{"op": "set", "path": ["users", "A", "tenant_history", "sv"], "data": {"tenant": "t", "leftAt": SV}}])
    got = api(c, "/api/get", a, {"path": ["users", "A", "tenant_history", "sv"]})[1]["data"]["leftAt"]
    assert isinstance(got["__ts"], int) and got["__ts"] > now - 60_000                      # server stamped the time


def test_delete_room_removes_its_beds(env):
    from conftest import scalar
    c, _ = env
    a = mkuser(c, "A")
    put(c, a, "A", "r1", room())
    commit(c, a, [{"op": "delete", "path": ["users", "A", "rooms", "r1"]}])
    assert scalar(c, "select count(*) from beds") == 0


def test_bad_paths_and_queries_are_rejected_safely(env):
    c, _ = env
    a = mkuser(c, "A")
    for p in (["users", "A", "nope", "x"], ["users"], ["accounts", "A"], ["users", "A; DROP TABLE rooms", "rooms", "x"],
              ["users", "A", "rooms"], "users/A/rooms/x"):
        assert api(c, "/api/get", a, {"path": p})[0] in (400, 403), p
    assert api(c, "/api/query", a, {"path": ["users", "A", "rooms"], "where": [["room; DROP TABLE rooms", "==", "1"]]})[0] == 400
    assert api(c, "/api/query", a, {"path": ["users", "A", "rooms"], "orderBy": [["room", "sideways"]]})[0] == 400
    assert commit(c, a, [{"op": "set", "path": ["users", "A", "rooms", "x"], "data": {"capacity": "many"}}])[0] == 400
    assert api(c, "/api/query", a, {"path": ["users", "A", "rooms"]})[0] == 200        # table still there
    big = {"room": "x" * 2_000_000}
    assert commit(c, a, [{"op": "set", "path": ["users", "A", "rooms", "big"], "data": big}])[0] in (400, 413)


def test_concurrent_users_do_not_interfere(env):
    import threading
    c, _ = env
    tokens = [mkuser(c, "U%d" % i) for i in range(6)]
    errors = []

    def work(i):
        cl = c.application.test_client()
        for n in range(8):
            s, _ = commit(cl, tokens[i], [{"op": "set", "path": ["users", "U%d" % i, "rooms", "r%d" % n], "data": room(str(n))}])
            if s != 200:
                errors.append(s)
    ts_ = [threading.Thread(target=work, args=(i,)) for i in range(6)]
    [t.start() for t in ts_]
    [t.join() for t in ts_]
    assert not errors
    for i in range(6):
        assert len(api(c, "/api/query", tokens[i], {"path": ["users", "U%d" % i, "rooms"]})[1]["docs"]) == 8


def test_hosted_server_never_serves_real_tenant_data_or_server_code(env):
    c, _ = env
    for p in ("/seed-data.js", "/server/app.py", "/legacy/main.py", "/firebase.json", "/.env"):
        assert c.get(p).status_code == 404, p
    assert c.get("/index.html").status_code == 200


def test_hosted_server_does_not_allow_other_sites(env):
    c, _ = env
    r = c.post("/api/get", headers={"Origin": "http://127.0.0.1:5500"}, json={"path": ["users", "A", "rooms", "x"]})
    assert "Access-Control-Allow-Origin" not in r.headers
