"""The smarter assistant: reads the caller's own records, uses screen context, and only PROPOSES
changes (restating what it understood) that the browser applies after Confirm."""
from datetime import date, timedelta

from conftest import api, commit, mkuser

T = date.today()


def d(n):
    return (T + timedelta(days=n)).isoformat()


def setup(c):
    a = mkuser(c, "A")
    rooms = {"r201": {"room": "201", "capacity": 3, "gender": "Female", "demographic": "Students", "tenancyMode": "Bedspace",
                      "beds": [{"slot": "Bed 1", "tenant": "Ana Reyes", "start": d(-30), "end": d(3)}, {"slot": "Bed 2", "tenant": None},
                               {"slot": "Bed 3", "tenant": "Lea Cruz", "start": d(-60), "end": d(-2)}]},
             "r202": {"room": "202", "capacity": 2, "gender": "Male", "demographic": "Mixed", "tenancyMode": "Bedspace",
                      "beds": [{"slot": "Bed 1", "tenant": "Juan Dela Cruz", "start": d(-10), "end": d(40)}, {"slot": "Bed 2", "tenant": None}]},
             "r203": {"room": "203", "capacity": 2, "gender": "Mixed", "demographic": "Mixed", "tenancyMode": "Bedspace",
                      "beds": [{"slot": "Bed 1", "tenant": None}, {"slot": "Bed 2", "tenant": None}]}}
    w = [{"op": "set", "path": ["users", "A", "rooms", k], "data": v} for k, v in rooms.items()]
    w.append({"op": "set", "path": ["users", "A", "prospects", "p1"],
              "data": {"name": "Maria Santos", "gender": "Female", "demographic": "Student", "checkIn": d(10)}})
    assert commit(c, a, w)[0] == 200
    return a


CHAT = {}                                     # like the real chat window: every message continues the same conversation


def say(c, tok, q, **ctx):
    s, r = api(c, "/api/assistant", tok, {"question": q, "context": dict({"today": T.isoformat()}, **ctx), "conversationId": CHAT.get(tok)})
    assert s == 200, r
    if r.get("conversationId"):
        CHAT[tok] = r["conversationId"]
    return r


def test_answers_from_the_users_own_records(env):
    c, _ = env
    a = setup(c)
    assert "Ana Reyes" in say(c, a, "who is in room 201")["response"]
    assert "Room 202" in say(c, a, "where is Juan?")["response"]
    assert "Ana Reyes" in say(c, a, "who leaves this week")["response"]
    r = say(c, a, "vacant beds for female students")["response"]
    assert "Room 201 (Bed 2)" in r and "202" not in r                    # male room excluded
    assert "Maria Santos" in say(c, a, "show my reservations")["response"]
    assert "3 rooms" in say(c, a, "give me a summary")["response"]


def test_change_requests_are_only_proposed_and_restated(env):
    c, _ = env
    a = setup(c)
    r = say(c, a, "check in Pedro Garcia to room 202 until March 1")
    assert r["response"].startswith("Here's what I understood") and "Pedro Garcia" in r["response"]
    act = r["action"]
    assert act["type"] == "edit_room" and act["roomId"] == "r202"
    assert act["changes"]["bedChanges"][0]["slot"] == "Bed 2" and act["changes"]["bedChanges"][0]["tenant"] == "Pedro Garcia"
    # nothing was written: the bed is still empty
    beds = api(c, "/api/get", a, {"path": ["users", "A", "rooms", "r202"]})[1]["data"]["beds"]
    assert beds[1]["tenant"] is None
    assert say(c, a, "check out Ana")["action"] == {"type": "checkout_tenant", "roomId": "r201", "slot": "Bed 1",
                                                    "summary": "check out Ana Reyes from Room 201, Bed 1. The bed becomes vacant and the stay is saved in Tenant History."}
    assert say(c, a, "move Ana to room 203")["action"]["targetRoomId"] == "r203"
    assert say(c, a, "add room 305 with 4 beds")["action"]["type"] == "create_room"
    assert say(c, a, "delete room 201")["action"]["type"] == "none"                 # occupied: explains instead


def test_missing_details_are_asked_for_and_remembered(env):
    c, _ = env
    a = setup(c)
    assert "full name" in say(c, a, "add a tenant")["response"]
    assert "Which room" in say(c, a, "Rosa Lim")["response"]
    assert "Until when" in say(c, a, "room 203")["response"]
    r = say(c, a, "until April 5")
    assert r["action"]["type"] == "edit_room" and r["action"]["roomId"] == "r203"
    assert r["action"]["changes"]["bedChanges"][0]["tenant"] == "Rosa Lim"
    say(c, a, "check in Tom to room 201")
    assert "cancelled" in say(c, a, "cancel")["response"]


def test_screen_context_is_used_but_never_trusted(env):
    c, _ = env
    a = setup(c)
    r = say(c, a, "explain this tab", tab="matrix")
    assert "Bed Matrix" in r["response"] and r["suggestions"]
    assert "Ana Reyes" in say(c, a, "who is in this room?", tab="dashboard", roomId="r201")["response"]
    b = mkuser(c, "B")
    r = say(c, b, "who is in this room?", roomId="r201")                 # someone else's room id: ignored
    assert "Ana" not in r["response"]
    r = say(c, b, "where is Ana")
    assert "Ana" not in r["response"] or "couldn't find" in r["response"]
    assert say(c, b, "check out Ana")["action"]["type"] == "none"
