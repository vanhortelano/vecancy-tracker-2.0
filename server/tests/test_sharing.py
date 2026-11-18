import time

from conftest import SV, api, commit, mkuser, ts


def w(path, data, op="set"):
    return {"op": op, "path": path, "data": data}


def ok(c, t, *ws):
    s, d = commit(c, t, list(ws))
    assert s == 200, d


def code(c, t, *ws):
    return commit(c, t, list(ws))[0]


def soon(minutes):
    return ts(int(time.time() * 1000) + minutes * 60_000)


def setup_dorm(c, a, uid="A", dorm="dorm-one", proof="PROOF"):
    ok(c, a, w(["dorms", dorm], {"ownerUid": uid, "dormName": "One", "enabled": True, "updatedAt": SV}))
    ok(c, a, w(["dormSecrets", dorm], {"ownerUid": uid, "passwordHash": proof}))


def join(c, v, dorm="dorm-one", proof="PROOF", **over):
    d = {"proof": proof, "name": "V", "email": "v@x.com", "joinedAt": SV}
    d.update(over)
    return code(c, v, w(["dorms", dorm, "viewers", "V"], d))


# ------------------------------------------------------------------ dorm viewers
def test_viewer_join_requires_code_password_enabled_and_clean_fields(env):
    c, _ = env
    a, v = mkuser(c, "A"), mkuser(c, "V")
    setup_dorm(c, a)
    assert code(c, mkuser(c, "B"), w(["dorms", "dorm-one"], {"ownerUid": "B", "dormName": "x", "enabled": True, "updatedAt": SV})) == 403  # code taken
    assert join(c, v, proof="WRONG") == 403
    assert join(c, v, extra="x") == 403
    assert join(c, v, joinedAt=ts(1)) == 403            # cannot back-date the join time
    assert code(c, v, w(["dorms", "nonexistent", "viewers", "V"], {"proof": "P", "joinedAt": SV})) == 403
    assert join(c, v) == 200
    s, d = api(c, "/api/get", v, {"path": ["dorms", "dorm-one", "viewers", "V"]})
    assert d["exists"] and d["data"]["proof"] == "PROOF"
    assert api(c, "/api/get", v, {"path": ["dormSecrets", "dorm-one"]})[0] == 403          # secrets are owner-only
    assert api(c, "/api/get", v, {"path": ["dorms", "dorm-one"]})[0] == 403
    assert api(c, "/api/query", v, {"path": ["dorms", "dorm-one", "viewers"]})[0] == 403   # only the owner lists viewers
    assert len(api(c, "/api/query", a, {"path": ["dorms", "dorm-one", "viewers"]})[1]["docs"]) == 1


def test_vacancy_visible_only_to_joined_viewers_while_enabled(env):
    c, _ = env
    a, v, s = mkuser(c, "A"), mkuser(c, "V"), mkuser(c, "S")
    setup_dorm(c, a)
    ok(c, a, w(["dorms", "dorm-one", "vacancy", "r1"], {"room": "101", "total": 2, "vacant": 1, "beds": [{"slot": "Bed 1"}], "status": "vacant", "updatedAt": SV}),
           w(["dorms", "dorm-one", "layout", "public"], {"shapes": [{"label": "Hall"}], "updatedAt": SV}))
    q = {"path": ["dorms", "dorm-one", "vacancy"]}
    assert api(c, "/api/query", v, q)[0] == 403                    # not joined yet
    join(c, v)
    assert [x["data"]["room"] for x in api(c, "/api/query", v, q)[1]["docs"]] == ["101"]
    assert api(c, "/api/get", v, {"path": ["dorms", "dorm-one", "layout", "public"]})[1]["data"]["shapes"] == [{"label": "Hall"}]
    assert api(c, "/api/query", s, q)[0] == 403                    # stranger
    assert code(c, v, w(["dorms", "dorm-one", "vacancy", "r1"], {"vacant": 99}, "update")) == 403   # read-only
    ok(c, a, w(["dorms", "dorm-one"], {"enabled": False, "updatedAt": SV}, "update"))
    assert api(c, "/api/query", v, q)[0] == 403                    # access paused
    wv = mkuser(c, "W")
    assert code(c, wv, w(["dorms", "dorm-one", "viewers", "W"], {"proof": "PROOF", "name": "W", "email": "w@x", "joinedAt": SV})) == 403   # paused: nobody can join


