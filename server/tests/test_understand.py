"""Reading the WHOLE message (understand.py): several requests in one message, conditions and negations anywhere in
it, greetings and corrections, honest answers about what the assistant can and cannot do, and long messages that
are reported instead of silently cut."""
from conftest import api, commit
from test_language import T, d, say, setup

import lang
import understand


def setup_more(c):
    """setup() rooms 201 (female), 202 (male), 203 (female whole room) + 204: a male room with a reservation."""
    a = setup(c)
    w = [{"op": "set", "path": ["users", "A", "rooms", "r204"], "data": {
            "room": "204", "capacity": 2, "gender": "Male", "demographic": "Students", "tenancyMode": "Bedspace",
            "beds": [{"slot": "Bed 1", "tenant": None}, {"slot": "Bed 2", "tenant": None, "reservedFor": "p1"}]}},
         {"op": "set", "path": ["users", "A", "prospects", "p1"], "data": {
            "name": "Lito Ramos", "gender": "Male", "demographic": "Student", "checkIn": d(9),
            "reservedBed": {"roomId": "r204", "slot": "Bed 2"}}}]
    assert commit(c, a, w)[0] == 200
    return a


# ------------------------------------------------------------------------------------------- pure functions
def test_split_keeps_conditions_with_their_request_and_separates_real_requests():
    one = ("can u check all the rooms that are vacant and tell me which one can be reserve next week but dont include the rooms that "
           "already have someone coming in and also check the male rooms only")
    assert understand.split(one) == [one]                                   # one request with four conditions
    assert understand.split("how many vacant beds do we have, who is overdue, and how many reservations are coming next week?") == \
        ["how many vacant beds do we have", "who is overdue", "how many reservations are coming next week?"]
    assert len(understand.split("Pila pa ka vacant beds? ug kinsa ang overdue?")) == 2
    assert understand.split("Good morning! Busy day today. First, how many reservations do we have this week? Second, which tenants "
                            "are overdue? And lastly, what is our occupancy rate right now? Thanks!") == \
        ["how many reservations do we have this week?", "which tenants are overdue?", "what is our occupancy rate right now?"]
    for single in ["compare male and female vacancy", "show vacant rooms for male and female students",
                   "check out Miguel Lopez and transfer Luis Cruz to room 202"]:     # two changes: never split
        assert understand.split(single) == [single], single
    assert understand.split("check out Ana Reyes and show me the vacant rooms") == ["check out Ana Reyes", "show me the vacant rooms"]
    assert understand.commands("check out Ana Reyes with a good record and transfer Juan Cruz to room 201") == \
        ["check out Ana Reyes with a good record", "transfer Juan Cruz to room 201"]


def test_negations_are_read_not_ignored():
    t, notes = understand.exclusions(lang.to_english("list vacant rooms except the female rooms"))
    assert "female" not in t and "male" in t and notes
    t, notes = understand.exclusions(lang.to_english("vacant rooms not for students"))
    assert "students" not in t and "reviewees" in t
    t, notes = understand.exclusions(lang.to_english("show vacant beds but not the reserved ones"))
    assert "excluding incoming" not in t and "never counted as vacant" in notes[0]
    t, _ = understand.exclusions(lang.to_english("vacant rooms but dont include the rooms that already have someone coming in"))
    assert t.endswith("excluding incoming")


def test_language_fixes():
    assert lang.to_english("Can you check kung naa pay available rooms?") == "can you check if is there available rooms?"   # "pay" is not money
    assert "vacant" in lang.to_english("Can I still accommodate another tenant?")
    assert lang.to_english("shw me ocupied rms on 2nd flr") == "show me occupied rooms on second floor"
    assert lang.to_english("Pakita lahat ng occupied rooms sa branch.").endswith("in my dorm.")
    assert lang.to_english("add a new tenant") == "add a new tenant"                                  # a command stays a command


def test_greeting_is_answered_together_with_the_request():
    assert understand.greeting("Maayong buntag! pila pa ka bakante?") == ("Good morning!", "pila pa ka bakante?")
    assert understand.greeting("hello") == (None, "hello")


# ------------------------------------------------------------------------------------------- through the assistant
def test_long_request_with_several_conditions(env):
    c, _ = env
    a = setup_more(c)
    r = say(c, a, "can u check all the rooms that are vacant and tell me which one can be reserve next week but dont include the rooms "
                  "that already have someone coming in and also check the male rooms only")
    assert r["intent"] == "vacancy"
    rooms = {row[0] for b in r["blocks"] if b["type"] == "table" for row in b["rows"]}
    assert rooms == {"202"}                         # male, free next week; 204 has Lito Ramos coming in; 201/203 are female
    assert any("reservation or a guest due to arrive" in b.get("text", "") for b in r["blocks"])


