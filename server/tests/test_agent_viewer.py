"""Assistant on the Dormitory Viewer and directory pages: viewer permissions, no names, same numbers as the
page (vacancy_core), filters/scope, upcoming vacancies, navigation, and the trained language model."""
from datetime import datetime, timedelta, timezone

import agent_nlu
import vacancy_core as vc
from conftest import api, mkuser, ts
from store import KINDS, write

NOW = datetime.now(timezone.utc)


def day(n):
    return (NOW + timedelta(days=n)).strftime("%Y-%m-%d")


ROOMS = {
    "r201": {"room": "201", "gender": "Female", "demographic": "Students", "tenancyMode": "Bedspace", "total": 3, "vacant": 1,
             "bedInfo": [{"slot": "Bed 1", "tenant": True, "start": day(-10), "end": day(3)}, {"slot": "Bed 2", "tenant": False},
                         {"slot": "Bed 3", "tenant": True, "start": day(-10), "end": day(-2)}]},
    "r205": {"room": "205", "gender": "Male", "demographic": "Students", "tenancyMode": "Bedspace", "total": 2, "vacant": 0,
             "bedInfo": [{"slot": "Bed 1", "tenant": True, "start": day(-10), "end": day(40)},
                         {"slot": "Bed 2", "tenant": False, "reservedFor": True, "reservedFrom": day(5)}]},
    "r210": {"room": "210", "gender": "Male", "demographic": "Reviewees", "tenancyMode": "Bedspace", "total": 4, "vacant": 3,
             "bedInfo": [{"slot": "Bed 1", "tenant": True, "start": day(-1), "end": day(1)}, {"slot": "Bed 2", "tenant": False},
                         {"slot": "Bed 3", "tenant": False}, {"slot": "Bed 4", "tenant": False}]},
}


def setup(c, viewer_uid="V", join=True):
    owner = mkuser(c, "OWN")
    v = mkuser(c, viewer_uid)
    now = datetime.now(timezone.utc)
    with c.application.extensions["pool"].connection() as conn:
        with conn.transaction():
            cur = conn.cursor()
            write(cur, KINDS["dorms"], ("test-dorm",), {"ownerUid": "OWN", "dormName": "Test", "enabled": True}, now, lenient=True)
            if join:
                write(cur, KINDS["dorm_viewers"], ("test-dorm", viewer_uid), {"proof": "x", "name": "", "email": ""}, now, lenient=True)
            for rid, doc in ROOMS.items():
                write(cur, KINDS["dorm_vacancy"], ("test-dorm", rid), dict(doc, x=10, y=10, beds=[]), now, lenient=True)
            write(cur, KINDS["directory"], ("D1",), {"ownerUid": "D1", "dormName": "North", "location": "Cebu", "total": 40, "vacant": 12,
                                                    "maleVacant": 2, "femaleVacant": 10}, now, lenient=True)
            write(cur, KINDS["directory"], ("D2",), {"ownerUid": "D2", "dormName": "South", "location": "Manila", "total": 30, "vacant": 9,
                                                    "maleVacant": 9, "femaleVacant": 0}, now, lenient=True)
    return owner, v


def ask(c, tok, q, page="viewer", **ctx):
    base = {"page": page, "code": "test-dorm", "now": int(NOW.timestamp() * 1000), "tzOffset": -480, "filters": {}}
    s, r = api(c, "/api/assistant", tok, {"question": q, "context": dict(base, **ctx)})
    assert s == 200, r
    return r


def test_viewer_counts_match_the_shared_rules(env):
    c, _ = env
    _o, v = setup(c)
    r = ask(c, v, "How many beds are vacant?")
    assert "4 of 9 beds are vacant" in r["response"] and "2 more will free up" in r["response"]
    # same numbers as vacancy_core (the page uses the JS twin of it)
    st = vc.stats([dict(d, id=k) for k, d in ROOMS.items()], {}, int(NOW.timestamp() * 1000), -480)
    assert (st["vacant"], st["occupied"], st["upcoming"], st["reserved"], st["overdue"]) == (4, 4, 2, 1, 1)
    # filters from the page (or from the question) change the scope
    assert "Scope Male: 3 of 6 beds are vacant" in ask(c, v, "how many vacant beds?", filters={"gender": "Male"})["response"]
    assert "Scope Female: 1 of 3" in ask(c, v, "how many vacnt beds for girls")["response"]