def test_block_and_unblock(env):
    c, _ = env
    a, v = mkuser(c, "A"), mkuser(c, "V")
    setup_dorm(c, a)
    join(c, v)
    ok(c, a, {"op": "delete", "path": ["dorms", "dorm-one", "viewers", "V"]},
           w(["dorms", "dorm-one", "blocked", "V"], {"name": "V", "email": "v@x.com", "blockedAt": SV}))
    assert api(c, "/api/get", v, {"path": ["dorms", "dorm-one", "viewers", "V"]})[1]["exists"] is False
    assert join(c, v) == 403                                       # blocked users cannot rejoin
    assert code(c, v, {"op": "delete", "path": ["dorms", "dorm-one", "blocked", "V"]}) == 403
    ok(c, a, {"op": "delete", "path": ["dorms", "dorm-one", "blocked", "V"]})
    assert join(c, v) == 200


def test_changing_the_dorm_password_removes_viewers(env):
    c, _ = env
    a, v = mkuser(c, "A"), mkuser(c, "V")
    setup_dorm(c, a)
    join(c, v)
    ok(c, a, w(["dormSecrets", "dorm-one"], {"passwordHash": "NEW"}, "update"),
           {"op": "delete", "path": ["dorms", "dorm-one", "viewers", "V"]})
    assert join(c, v, proof="PROOF") == 403 and join(c, v, proof="NEW") == 200


# ------------------------------------------------------------------ super admin platform
def super_setup(c):
    s, a, m = mkuser(c, "S"), mkuser(c, "A"), mkuser(c, "M")
    ok(c, s, w(["superAdmins", "S"], {"email": "s@x.com", "createdAt": SV}))
    return s, a, m


def connect(c, s, a):
    ok(c, a, w(["pairing", "PC1"], {"ownerUid": "A", "dormName": "Dorm A", "location": "Cebu", "expiresAt": soon(10)}))
    ok(c, s, w(["branches", "A"], {"ownerUid": "A", "dormName": "Dorm A", "location": "Cebu", "purpose": "p", "pairingCode": "PC1",
                                   "requestedBy": "S", "dirStatus": "pending", "analyticsStatus": "pending", "createdAt": SV}))


def test_super_admin_registration_is_self_only(env):
    c, _ = env
    a = mkuser(c, "A")
    assert code(c, a, w(["superAdmins", "S"], {"email": "x", "createdAt": SV})) == 403          # cannot make someone else one
    assert code(c, a, w(["superAdmins", "A"], {"email": "x", "createdAt": SV, "role": "root"})) == 403
    ok(c, a, w(["superAdmins", "A"], {"email": "x", "createdAt": SV}))
    assert code(c, a, w(["superAdmins", "A"], {"email": "y", "createdAt": SV})) == 403          # no edits afterwards


def test_pairing_and_branch_connection_rules(env):
    c, _ = env
    s, a, m = super_setup(c)
    assert code(c, a, w(["pairing", "LONG"], {"ownerUid": "A", "dormName": "x", "location": "y", "expiresAt": soon(60)})) == 403   # > 20 min
    assert code(c, a, w(["pairing", "FORGE"], {"ownerUid": "S", "dormName": "x", "location": "y", "expiresAt": soon(5)})) == 403
    ok(c, a, w(["pairing", "PC1"], {"ownerUid": "A", "dormName": "Dorm A", "location": "Cebu", "expiresAt": soon(10)}))
    assert api(c, "/api/get", m, {"path": ["pairing", "PC1"]})[0] == 403                      # only Super Admins read codes
    assert api(c, "/api/get", s, {"path": ["pairing", "PC1"]})[0] == 200
    bad = {"ownerUid": "A", "dormName": "Dorm A", "location": "Cebu", "purpose": "p", "pairingCode": "PC1",
           "requestedBy": "S", "dirStatus": "pending", "analyticsStatus": "pending", "createdAt": SV}
    assert code(c, m, w(["branches", "A"], {**bad, "requestedBy": "M"})) == 403               # not a Super Admin
    assert code(c, s, w(["branches", "A"], {**bad, "dirStatus": "approved"})) == 403          # cannot self-approve
    assert code(c, s, w(["branches", "A"], {**bad, "pairingCode": "nope"})) == 403
    ok(c, s, w(["branches", "A"], bad))