def test_except_means_leave_out(env):
    c, _ = env
    a = setup_more(c)
    r = say(c, a, "list vacant rooms except the female rooms")
    assert "202" in r["response"] and "201" not in r["response"] and "203" not in r["response"]
    assert any("female-only rooms" in b.get("text", "") for b in r["blocks"])


def test_several_questions_get_several_answers(env):
    c, _ = env
    a = setup_more(c)
    r = say(c, a, "how many vacant beds do we have, which rooms are occupied, and how many reservations are coming next week?")
    assert r["intent"] == "multi" and r["response"].startswith("You asked three things")
    heads = [b["text"] for b in r["blocks"] if b["type"] == "subheading"]
    assert len(heads) == 3 and heads[1].lower().startswith("which rooms are occupied")
    texts = " ".join(b["text"] for b in r["blocks"] if b["type"] == "text")
    assert "vacant" in texts and "201" in texts and "Reservations next week: 1" in texts
    # saved once, as one exchange (the user's exact words + the combined answer)
    msgs = api(c, "/api/assistant/history", a, {"conversationId": r["conversationId"]})[1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[0]["content"].startswith("how many vacant beds do we have,")
    assert len([b for b in msgs[1]["blocks"] if b["type"] == "subheading"]) == 3


def test_one_change_and_a_question_in_one_message(env):
    c, _ = env
    a = setup_more(c)
    r = say(c, a, "check out Ana Reyes and show me the vacant rooms")
    assert r["action"]["type"] != "none" and "Ana Reyes" in r["response"]           # still needs Confirm
    assert any(b["type"] == "subheading" and "vacant rooms" in b["text"] for b in r["blocks"])
    r = say(c, a, "check out Ana Reyes and transfer Juan Cruz to room 201")
    assert any("asks for 2 changes" in b.get("text", "") and "transfer Juan Cruz" in b["text"] for b in r["blocks"])


def test_greetings_corrections_and_follow_ups(env):
    c, _ = env
    a = setup_more(c)
    r = say(c, a, "hey so for the reviewees only, I need to know which rooms still have a free bed, thanks a lot")
    assert "202" in r["response"] and "Hello, I am" not in r["response"]
    r = say(c, a, "Good morning! how many vacant beds for female?")
    assert r["response"].startswith("Good morning!") and "vacant" in r["response"]
    cid = say(c, a, "show me the vacant rooms for male")["conversationId"]
    r = say(c, a, "no wait, I meant female", cid=cid)
    assert "201" in r["response"] and "202" not in r["response"]
    r = say(c, a, "actually make it whole room", cid=cid)
    assert r["action"]["type"] == "none" and "203" in r["response"] and "201" not in r["response"]


def test_honest_answers_about_what_the_assistant_can_do(env):
    c, _ = env
    a = setup_more(c)
    for q, want in [("Can you read this file?", "can't open files"), ("Do you have access to real-time data?", "at the moment you ask"),
                    ("Can you send an email to the tenants?", "can't send emails"), ("Why can't you understand my message?", "misread"),
                    ("what is the tenant's birthday in room 201?", "doesn't record birthdays")]:
        r = say(c, a, q)
        assert want in r["response"], (q, r["response"])
    r = say(c, a, "what is the weather tomorrow")
    assert r["scope"] == "unrelated" and "no internet access" in r["response"]
    assert say(c, a, "what can you actually do?")["intent"] == "capabilities"
    assert say(c, a, "what do you remember about me")["intent"] == "memory_show"     # the real memory feature, not a speech
    assert "Room 204" in say(c, a, "who is in room 204?")["response"]
    assert "Lito Ramos" in say(c, a, "who is in room 204?")["response"]              # a reservation's name, never its id
    assert "p1" not in say(c, a, "who is in room 204?")["response"]


def test_long_messages_are_read_or_reported(env):
    c, _ = env
    a = setup_more(c)
    chatter = "I was looking at the canvas earlier and things look a bit messy, we had a lot of people move around this month " * 3
    r = say(c, a, chatter + "anyway just tell me the occupancy rate")             # past the old 300-character cut
    assert r["intent"] == "rates"
    r = say(c, a, "how many vacant beds " + "please " * 400)
    assert any("longer than %d characters" % understand.MAX_CHARS in b.get("text", "") for b in r["blocks"])


def test_privacy_still_applies_to_every_part(env):
    c, _ = env
    a = setup_more(c)
    r = say(c, a, "how many vacant beds are there, and who is staying in room 201?", page="viewer")
    assert "Ana Reyes" not in str(r)
