"""Account data transfer runs on the server in one transaction: everything moves or nothing does."""
from conftest import api, commit, mkuser


def ts_in(hours):
    import time
    return {"__ts": int((time.time() + hours * 3600) * 1000)}


def setup(c):
    a, b = mkuser(c, "A"), mkuser(c, "B")
    w = [{"op": "set", "path": ["users", "A", "rooms", "r1"], "data": {"room": "101", "capacity": 1,
          "beds": [{"slot": "Bed 1", "tenant": "Ann", "end": "2027-01-01"}]}},
         {"op": "set", "path": ["users", "A", "prospects", "p1"], "data": {"name": "Pia", "checkIn": "2027-02-01"}},
         {"op": "set", "path": ["users", "A", "settings", "viewerAccess"], "data": {"code": "DORM1", "enabled": True}}]
    assert commit(c, a, w)[0] == 200
    assert commit(c, a, [{"op": "set", "path": ["accountTransfers", "CODE-0001"], "data": {
        "fromUid": "A", "fromEmail": "a", "purpose": "leaving", "expiresAt": ts_in(5), "status": "open"}}])[0] == 200
    assert commit(c, b, [{"op": "update", "path": ["accountTransfers", "CODE-0001"],
                          "data": {"status": "requested", "toUid": "B", "toEmail": "b"}}])[0] == 200
    assert commit(c, b, [{"op": "set", "path": ["incomingTransfer", "B"], "data": {"code": "CODE-0001", "fromUid": "A"}}])[0] == 200
    return a, b


def test_transfer_moves_everything_once_and_new_owner_can_edit(env):
    c, _ = env
    a, b = setup(c)
    assert api(c, "/api/transfer/complete", b, {"code": "CODE-0001"})[0] == 404          # only the sender
    s, d = api(c, "/api/transfer/complete", a, {"code": "code-0001"})                  # lower case is fine
    assert s == 200 and d["moved"]["rooms"] == 1 and d["moved"]["prospects"] == 1
    room = api(c, "/api/get", b, {"path": ["users", "B", "rooms", "r1"]})[1]
    assert room["exists"] and room["data"]["beds"][0]["tenant"] == "Ann"
    assert api(c, "/api/query", a, {"path": ["users", "A", "rooms"]})[1]["docs"] == []   # moved, not copied
    assert api(c, "/api/get", a, {"path": ["users", "A", "settings", "viewerAccess"]})[1]["exists"]   # stays
    assert commit(c, b, [{"op": "update", "path": ["users", "B", "rooms", "r1"], "data": {"room": "101B"}}])[0] == 200
    assert api(c, "/api/get", b, {"path": ["accountTransfers", "CODE-0001"]})[1]["data"]["status"] == "done"
    assert api(c, "/api/transfer/complete", a, {"code": "CODE-0001"})[0] == 409          # not twice


def test_transfer_into_a_non_empty_account_changes_nothing(env):
    c, _ = env
    a, b = setup(c)
    assert commit(c, b, [{"op": "set", "path": ["users", "B", "shapes", "s1"], "data": {"label": "Lobby"}}])[0] == 200
    s, d = api(c, "/api/transfer/complete", a, {"code": "CODE-0001"})
    assert s == 409 and d["error"] == "not_empty"
    assert api(c, "/api/get", a, {"path": ["users", "A", "rooms", "r1"]})[1]["exists"]
    assert not api(c, "/api/get", b, {"path": ["users", "B", "rooms", "r1"]})[1]["exists"]


def test_tenant_information_and_photos_move_with_the_transfer(env):
    c, _ = env
    a, b = setup(c)
    assert commit(c, a, [{"op": "set", "path": ["users", "A", "tenants", "t1"], "data": {"name": "Ann"}}])[0] == 200
    r = c.put("/api/tenant-photo/t1", data=b"\xff\xd8\xff\xe0" + b"0" * 50, headers={"Authorization": "Bearer " + a, "Content-Type": "image/jpeg"})
    assert r.status_code == 200
    assert api(c, "/api/transfer/complete", a, {"code": "CODE-0001"})[0] == 200
    assert api(c, "/api/get", b, {"path": ["users", "B", "tenants", "t1"]})[1]["data"]["name"] == "Ann"
    assert c.get("/api/tenant-photo/t1", headers={"Authorization": "Bearer " + b}).status_code == 200
    assert c.get("/api/tenant-photo/t1", headers={"Authorization": "Bearer " + a}).status_code == 404