def test_only_the_branch_admin_decides_permissions(env):
    c, _ = env
    s, a, m = super_setup(c)
    connect(c, s, a)
    assert code(c, s, w(["branches", "A"], {"dirStatus": "approved"}, "update")) == 403       # Super Admin cannot
    assert code(c, a, w(["branches", "A"], {"dirStatus": "revoked"}, "update")) == 403        # pending -> revoked not allowed
    assert code(c, a, w(["branches", "A"], {"dormName": "Renamed"}, "update")) == 403         # only the two permissions
    ok(c, a, w(["branches", "A"], {"dirStatus": "approved", "analyticsStatus": "approved", "decidedAt": SV}, "update"))
    ok(c, a, w(["branches", "A"], {"dirStatus": "revoked", "decidedAt": SV}, "update"))
    assert api(c, "/api/get", m, {"path": ["branches", "A"]})[0] == 403
    assert api(c, "/api/get", s, {"path": ["branches", "A"]})[0] == 200


def test_directory_snapshots_changes_and_visibility(env):
    c, _ = env
    s, a, m = super_setup(c)
    s2 = mkuser(c, "S2")
    ok(c, s2, w(["superAdmins", "S2"], {"email": "z", "createdAt": SV}))
    connect(c, s, a)
    d = {"ownerUid": "A", "dormName": "Dorm A", "location": "Cebu", "total": 10, "vacant": 4, "occupied": 6, "updatedAt": SV}
    assert code(c, a, w(["directory", "A"], d)) == 403                                         # not approved yet
    snap = {"total": 10, "vacant": 4, "occupied": 6, "capturedAt": SV}
    assert code(c, a, w(["branches", "A", "snapshots", "x1"], snap)) == 403
    ok(c, a, w(["branches", "A"], {"dirStatus": "approved", "analyticsStatus": "approved", "decidedAt": SV}, "update"))
    ok(c, a, w(["directory", "A"], d), w(["branches", "A", "snapshots", "x1"], snap))
    assert code(c, a, w(["directory", "A"], {**d, "ownerUid": "S"})) == 403
    assert api(c, "/api/get", m, {"path": ["directory", "A"]})[1]["data"]["vacant"] == 4        # marketing viewers read it
    assert len(api(c, "/api/query", m, {"path": ["directory"]})[1]["docs"]) == 1
    # analytics: only the connecting Super Admin
    assert len(api(c, "/api/query", s, {"path": ["branches", "A", "snapshots"], "orderBy": [["capturedAt", "asc"]]})[1]["docs"]) == 1
    assert api(c, "/api/query", s2, {"path": ["branches", "A", "snapshots"]})[0] == 403
    assert api(c, "/api/query", m, {"path": ["branches", "A", "snapshots"]})[0] == 403
    # list of branches only ever shows the caller's own connections
    assert [x["id"] for x in api(c, "/api/query", s, {"path": ["branches"]})[1]["docs"]] == ["A"]
    assert api(c, "/api/query", s2, {"path": ["branches"]})[1]["docs"] == []
    assert api(c, "/api/query", m, {"path": ["branches"]})[0] == 403
    # consent flow: branch asks, only the connected Super Admin answers
    ch = {"kind": "remove", "status": "pending", "dormName": "Dorm A", "createdAt": SV}
    ok(c, a, w(["branches", "A", "changes", "c1"], ch))
    assert code(c, a, w(["branches", "A", "changes", "c1"], {"status": "approved", "decidedAt": SV}, "update")) == 403
    assert code(c, s2, w(["branches", "A", "changes", "c1"], {"status": "approved", "decidedAt": SV}, "update")) == 403
    ok(c, s, w(["branches", "A", "changes", "c1"], {"status": "approved", "decidedAt": SV}, "update"))
    assert code(c, s, w(["branches", "A", "changes", "c1"], {"status": "rejected", "decidedAt": SV}, "update")) == 403  # single-use
    # pausing viewer access is asked too, with a short reason the Super Admin reads; long or odd fields are refused
    ok(c, a, w(["branches", "A", "changes", "c2"], {"kind": "pause", "status": "pending", "reason": "Agent left the company", "dormName": "Dorm A", "createdAt": SV}))
    assert code(c, a, w(["branches", "A", "changes", "c3"], {"kind": "pause", "status": "pending", "reason": "x" * 301, "createdAt": SV})) == 403
    assert code(c, a, w(["branches", "A", "changes", "c4"], {"kind": "rename", "status": "pending", "createdAt": SV})) == 403
    assert code(c, a, w(["branches", "A", "changes", "c5"], {"kind": "pause", "status": "pending", "extra": 1, "createdAt": SV})) == 403
    # disconnect by either side removes the directory entry
    ok(c, s, {"op": "delete", "path": ["directory", "A"]})


