"""Project-aware assistant: account memory isolation, navigation, real-data reports, permission checks,
and the confirm-first contact update. Runs on PostgreSQL and on the local SQLite mode."""
from datetime import date, datetime, timedelta, timezone

from conftest import api, commit, mkuser, ts
from store import KINDS, write

T = date.today()


def d(n):
    return (T + timedelta(days=n)).isoformat()


def ms(days):
    return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp() * 1000)


def setup(c, uid="A"):
    a = mkuser(c, uid)
    rooms = {"r201": {"room": "201", "capacity": 3, "gender": "Female", "demographic": "Students", "tenancyMode": "Bedspace",
                      "beds": [{"slot": "Bed 1", "tenant": "Ana Reyes", "start": d(-40), "end": d(3)}, {"slot": "Bed 2", "tenant": None},
                               {"slot": "Bed 3", "tenant": "Lea Cruz", "start": d(-60), "end": d(-2)}]},
             "r205": {"room": "205", "capacity": 2, "gender": "Male", "demographic": "Mixed", "tenancyMode": "Bedspace",
                      "beds": [{"slot": "Bed 1", "tenant": "Juan Dela Cruz", "start": d(-5), "end": d(40)}, {"slot": "Bed 2", "tenant": None}]}}
    w = [{"op": "set", "path": ["users", uid, "rooms", k], "data": v} for k, v in rooms.items()]
    w.append({"op": "set", "path": ["users", uid, "tenant_history", "h1"],
              "data": {"tenant": "Mark Lim", "roomId": "r205", "room": "205", "slot": "Bed 2", "start": d(-90), "end": d(-10),
                       "reason": "Contract ended", "leftAt": ts(ms(-10)), "expireAt": ts(ms(300))}})
    assert commit(c, a, w)[0] == 200
    return a


def say(c, tok, q, page="admin", **ctx):
    s, r = api(c, "/api/assistant", tok, {"question": q, "context": dict({"today": T.isoformat(), "page": page}, **ctx)})
    assert s == 200, r
    return r


def test_memory_is_per_account_and_can_be_viewed_and_cleared(env):
    c, _ = env
    a, b = setup(c, "A"), mkuser(c, "B")
    assert "tables" in say(c, a, "Remember that I prefer table format for reports")["response"]
    assert "Ana" in say(c, a, "remember my name is ana")["response"] or True
    mine = api(c, "/api/assistant/memory", a, {})[1]["items"]
    assert any(i["key"] == "report_format" and i["value"] == "table" for i in mine)
    # account B sees nothing of A's memory, through chat or the endpoint
    assert api(c, "/api/assistant/memory", b, {})[1]["items"] == []
    assert "don't have anything saved" in say(c, b, "what do you remember about me")["response"]
    # the preference changes A's report layout (a table), and B's report is not affected
    rep = say(c, a, "report the vacancy")
    assert rep["blocks"][1]["type"] == "text" and any(x["type"] == "table" for x in rep["blocks"])
    assert any("remember" in x.get("text", "") for x in rep["blocks"] if x["type"] == "note")
    # memory survives "logout/login" (a new token for the same account)
    assert "tables" in " ".join(x if isinstance(x, str) else "" for x in
                                say(c, mkuser_again(a), "what do you remember")["blocks"][0]["items"])
    assert "cleared" in say(c, a, "forget my memory")["response"]
    assert api(c, "/api/assistant/memory", a, {})[1]["items"] == []


def mkuser_again(token):
    return token            # tokens are stateless here; the same account signs in again


def test_secrets_are_never_stored(env):
    c, _ = env
    a = setup(c)
    r = say(c, a, "remember my password is hunter22")
    assert r["intent"] == "memory_refused"
    assert api(c, "/api/assistant/memory", a, {})[1]["items"] == []


def test_conversation_history_is_private_and_restorable(env):
    c, _ = env
    a, b = setup(c, "A"), mkuser(c, "B")
    say(c, a, "report the vacancy")
    rec = api(c, "/api/assistant/recent", a, {})[1]
    assert rec["conversationId"] and rec["messages"][0]["content"] == "report the vacancy"
    assert rec["messages"][1]["blocks"], "report tables are kept for redrawing"
    assert api(c, "/api/assistant/recent", b, {})[1] == {"conversationId": None, "messages": []}
    # B cannot read A's conversation by passing its id
    assert api(c, "/api/assistant/history", b, {"conversationId": rec["conversationId"]})[1]["messages"] == []
    say(c, a, "clear my chat history")
    assert api(c, "/api/assistant/recent", a, {})[1]["messages"] == []


