"""The assistant's extra understanding: control words never loop, definitions, real limitations, room-by-room reports,
finding a person (Branch Admin only), commands with details, and screen filters."""
from test_language import T, d, say, setup
from conftest import commit


def test_cancel_always_works_and_never_repeats_the_previous_answer(env):
    c, _ = env
    a = setup(c)
    first = say(c, a, "is a reserved client considered as occupied?")
    assert first["intent"] == "definition" and "counts as occupied" in first["response"]
    cid = first["conversationId"]
    r = say(c, a, "cancel", cid=cid)
    assert r["intent"] == "cancelled" and "Nothing" in r["response"]
    assert say(c, a, "what?", cid=cid)["intent"] == "clarify"
    # a half-finished request stops after two answers it cannot use, instead of asking forever
    say(c, a, "reserve a bed for Lito Ramos", cid=cid)
    assert "didn't catch" in say(c, a, "purple monkey", cid=cid)["response"]
    assert say(c, a, "blue banana", cid=cid)["intent"] == "clarify_cancelled"
    assert say(c, a, "how many vacant beds?", cid=cid)["intent"] in ("live_vacant", "vacancy")


def test_definitions_limitations_and_curiosity(env):
    c, _ = env
    a = setup(c)
    for q, want in [("is vecan is consider occupied", "opposites"), ("is a temporary client considered occupied?", "counts as occupied"),
                    ("is overdue still occupied", "still occupied"), ("what does vacant mean?", "free right now"),
                    ("what is the difference between reserved and temporary?", "Both count as occupied")]:
        r = say(c, a, q)
        assert r["intent"] == "definition" and want in r["response"], (q, r["response"])
    r = say(c, a, "what is your limitaion")
    assert r["intent"] == "limitations" and "Hello, I am" not in r["response"] and r["blocks"]
    assert say(c, a, "what can you do?")["intent"] == "capabilities"
    assert "AI assistant" in say(c, a, "are you a robot?")["response"]
    assert say(c, a, "who are you")["response"].startswith("Hello, I am an AI assistant")
    for page in ("viewer", "marketing"):
        r = say(c, a, "what are your limitations", page=page)
        assert r["intent"] == "limitations" and any("read-only" in x or "can't share" in x or "can't tell" in x for x in r["blocks"][0]["items"])


def test_room_by_room_reports(env):
    c, _ = env
    a = setup(c)
    r = say(c, a, "how many vecant in 201")
    assert r["intent"] == "room_report" and "Room 201 has 2 vacant beds (Bed 2, Bed 3)" in r["response"]
    assert "0 overdue" in say(c, a, "how many overdue in room 201")["response"]
    assert "0 reserved" in say(c, a, "pila ang reserve sa room 202")["response"]
    assert "can't find Room 999" in say(c, a, "how many vacant in room 999")["response"]


def test_finding_a_person_is_for_the_branch_admin_only(env):
    c, _ = env
    a = setup(c)
    r = say(c, a, "is ana present there?")
    assert r["intent"] == "person_search" and "Ana Reyes is here: Room 201, Bed 1" in r["response"]
    assert "not in Tenant History" in say(c, a, "can you find ana reyes in the history?")["response"]
    assert "found nobody" in say(c, a, "is terrins present?")["response"]
    for page in ("viewer", "marketing", "superadmin"):
        r = say(c, a, "is ana present there?", page=page, code="none")
        assert "Ana Reyes" not in r["response"] and "Room 201" not in r["response"], (page, r["response"])
        assert r["intent"] in ("privacy", "clarify", "denied")
        assert say(c, a, "add terrins as a reserve", page=page, code="none")["action"]["type"] == "none"


def test_commands_with_details(env):
    c, _ = env
    a = setup(c)
    r = say(c, a, "can you check out ana reyes right now and give it bad recoerd because it didnot pay the rental")
    assert r["action"]["type"] == "checkout_tenant" and r["action"]["record"] == "bad" and "pay the rental" in r["action"]["reason"]
    first = say(c, a, "check out juan cruz with a bad record")
    assert "reason" in first["response"] and first["action"]["type"] == "none"
    r = say(c, a, "he broke the door", cid=first["conversationId"])
    assert r["action"]["record"] == "bad" and r["action"]["reason"] == "he broke the door"
    r = say(c, a, "can you add terrins as a reserve and choose teh best room and what it next room his chekc in date is today and check our will 2027, female student")
    act = r["action"]
    assert act["type"] == "add_reserve_client" and act["name"] == "Terrins" and act["roomId"] == "r201" and act["slot"] == "Bed 2"
    assert act["checkIn"] == T.isoformat() and act["checkOut"].endswith("2027-12-31") and "Next best" in r["response"]
    r = say(c, a, "add terrins as a temporary client, male, check in today and check out tomorrow, choose the best room")
    assert r["action"]["type"] == "add_temporary_client" and r["action"]["roomId"] == "r202"
    r = say(c, a, "can you add reason to my data transfer because i want to resign")
    assert r["nav"] == {"tab": "transfer", "transferPurpose": "I want to resign"} and r["action"]["type"] == "none"