def test_audit_is_append_only_and_private(env):
    c, _ = env
    s, a, m = super_setup(c)
    e = {"actorUid": "S", "actorEmail": "s@x", "action": "X", "branch": "", "detail": "", "at": SV, "targetAdmin": "S"}
    ok(c, s, w(["audit", "e1"], e))
    assert code(c, a, w(["audit", "e2"], {**e, "actorUid": "S"})) == 403                       # cannot forge another actor
    assert code(c, s, w(["audit", "e1"], {**e, "action": "EDIT"})) == 403                      # no edits
    assert code(c, s, {"op": "delete", "path": ["audit", "e1"]}) == 403                       # no deletes
    assert len(api(c, "/api/query", s, {"path": ["audit"], "where": [["targetAdmin", "==", "S"]]})[1]["docs"]) == 1
    assert api(c, "/api/query", m, {"path": ["audit"]})[1]["docs"] == []                      # others see nothing
    ok(c, a, w(["audit", "e3"], {**e, "actorUid": "A", "targetAdmin": "S"}))                  # branch logs for the Super Admin
    assert len(api(c, "/api/query", s, {"path": ["audit"]})[1]["docs"]) == 2


def test_central_server_one_per_super_admin_and_marketing_join(env):
    c, _ = env
    s, a, m = super_setup(c)
    batch = [w(["centralSecrets", "central-1"], {"ownerUid": "S", "passwordHash": "CP"}),
             w(["centralAccess", "central-1"], {"ownerUid": "S", "name": "HQ", "enabled": True, "updatedAt": SV}),
             w(["centralOwner", "S"], {"code": "central-1"})]
    assert code(c, a, *batch) == 403                                                          # not a Super Admin
    assert code(c, s, batch[1]) == 403                                                        # access without its pointer
    ok(c, s, *batch)
    second = [w(["centralSecrets", "central-2"], {"ownerUid": "S", "passwordHash": "CP2"}),
              w(["centralAccess", "central-2"], {"ownerUid": "S", "name": "HQ2", "enabled": True, "updatedAt": SV}),
              w(["centralOwner", "S"], {"code": "central-2"})]
    assert code(c, s, *second[:2]) == 403 and code(c, s, *second) == 403                      # only one server each
    jv = lambda t, p: code(c, t, w(["centralAccess", "central-1", "viewers", "M"], {"proof": p, "name": "M", "email": "m@x", "joinedAt": SV}))
    assert jv(m, "BAD") == 403 and jv(m, "CP") == 200
    assert api(c, "/api/get", m, {"path": ["centralSecrets", "central-1"]})[0] == 403
    assert api(c, "/api/query", m, {"path": ["centralAccess"]})[0] == 403
    assert [x["id"] for x in api(c, "/api/query", s, {"path": ["centralAccess"]})[1]["docs"]] == ["central-1"]
    assert len(api(c, "/api/query", s, {"path": ["centralAccess", "central-1", "viewers"]})[1]["docs"]) == 1
    assert api(c, "/api/query", m, {"path": ["centralAccess", "central-1", "viewers"]})[0] == 403
    assert code(c, m, w(["centralAccess", "central-1"], {"enabled": False}, "update")) == 403