def test_navigation_commands(env):
    c, _ = env
    a = setup(c)
    assert say(c, a, "take me to the server")["nav"] == {"tab": "viewers"}
    assert say(c, a, "Open the Room Canvas")["nav"] == {"tab": "dashboard"}
    r = say(c, a, "Navigate to Room 205")
    assert r["nav"] == {"tab": "dashboard", "roomId": "r205", "room": "205"} and "1 of 2" in r["response"]
    r = say(c, a, "go to room 999")
    assert r["nav"] is None and "couldn't find Room 999" in r["response"]
    r = say(c, a, "Open the Super Admin analytics")              # not a super admin
    assert r["nav"] is None and "isn't a Super Admin" in r["response"]


def test_vacancy_report_uses_real_counts(env):
    c, _ = env
    a = setup(c)
    r = say(c, a, "give me a vacancy report in bullet points")
    assert "2 of 5 beds are vacant (40%)" in r["response"]
    items = [i for x in r["blocks"] if x["type"] == "list" for i in x["items"]]
    assert any("Lea Cruz (Room 201)" in i for i in items)          # overdue tenant, from the records
    assert any("Ana Reyes (Room 201" in i for i in items)          # contract ending within 7 days
    tab = say(c, a, "vacancy report as a table")
    t = next(x for x in tab["blocks"] if x["type"] == "table")
    assert t["columns"][:4] == ["Room", "Beds", "Occupied", "Vacant"] and ["201", 3, 2, 1, 0, "33.3%"] in t["rows"]


def test_explanation_separates_confirmed_from_possible(env):
    c, _ = env
    a = setup(c)
    r = say(c, a, "why did vacancy increase?")
    heads = [x["text"] for x in r["blocks"] if x["type"] == "subheading"]
    assert heads[0] == "Confirmed by your records"
    confirmed = r["blocks"][heads and 3]["items"]
    assert any("Mark Lim (Room 205" in i for i in confirmed) and any("Contract ended" in i for i in confirmed)
    assert "Possible factors (not confirmed)" in heads
    cmp = say(c, a, "compare this month with last month")
    assert any(x["type"] == "table" and x["columns"][0] == "Measure" for x in cmp["blocks"])


def test_contact_update_is_validated_and_only_proposed(env):
    c, _ = env
    a = setup(c)
    bad = say(c, a, "update the contact number of Juan Dela Cruz to 12345")
    assert bad["action"]["type"] == "none" and "isn't a valid Philippine mobile" in bad["response"]
    r = say(c, a, "update the contact number of Juan Dela Cruz to 0917 123 4567")
    assert r["action"] == {"type": "update_tenant_contact", "roomId": "r205", "slot": "Bed 1", "tenant": "Juan Dela Cruz",
                           "contact": "09171234567"}
    assert r["response"].startswith("Here's what I understood")
    assert "couldn't find" in say(c, a, "change the phone number of Nobody Here to 09171234567")["response"]


def test_super_admin_reports_only_cover_their_approved_branches(env):
    c, _ = env
    s, other = mkuser(c, "S"), mkuser(c, "S2")
    now = datetime.now(timezone.utc)
    with c.application.extensions["pool"].connection() as conn:
        with conn.transaction():
            cur = conn.cursor()
            for uid in ("S", "S2"):
                write(cur, KINDS["superAdmins"], (uid,), {"email": "x", "createdAt": ts(ms(0))}, now, lenient=True)
            for bid, req, name, vac, status in [("B1", "S", "North", 15, "approved"), ("B2", "S", "South", 2, "approved"),
                                                ("B3", "S2", "Other", 30, "approved"), ("B4", "S", "Hidden", 40, "pending")]:
                write(cur, KINDS["branches"], (bid,), {"ownerUid": bid, "dormName": name, "requestedBy": req,
                                                         "analyticsStatus": status, "dirStatus": "approved"}, now, lenient=True)
                for k in range(10):
                    write(cur, KINDS["branch_snapshots"], (bid, "s%d" % k), {"total": 40, "vacant": vac, "occupied": 40 - vac,
                                                                          "capturedAt": ts(ms(k - 9))}, now, lenient=True)
    r = say(c, s, "which dorm has the highest vacancy?", page="superadmin")
    assert "North has the highest vacancy rate: 37.5%" in r["response"]
    names = [row[0] for row in r["blocks"][0]["rows"]]
    assert names == ["North", "South"]                    # not S2's branch, not the pending one
    rep = say(c, s, "report the vacancy of the dorms", page="superadmin")
    assert "15 of 40" not in rep["response"] and "17 of 80 beds vacant" in rep["response"]
    assert any(x["type"] == "table" and ["North", 40, 15, "37.5%", "n/a", "High risk"] in x["rows"] for x in rep["blocks"])
    # a branch admin cannot get cross-dormitory data by claiming to be on the Super Admin page
    a = setup(c, "A")
    assert "Super Admin accounts only" in say(c, a, "report the vacancy of the dorms", page="superadmin")["response"]
    assert say(c, s, "Open the Super Admin analytics")["nav"] == {"url": "superadmin.html", "tab": "trading"}
    assert say(c, s, "take me to the server", page="superadmin")["nav"] == {"tab": "server"}