def test_viewer_room_status_upcoming_compare(env):
    c, _ = env
    _o, v = setup(c)
    r = ask(c, v, "Show me the occupancy status", roomId="r201")
    assert r["response"].startswith("Room 201: 3 beds — 2 occupied, 1 vacant, 1 upcoming vacancy")
    statuses = [row[1] for row in r["blocks"][1]["rows"]]
    assert statuses == ["Occupied · upcoming vacancy", "Vacant", "Overdue"]
    up = ask(c, v, "show upcoming vacancies")
    assert "2 beds will become vacant within 7 days" in up["response"]
    cmp = ask(c, v, "compare boys and girls")
    rows = {x[0]: x for x in cmp["blocks"][0]["rows"]}
    assert rows["Male"][1:4] == [6, 2, 3] and rows["Female"][1:4] == [3, 2, 1]


def test_viewer_is_read_only_and_never_names(env):
    c, _ = env
    _o, v = setup(c)
    assert ask(c, v, "who lives in room 201?")["intent"] == "privacy"
    assert ask(c, v, "what is the name of the tenant in bed 1")["intent"] == "privacy"
    assert ask(c, v, "check out the tenant in room 201")["intent"] == "read_only"
    r = ask(c, v, "report the vacancy")
    assert r["action"] == {"type": "none"}


def test_viewer_without_access_gets_nothing(env):
    c, _ = env
    _o, _v = setup(c)
    stranger = mkuser(c, "X")
    r = ask(c, stranger, "How many beds are vacant?")
    assert r["intent"] == "denied" and "beds" not in r["response"].split("access")[0]


def test_viewer_navigation(env):
    c, _ = env
    _o, v = setup(c)
    assert ask(c, v, "open the hallwy")["nav"] == {"view": "hallway"}
    assert ask(c, v, "take me to analytics")["nav"] == {"view": "analytics"}
    assert ask(c, v, "show room 210")["nav"] == {"view": "hallway", "roomId": "r210"}
    assert ask(c, v, "show male rooms only")["nav"] == {"filters": {"gender": "Male"}}


def test_directory_page(env):
    c, _ = env
    _o, v = setup(c)
    r = ask(c, v, "Which dorm has the most vacant beds for female?", page="marketing")
    assert r["response"].startswith("North has the most vacant beds for female residents: 10")
    r = ask(c, v, "where can boys stay", page="marketing")
    assert "South" in r["response"]


def test_trained_language_model():
    cases = {"how many vacnt beds for boys?": "vacancy_summary", "show me upcomng vacancies pls": "upcoming",
             "compare boys vs girls": "compare", "opn the hallwy": "nav_hallway", "wat can u do": "help",
             "report pls": "report", "which dorm has most free beds": "highest", "explain the colors": "explain"}
    for q, want in cases.items():
        assert agent_nlu.classify(q)[0] == want, q
    assert agent_nlu.normalize("Any free beds for the girls?") == "any vacant beds for the female"


def test_admin_fallback_understands_other_wordings(env):
    c, _ = env
    a = mkuser(c, "A")
    from conftest import commit
    w = [{"op": "set", "path": ["users", "A", "rooms", "r1"], "data": {"room": "101", "capacity": 2, "gender": "Male", "demographic": "Students",
          "tenancyMode": "Bedspace", "beds": [{"slot": "Bed 1", "tenant": "Ana", "start": day(-3), "end": day(2)}, {"slot": "Bed 2", "tenant": None}]}},
         {"op": "set", "path": ["users", "A", "rooms", "r2"], "data": {"room": "102", "capacity": 1, "gender": "Female", "demographic": "Students",
          "tenancyMode": "Bedspace", "beds": [{"slot": "Bed 1", "tenant": None}]}}]
    assert commit(c, a, w)[0] == 200
    r = ask(c, a, "compare boys vs girls", page="admin")
    rows = {x[0]: x for x in r["blocks"][0]["rows"]}
    assert rows["Male"][1:4] == [2, 1, 1] and rows["Female"][1:4] == [1, 0, 1]