# ------------------------------------------------------------------ account (data) transfer
def test_account_transfer_flow_and_guards(env):
    c, _ = env
    a, b, x = mkuser(c, "A"), mkuser(c, "B"), mkuser(c, "X")
    ok(c, a, w(["users", "A", "rooms", "r1"], {"room": "101", "capacity": 0, "beds": []}))
    assert code(c, a, w(["accountTransfers", "T1"], {"fromUid": "A", "fromEmail": "a", "purpose": "p", "expiresAt": soon(60 * 48), "status": "open"})) == 403
    assert code(c, a, w(["accountTransfers", "T1"], {"fromUid": "B", "fromEmail": "a", "purpose": "p", "expiresAt": soon(60), "status": "open"})) == 403
    ok(c, a, w(["accountTransfers", "T1"], {"fromUid": "A", "fromEmail": "a", "purpose": "p", "expiresAt": soon(60), "status": "open"}))
    assert code(c, a, w(["users", "B", "rooms", "r1"], {"room": "101", "beds": []})) == 403           # before approval
    assert code(c, a, w(["accountTransfers", "T1"], {"status": "requested", "toUid": "A"}, "update")) == 403   # sender cannot request own
    ok(c, b, w(["accountTransfers", "T1"], {"status": "requested", "toUid": "B", "toEmail": "b"}, "update"),
           w(["incomingTransfer", "B"], {"code": "T1", "fromUid": "A"}))
    assert code(c, x, w(["incomingTransfer", "X"], {"code": "T1", "fromUid": "A"})) == 403            # not the requester
    assert code(c, b, w(["accountTransfers", "T1"], {"status": "approved"}, "update")) == 403          # recipient cannot approve
    assert code(c, a, w(["users", "B", "rooms", "r1"], {"room": "101", "beds": []})) == 403
    ok(c, a, w(["accountTransfers", "T1"], {"status": "approved"}, "update"))
    ok(c, a, w(["users", "B", "rooms", "r1"], {"room": "101", "capacity": 0, "beds": []}))             # now allowed
    assert code(c, x, w(["users", "B", "rooms", "r9"], {"room": "9", "beds": []})) == 403             # nobody else
    assert len(api(c, "/api/query", a, {"path": ["accountTransfers"], "where": [["fromUid", "==", "A"]]})[1]["docs"]) == 1
    assert api(c, "/api/query", b, {"path": ["accountTransfers"]})[1]["docs"] == []


# ------------------------------------------------------------------ room status sharing + dorm photo (feedback A-0002/4/8)
def test_room_status_permission_and_requester_name(env):
    c, _ = env
    s, a, m = super_setup(c)
    s2 = mkuser(c, "S2")
    ok(c, s2, w(["superAdmins", "S2"], {"email": "z", "createdAt": SV}))
    ok(c, a, w(["pairing", "PC1"], {"ownerUid": "A", "dormName": "Dorm A", "location": "Cebu", "expiresAt": soon(10)}))
    base = {"ownerUid": "A", "dormName": "Dorm A", "location": "Cebu", "purpose": "p", "pairingCode": "PC1",
            "requestedBy": "S", "dirStatus": "pending", "analyticsStatus": "pending", "createdAt": SV}
    assert code(c, s, w(["branches", "A"], {**base, "roomStatus": "approved", "requesterName": "Maria"})) == 403   # no self-approval
    assert code(c, s, w(["branches", "A"], {**base, "roomStatus": "pending", "requesterName": "x" * 81})) == 403
    ok(c, s, w(["branches", "A"], {**base, "roomStatus": "pending", "requesterName": "Maria Santos"}))
    assert api(c, "/api/get", a, {"path": ["branches", "A"]})[1]["data"]["requesterName"] == "Maria Santos"
    room = {"room": '{"room":"101","bedInfo":[{"slot":"Bed 1","tenant":"Ann"}]}', "updatedAt": SV}
    assert code(c, a, w(["branches", "A", "rooms", "r1"], room)) == 403                           # not approved yet
    assert code(c, s, w(["branches", "A"], {"roomStatus": "approved"}, "update")) == 403          # only the branch decides
    ok(c, a, w(["branches", "A"], {"roomStatus": "approved", "decidedAt": SV}, "update"))
    ok(c, a, w(["branches", "A", "rooms", "r1"], room))
    assert code(c, s, w(["branches", "A", "rooms", "r2"], room)) == 403                           # Super Admin is read-only
    assert len(api(c, "/api/query", s, {"path": ["branches", "A", "rooms"]})[1]["docs"]) == 1
    assert api(c, "/api/get", s, {"path": ["branches", "A", "rooms", "r1"]})[0] == 200
    assert api(c, "/api/query", s2, {"path": ["branches", "A", "rooms"]})[0] == 403               # another Super Admin
    assert api(c, "/api/query", m, {"path": ["branches", "A", "rooms"]})[0] == 403                # a viewer
    ok(c, a, w(["branches", "A"], {"roomStatus": "revoked", "decidedAt": SV}, "update"))
    assert api(c, "/api/query", s, {"path": ["branches", "A", "rooms"]})[0] == 403                # revoked: no access at once
    assert api(c, "/api/get", s, {"path": ["branches", "A", "rooms", "r1"]})[0] == 403