def test_screen_filters(env):
    c, _ = env
    a = setup(c)
    r = say(c, a, "can you show me only the vecant bed")
    assert r["intent"] == "screen_filter" and r["nav"]["filters"]["status"] == "vacant" and "5 beds in 3 rooms" in r["response"]
    assert say(c, a, "clear the filters")["nav"]["filters"]["status"] == "all"
    assert say(c, a, "show only female rooms that are vacant")["nav"]["filters"] == {"status": "vacant", "gender": "Female", "demographic": "all", "search": ""}


def test_any_wording_works(env):
    """Round 2: the same request in many forms, typos included."""
    c, _ = env
    a = setup(c)
    # who are you / who made this / my name
    for q in ("who you are", "who are you?", "hu u", "what are you"):
        assert say(c, a, q)["response"].startswith("Hello, I am an AI assistant"), q
    first = say(c, a, "what is your limitation")
    assert say(c, a, "who you are", cid=first["conversationId"])["intent"] == "identity"       # not the limitations again
    for q in ("who is teh createor of this website", "who made this app?", "kinsa naghimo ani nga website"):
        assert "Hortelano" in say(c, a, q)["response"] and say(c, a, q)["intent"] == "creator", q
    assert "Nice to meet you, Joy" in say(c, a, "hi my name is joy")["response"]
    assert say(c, a, "what is my name")["response"] == "Your name is Joy."


def test_add_room_scroll_and_named_tab_in_any_wording(env):
    c, _ = env
    a = setup(c)
    # add a room, any order
    r = say(c, a, "can you add room name terin 123 4 capacity and for female revwee")
    act = r["action"]
    assert act["type"] == "create_room" and act["room"] == "TERIN 123" and act["capacity"] == 4 and act["gender"] == "Female" and act["demographic"] == "Reviewees"
    first = say(c, a, "add room")
    assert "name" in first["response"]
    cid = first["conversationId"]
    assert "name" in say(c, a, "for female student capacity of 5", cid=cid)["response"]
    act = say(c, a, "t567", cid=cid)["action"]
    assert act["room"] == "T567" and act["capacity"] == 5 and act["gender"] == "Female" and act["demographic"] == "Students"
    act = say(c, a, "please add new room 301 good for 6 female students")["action"]
    assert act["room"] == "301" and act["capacity"] == 6
    # a half-finished request never leaks into a new chat
    say(c, a, "add room")
    assert say(c, a, "how many vacant beds?")["intent"] in ("live_vacant", "vacancy")
    # scroll and slide
    assert say(c, a, "can you scroll down?")["nav"]["scroll"] == {"dir": "down", "amount": "normal", "target": None}
    assert say(c, a, "please scrool down little bit")["nav"]["scroll"]["amount"] == "little"
    r = say(c, a, "please slied riffght the checkout date")
    assert r["nav"]["scroll"]["dir"] == "right" and r["nav"]["tab"] == "calendar"
    assert say(c, a, "scroll down", page="viewer", code="none")["nav"]["scroll"]["dir"] == "down"
    # the tab that was named
    r = say(c, a, "can you show me teh vecant bed in high waay")
    assert r["nav"]["tab"] == "hallway" and r["nav"]["filters"]["status"] == "vacant"


def test_person_in_any_form_and_their_record(env):
    c, pool = env
    a = setup(c)
    uid = say(c, a, "hi") and None
    r = say(c, a, "can you fnd ana reyes in the room canvas?")
    assert r["intent"] == "person_search" and "Ana Reyes is here" in r["response"] and r["nav"]["filters"]["search"] == "Ana Reyes"
    r = say(c, a, "is reyes ana is present or he akready checkout if checkout can you find it to the hisotry of the tenant?")
    assert "Ana Reyes is present" in r["response"] and "Not checked out yet" in r["response"]
    r = say(c, a, "what is thet record of ana if bad say the reason")
    assert r["intent"] == "person_record" and "no record yet" in r["response"]
    for page in ("viewer", "marketing"):
        r = say(c, a, "what is the record of ana", page=page, code="none")
        assert r["intent"] == "privacy" and "Reyes" not in r["response"]


def test_knows_its_developer_and_talks_like_a_person(env):
    c, _ = env
    a = setup(c)
    for q in ("who is terrrinns hortelano", "do you know terrins hortelano?", "who is the developer of this website"):
        r = say(c, a, q)
        assert r["intent"] == "creator" and "developer" in r["response"] and "help dormitory staff" in r["response"], (q, r["response"])
    assert "help dormitory staff" in say(c, a, "why did terrins create this website")["response"]
    r = say(c, a, "i am terrins hortelano")
    assert "I recognize you" in r["response"] and "developer who created this website" in r["response"]
    assert say(c, a, "hello")["response"].startswith(("Good morning, Mr. Hortelano", "Good afternoon, Mr. Hortelano", "Good evening, Mr. Hortelano"))
    assert "my developer" in say(c, a, "do you recognize me?")["response"]
    assert say(c, a, "is terrins present?")["intent"] == "person_search"          # still a tenant search, not the developer answer
    assert say(c, a, "thank you")["intent"] == "smalltalk"                        # the wording rotates, so only the kind of reply is checked
    assert say(c, a, "how are you")["intent"] == "smalltalk"
    for q, key in [("switch to dark mode", "theme"), ("start the tutorial", "tutorial"), ("mute your voice", "voice"), ("read that again", "repeat"),
                   ("sign me out", "signout"), ("close the chat", "close")]:
        assert key in say(c, a, q)["nav"]["ui"], q
