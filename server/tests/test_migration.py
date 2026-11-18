import json

import psycopg
from conftest import DB, api, mkuser, register, tok

import migrate_firestore as mig


def test_import_roundtrip_verifies_and_data_is_claimed_by_registration(env_pg, tmp_path):
    c, fb = env_pg
    ms = 1_780_000_000_000
    docs = [
        {"path": ["users", "legacyUid1", "rooms", "roomAAA"], "data": {"room": "201", "type": "Room", "gender": "Mixed", "ac": True,
            "capacity": 2, "x": 20, "y": 20, "tenancyMode": "Bedspace", "demographic": "Mixed", "futureField": {"k": [1, 2]},
            "beds": [{"slot": "Bed 1", "tenant": "Alfad", "start": "2026-08-28", "end": "2027-03-01", "reservedFor": None, "residentType": "Student", "weird": 7},
                     {"slot": "Bed 2", "tenant": None}]}},
        {"path": ["users", "legacyUid1", "prospects", "p1"], "data": {"name": "P", "checkIn": "2026-09-01", "checkOut": None,
            "reservedBed": {"roomId": "roomAAA", "slot": "Bed 2"}, "checkedIn": True, "checkedInAt": {"__ts": ms}, "groupSize": 3}},
        {"path": ["users", "legacyUid1", "tenant_history", "h1"], "data": {"tenant": "X", "leftAt": {"__ts": ms}, "expireAt": {"__ts": ms + 1000}, "room": 305}},   # legacy number in a text field
        {"path": ["users", "legacyUid1", "settings", "viewerAccess"], "data": {"code": "dorm-x", "dormName": "X", "enabled": True}},
        {"path": ["users", "legacyUid1", "temporary_dorm_clients", "t1"], "data": {"name": "T", "start": "2026-01-01", "end": "2026-01-05", "createdAt": {"__ts": ms}, "status": "Active", "remindAfter": 1780000000123}},
        {"path": ["users", "legacyUid1", "bed_transfers", "b1"], "data": {"tenant": "T", "from": {"roomId": "a", "slot": "Bed 1"}, "to": {"roomId": "b", "slot": "Bed 2"}, "transferredAt": {"__ts": ms}}},
        {"path": ["dorms", "dorm-x"], "data": {"ownerUid": "legacyUid1", "dormName": "X", "enabled": True, "updatedAt": {"__ts": ms}}},
        {"path": ["dormSecrets", "dorm-x"], "data": {"ownerUid": "legacyUid1", "passwordHash": "abc"}},
        {"path": ["dorms", "dorm-x", "vacancy", "roomAAA"], "data": {"room": "201", "total": 2, "vacant": 1, "beds": [{"slot": "Bed 1"}], "status": "vacant", "x": 20.5}},
        {"path": ["dorms", "dorm-x", "viewers", "viewerUid"], "data": {"proof": "abc", "name": "V", "email": "v@x", "joinedAt": {"__ts": ms}}},
        {"path": ["superAdmins", "sup"], "data": {"email": "s@x", "createdAt": {"__ts": ms}}},
        {"path": ["branches", "legacyUid1", "snapshots", "s1"], "data": {"total": 4, "vacant": 1, "capturedAt": {"__ts": ms}, "checkouts": 2}},
        {"path": ["audit", "e1"], "data": {"actorUid": "sup", "targetAdmin": "sup", "action": "X", "at": {"__ts": ms}}},
    ]
    f = tmp_path / "backup.json"
    f.write_text(json.dumps({"docs": docs}))
    assert mig.import_backup(str(f), DB) == 0                      # verified
    assert mig.import_backup(str(f), DB) == 0                      # safe to re-run
    # The legacy user claims the account with the same uid: all their data is immediately there.
    s, d = register(c, "legacyUid1", "oldtimer", email="old@gmail.com")
    assert s == 200
    t = tok("legacyUid1", "oldtimer@vecancy.tracker")
    got = api(c, "/api/get", t, {"path": ["users", "legacyUid1", "rooms", "roomAAA"]})[1]["data"]
    assert got["beds"][0]["tenant"] == "Alfad" and got["beds"][0]["weird"] == 7 and got["futureField"] == {"k": [1, 2]}
    h = api(c, "/api/get", t, {"path": ["users", "legacyUid1", "tenant_history", "h1"]})[1]["data"]
    assert h["room"] == 305                                          # the legacy number survived unchanged
    # nobody else can see it
    other = mkuser(c, "Other")
    assert api(c, "/api/get", other, {"path": ["users", "legacyUid1", "rooms", "roomAAA"]})[0] == 403


def test_import_reports_bad_records_instead_of_dropping_them(env_pg, tmp_path):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps({"docs": [{"path": ["users", "u", "mystery", "x"], "data": {"a": 1}},
                                      {"path": ["users", "u", "rooms", "ok"], "data": {"room": "1", "beds": []}}]}))
    assert mig.import_backup(str(f), DB) == 1                        # non-zero: do not delete anything