def test_branch_photo_upload_and_access(env):
    c, _ = env
    s, a, m = super_setup(c)
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 200
    put = lambda tkn, data, mime="image/jpeg": c.put("/api/branch-photo", data=data, headers={"Authorization": "Bearer " + tkn, "Content-Type": mime})
    assert put(a, jpeg).status_code == 404                                                       # not linked yet
    connect(c, s, a)
    assert put(a, b"not an image").status_code == 400
    assert put(a, jpeg, "image/gif").status_code == 400
    r = put(a, jpeg)
    assert r.status_code == 200 and r.get_json()["photoVersion"]
    assert api(c, "/api/get", s, {"path": ["branches", "A"]})[1]["data"]["photoVersion"] == r.get_json()["photoVersion"]
    get = lambda tkn: c.get("/api/branch-photo/A", headers={"Authorization": "Bearer " + tkn})
    assert get(a).status_code == 200 and get(a).data == jpeg
    assert get(s).status_code == 200                                                             # the connected Super Admin
    assert get(m).status_code == 404                                                             # anyone else
    s2 = mkuser(c, "S2")
    ok(c, s2, w(["superAdmins", "S2"], {"email": "z", "createdAt": SV}))
    assert get(s2).status_code == 404


def test_tenant_record_fields(env):
    c, _ = env
    a = mkuser(c, "A")
    t = {"name": "Ann", "contact": "", "address": ""}
    ok(c, a, w(["users", "A", "tenants", "t1"], {**t, "record": "bad", "recordReason": "Unpaid", "recordAt": SV}))
    assert code(c, a, w(["users", "A", "tenants", "t2"], {**t, "record": "maybe"})) == 403
    assert code(c, a, w(["users", "A", "tenants", "t3"], {**t, "record": "bad", "recordReason": "x" * 401})) == 403


# ------------------------------------------------------------------ open a dorm from the Marketing Directory (A-0027)
def test_open_dorm_from_directory(env):
    c, _ = env
    s, a, m = super_setup(c)
    connect(c, s, a)
    setup_dorm(c, a, uid="A", dorm="dorm-a", proof="DP")
    ok(c, s, w(["centralSecrets", "central-1"], {"ownerUid": "S", "passwordHash": "CP"}),
       w(["centralAccess", "central-1"], {"ownerUid": "S", "name": "HQ", "enabled": True, "updatedAt": SV}),
       w(["centralOwner", "S"], {"code": "central-1"}))
    open_ = lambda t, central="central-1", branch="A": c.post("/api/central/open-dorm", json={"central": central, "branch": branch},
                                                              headers={"Authorization": "Bearer " + t})
    assert open_(m).status_code == 403                                                        # not a directory viewer
    ok(c, m, w(["centralAccess", "central-1", "viewers", "M"], {"proof": "CP", "name": "M", "email": "m@x", "joinedAt": SV}))
    assert open_(m).status_code == 403                                                        # Directory not approved yet
    ok(c, a, w(["branches", "A"], {"dirStatus": "approved", "decidedAt": SV}, "update"))
    assert api(c, "/api/query", m, {"path": ["dorms", "dorm-a", "vacancy"]})[0] == 403        # no access before opening
    r = open_(m)
    assert r.status_code == 200 and r.get_json()["code"] == "dorm-a"
    assert api(c, "/api/query", m, {"path": ["dorms", "dorm-a", "vacancy"]})[0] == 200        # now a viewer of that dorm
    assert len(api(c, "/api/query", a, {"path": ["dorms", "dorm-a", "viewers"]})[1]["docs"]) == 1   # the Branch Admin sees them
    # viewer access off -> refused; a different directory -> refused; blocked from the dorm -> refused
    ok(c, a, {"op": "delete", "path": ["dorms", "dorm-a", "viewers", "M"]},
       w(["dorms", "dorm-a", "blocked", "M"], {"name": "M", "email": "m@x", "blockedAt": SV}))
    assert open_(m).status_code == 403
    assert open_(m, central="central-x").status_code == 403
    assert open_(m, branch="nobody").status_code == 403
    # central password changed -> old membership no longer counts
    ok(c, s, w(["centralSecrets", "central-1"], {"ownerUid": "S", "passwordHash": "CP-NEW"}, "update"))
    o = mkuser(c, "O")
    ok(c, o, w(["centralAccess", "central-1", "viewers", "O"], {"proof": "CP-NEW", "name": "O", "email": "o@x", "joinedAt": SV}))
    assert open_(o).status_code == 200
    ok(c, a, w(["dorms", "dorm-a"], {"enabled": False, "updatedAt": SV}, "update"))
    assert open_(o).status_code == 404                                                        # viewer page switched off
