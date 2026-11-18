"""Assistant language understanding (misspellings, Cebuano, Tagalog, Taglish), several filters at once, privacy per role,
honest answers about things the app does not record, and follow-up questions in the same chat."""
from datetime import date, datetime, timedelta, timezone

import lang
from conftest import api, commit, mkuser, ts
from store import KINDS, write

T = date.today()


def d(n):
    return (T + timedelta(days=n)).isoformat()


def test_language_step_turns_local_and_misspelled_questions_into_simple_english():
    cases = {
        "pila pay vacant bed karun": "how many vacant bed now",
        "Naa bay bakante nga kwarto para sa lalaki?": "is there vacant room for male?",
        "May bakanteng kwarto ba para sa babae?": "is there vacant room for female?",
        "Sino ang mga tenant na magche-check out bukas?": "who tenant check out tomorrow?",
        "is there a vecant for the female student bedspacer?": "is there a vacant for the female student bedspace tenants?",
        "Kinsa ang hapit na mahuman ang kontrata?": "who expiring soon contract?",
        "Which branch ang pinaka-low ug occupancy?": "which branch lowest occupancy?",
    }
    for q, want in cases.items():
        assert lang.to_english(q) == want, (q, lang.to_english(q))
    # real words and names are never "corrected"
    assert lang.to_english("Show all recent room changes") == "show all recent room changes"
    assert lang.to_english("which rooms are unavailable for reservation") == "which rooms are unavailable for reservation"
    assert "ana reyes" in lang.to_english("check in Ana Reyes to room 201 until march 1")


def setup(c):
    a = mkuser(c, "A")
    rooms = {
        "r201": {"room": "201", "capacity": 3, "gender": "Female", "demographic": "Students", "tenancyMode": "Bedspace",
                 "beds": [{"slot": "Bed 1", "tenant": "Ana Reyes", "tenantId": "t1", "start": d(-40), "end": d(3), "residentGender": "Female"},
                          {"slot": "Bed 2", "tenant": None}, {"slot": "Bed 3", "tenant": None}]},
        "r202": {"room": "202", "capacity": 2, "gender": "Male", "demographic": "Reviewees", "tenancyMode": "Bedspace",
                 "beds": [{"slot": "Bed 1", "tenant": "Juan Cruz", "tenantId": "t2", "start": d(-5), "end": d(40), "residentGender": "Male"},
                          {"slot": "Bed 2", "tenant": None}]},
        "r203": {"room": "203", "capacity": 2, "gender": "Female", "demographic": "Students", "tenancyMode": "Whole Room",
                 "beds": [{"slot": "Bed 1", "tenant": None}, {"slot": "Bed 2", "tenant": None}]},
    }
    w = [{"op": "set", "path": ["users", "A", "rooms", k], "data": v} for k, v in rooms.items()]
    w.append({"op": "set", "path": ["users", "A", "tenants", "t1"], "data": {"name": "Ana Reyes", "contact": "09171234567", "ec1": None, "ec2": None}})
    w.append({"op": "set", "path": ["users", "A", "tenants", "t2"], "data": {"name": "Juan Cruz", "contact": "", "ec1": {"name": "Pedro", "phone": "09181112222"}}})
    assert commit(c, a, w)[0] == 200
    return a


def say(c, tok, q, cid=None, **ctx):
    s, r = api(c, "/api/assistant", tok, {"question": q, "conversationId": cid, "context": dict({"today": T.isoformat()}, **ctx)})
    assert s == 200, r
    return r


def test_several_filters_at_once_in_any_language(env):
    c, _ = env
    a = setup(c)
    for q in ["is there a vacant for the female student bedspacer?", "naa bay bakante para sa babae nga estudyante bedspacer?",
              "vacnt bedspce for grls students"]:
        r = say(c, a, q)
        assert "Room 201 (Bed 2, Bed 3)" in r["response"], (q, r["response"])
        assert "202" not in r["response"] and "Room 203" not in r["response"]      # male room and whole room left out
    r = say(c, a, "vacant whole room for female students")
    assert "Room 203" in r["response"] and "201" not in r["response"]
    assert "Room 202 (Bed 2)" in say(c, a, "may bakanteng kama ba para sa lalaking reviewee?")["response"]


def test_tenant_details_only_on_the_branch_admin_page(env):
    c, _ = env
    a = setup(c)
    assert "09171234567" in say(c, a, "contact information of tenants in room 201")["blocks"][0]["rows"][0]
    assert "Juan Cruz" in say(c, a, "which tenants have no emergency contact?")["response"] or \
        "Ana Reyes" in str(say(c, a, "which tenants have no emergency contact?")["blocks"])
    for page in ("viewer", "marketing", "superadmin"):
        for q in ["Who lives in room 201?", "kinsa ang nagpuyo sa room 201?", "sino ang nakatira sa 201?", "phone number of the tenants",
                  "Show me another branch's private tenant information."]:
            r = say(c, a, q, page=page, code="test-dorm")
            text = r["response"] + str(r.get("blocks"))
            assert "Ana" not in text and "0917" not in text, (page, q, text)


def test_money_is_never_guessed(env):
    c, _ = env
    a = setup(c)
    for q, page in [("How much revenue did we generate this month?", None), ("Kinsa ang wala pa kabayad?", None),
                    ("Magkano ang renta sa room?", "viewer"), ("Which branch generates the most revenue?", "superadmin")]:
        r = say(c, a, q, page=page) if page else say(c, a, q)
        assert "doesn't record" in r["response"] or "doesn't list" in r["response"] or "doesn't include" in r["response"], (q, r["response"])
        assert "₱" not in r["response"] and "PHP" not in r["response"]


def test_follow_up_questions_use_the_same_chat_only(env):
    c, _ = env
    a = setup(c)
    first = say(c, a, "Pila ang occupied sa room 202?")
    assert "Room 202" in first["response"]
    follow = say(c, a, "Pila pud ang vacant?", cid=first["conversationId"])
    assert follow["response"].startswith("Room 202 has 1 vacant bed")
    # a new chat does not inherit the previous question: it counts the whole dormitory
    assert not say(c, a, "Pila pud ang vacant?")["response"].startswith("Room 202")


def test_questions_are_not_turned_into_changes(env):
    c, _ = env
    a = setup(c)
    for q in ["Can I reserve a bed for tomorrow?", "Show tenants scheduled to check in today.", "A tenant wants to transfer rooms. Which rooms can accommodate them?",
              "Delete all tenant records."]:
        r = say(c, a, q)
        assert r["action"] == {"type": "none"}, (q, r)
    assert "won't delete everything" in say(c, a, "Delete all tenant records.")["response"]


def test_introduction_on_greeting_and_on_the_first_reply_of_a_new_chat(env):
    c, _ = env
    a = setup(c)
    intro = "Hello, I am an AI assistant created by the developer Mr. Hortelano, Terrins. I am here to help you."
    for q in ["Who are you?", "kinsa ka?", "who you are"]:           # the full self-introduction starts with the same sentence
        r = say(c, a, q)
        assert r["response"].startswith(intro) and "Branch Admin page" in r["response"] and r["intro"] is None, q
    for q in ["hi", "hello there", "maayong buntag"]:                # a greeting is a conversation, not the same sentence again
        r = say(c, a, q)
        assert r["intent"] == "greeting" and "Mr. Hortelano, Terrins" in r["response"] and "What is your name?" in r["response"], q
    first = say(c, a, "how many vacant beds?")
    assert first["intro"] == intro and not first["response"].startswith("Hello")
    assert say(c, a, "who leaves this week?", cid=first["conversationId"])["intro"] is None
