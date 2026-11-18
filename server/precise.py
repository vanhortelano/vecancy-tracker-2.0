"""precise.py: extra "brain" rules for the assistant, from the Branch Admin test on 2026-11-16.

Two jobs, both run BEFORE the older layers:
  reword(q)   turns wordings the older rules misread into wordings they answer well
              ("who is checking out" was read as check-IN, "can you count the tenants" as "add a room",
              "can we see …", "can I …", "can you check S-105" …)
  answer(...) answers the questions no older layer could: one person's check-out / check-in date and why
              they left, a room's own settings, bad records, longest / newest tenant, who left in a given
              month, vacant beds in rooms of a given size, a few how-to questions and simple maths.
Everything here reads the caller's OWN records only (Branch Admin page), like expert.person_lookup."""
import re
import threading
from datetime import date, datetime, timezone

import sys

import agent
import precise2 as P2
import precise3 as P3
import smart
from store import KINDS, list_docs

R = agent.reply


def _self():
    """This module, handed to precise2 so it can reuse the helpers here (name matching, history, dates)."""
    return sys.modules[__name__]


def set_tz(ctx):
    """The browser sends tzOffset in minutes, JavaScript style (-480 = UTC+8). Set at the start of EVERY question."""
    try:
        off = int((ctx or {}).get("tzOffset") or 0) if isinstance(ctx, dict) else 0
        TZ.offset = -off if abs(off) <= 840 else 0
    except (TypeError, ValueError):
        TZ.offset = 0


def resolve(conn, uid, q, today):
    """Change requests that need the records first ("extend X by 1 month", "move X to bed 4", "add 2 beds to S-110")."""
    q = P2.resolve(conn, uid, q, today, _self())
    return P3.resolve_more(conn, uid, q, today, _self())


def shape_first(conn, uid, q, today):
    """Hallway shape commands, checked before the page commands ("change cr color to blue" is not the page theme)."""
    t = re.sub(r"\s+", " ", str(q or "").lower()).strip()
    if not re.match(r"^(delete|remove|erase|take out|take away|get rid of|rename|change|edit|update|make|turn|set|colou?r|paint|recolou?r|reshape|move)\b", t):
        return None
    cur = conn.cursor()
    rec = smart.Records(cur, uid)
    return P3.shape_command(cur, uid, rec, t, today, _self())


def fill_pronouns(conn, uid, q, cid):
    """'when does she check out?' -> the person talked about last in this chat."""
    return P3.fill_pronouns(conn, uid, q, cid, _self())


def remember_person(conn, uid, q, answer_text, cid):
    P3.remember_person(conn, uid, q, answer_text, cid, _self())

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
MONTH_RE = r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b"
HOWTO_VERBS = (r"add|create|delete|remove|edit|change|update|extend|move|transfer|check ?in|checkin|check ?out|checkout|reserve|book|cancel|undo|"
               r"print|download|export|save|rename|block|unblock|pause|connect|disconnect|upload|assign|register|use|set ?up|reset")


# ------------------------------------------------------------------------------------------ 1. rewording
def reword(q):
    """q is already lower case, in English, with "can you …" stripped where a known verb follows (expert.command_form)."""
    t = re.sub(r"\s+", " ", str(q or "")).strip()
    if not t:
        return t
    end = "?" if t.endswith("?") else ""
    body = t.rstrip(" ?.!")
    # the spelling fixer turns "checking out" into "checkin out", which then reads as a CHECK-IN question
    body = re.sub(r"\bcheck(?:in|ing|in')\s+out\b", "check out", body)
    body = re.sub(r"\bchecking\s+in\b", "check in", body)
    # "who is check out / whos leaving tomorrow" -> "who will check out tomorrow" (the wording the schedule answer knows)
    body = re.sub(r"^who(?:'s|s| is| are)?\s+(?:check out|leaving|moving out|going out)\b", "who will check out", body)
    # "can we / can i see|view|get|know …" -> "show …"
    body = re.sub(r"^(?:can|could|may)\s+(?:i|we)\s+(?:please\s+)?(?:see|view|get|have|know|check(?![- ]?(?:in|out)\b)|look at)\s+", "show ", body)
    # "can i / can we <do something>?" -> "how do i <do something>"
    body = re.sub(r"^(?:can|could|may)\s+(?:i|we)\s+(?:also\s+|still\s+)?(?=(?:%s)\b)" % HOWTO_VERBS, "how do i ", body)
    # "can you check / see / look at room s-105" (and the same without "can you") -> a room report
    m = re.match(r"^(?:(?:can|could|would|will)\s+(?:you|u)\s+)?(?:please\s+)?(?:see|check|view|look at|inspect|check on)\s+(room\s+[a-z0-9][a-z0-9-]*)$", body)
    if m:
        body = "report " + m.group(1)
    # "(can you) count the tenants" -> "how many tenants" ("count" was taken for the start of "add a room")
    body = re.sub(r"^(?:(?:can|could|would)\s+(?:you|u)\s+)?count\s+(?:the\s+|all\s+|my\s+|our\s+)?", "how many ", body)
    # "who is reserved" -> the reservation list with names
    body = re.sub(r"\bwho(?:'s|s| is| are)\s+reserved\b", "the reservations", body)
    if re.match(r"^(?:show|list|give)(?: me)?\s+the reservations$", body) or body == "the reservations":
        body = "show the reservations"
    # "show (me) the overdue tenants" only opened a tab; the list answer is "list overdue tenants"
    body = re.sub(r"^(?:show|display|give)(?: me)?\s+(?:the\s+|all\s+)?overdue(?:\s+(?:tenants|residents|beds))?$", "list overdue tenants", body)
    # "what is the occupancy rate" gave the formula; the number is what people want
    if re.match(r"^(?:what(?:'s|s| is)|tell me|give me|show(?: me)?)\s+(?:the\s+|our\s+|my\s+|current\s+)*occupancy(?:\s+(?:rate|percentage|percent|level))?(?:\s+(?:now|today|right now))?$", body):
        body = "tell me the occupancy rate"
    # "do you know what a reviewee is / how to add a room" -> the question itself (it was read as "what do you know")
    m = re.match(r"^(?:do|did) (?:you|u) know (?:what|whats) (?:an? |the )?(.+?) (?:is|are|means?)$", body)
    if m:
        body = "what is %s" % m.group(1)
    else:
        body = re.sub(r"^(?:do|did) (?:you|u) know (?=(?:how|what|where|when|why|which|who|whether|if)\b)", "", body)
    # "who are the tenants / my tenants", "names of the tenants" -> the tenant list (it was answered with the privacy notice)
    if re.match(r"^(?:who are|whos|who's|what are the names of|names of|list the names of|give me the names of|show me)\s+(?:the\s+|my\s+|our\s+|all\s+(?:the\s+|my\s+)?)*"
                r"(?:tenants|residents|boarders|people staying|people here)(?:\s+(?:now|right now|here|staying))?$", body):
        body = "list all tenants"
    # "which bed is mae ramos in", "what room is carlo santos staying in" -> "where is mae ramos"
    m = re.match(r"^(?:what|which)\s+(?:room|bed|room and bed)\s+(?:is|does)\s+([a-zñ][a-zñ .'-]+?)\s+(?:in|staying in|staying|sleeping in|stay in|assigned to|using)$", body)
    if m:
        body = "where is %s" % m.group(1)
    # "what is ana rivera's room", "which bed is mae ramos's" -> "where is ana rivera"
    m = re.match(r"^(?:what|which)(?: is|s|'s)? (?:the )?(?!(?:the|a|an)\b)([a-zñ][a-zñ .-]+?)(?:'s|s)? (?:room|bed|room number|bed number|room and bed)$", body)
    if m and not re.search(r"\b(vacant|free|empty|full|biggest|largest|smallest|best|first|last|next|this|that|my|our|your|whole|private|shared|"
                           r"bed ?space\w*|aircon\w*|ac|non-ac|male|female|mixed|students?|reviewees?|type|kind|new|old|temporary|reserved)\b", m.group(1)):
        body = "where is %s" % m.group(1)
    # "who in room s-101" (from "sino ang nasa S-101") -> "who is in room s-101"
    body = re.sub(r"^(who|whos)\s+(?:in|inside|at)\s+(room\s+\S+)$", r"who is in \2", body)
    # "make S-107 a male room", "turn S-110 into an aircon room" -> "change room s-107 to male" (was read as "create a room")
    m = re.match(r"^(?:make|turn|convert|set)\s+(room\s+[a-z0-9][a-z0-9-]*)\s+(?:into\s+|to\s+|as\s+)?(?:an?\s+)?"
                 r"(male|female|mixed|students?|reviewees?|aircon|ac|air-?conditioned|non-?ac|non-?aircon|whole room|private|bed ?space)"
                 r"(?:\s+(?:room|only|rooms))?$", body)
    if m:
        body = "change %s to %s" % (m.group(1), m.group(2))
    # "any problems?", "anything I should know?" -> the attention list
    if re.match(r"^(?:are there |is there |do we have |do i have )?(?:any |some )?(?:problems?|issues?|concerns?|anything wrong|things? i should (?:know|check)|"
                r"anything (?:i should|to) (?:know|check|worry)(?: about)?|what needs (?:my )?attention|what should i (?:check|worry about))"
                r"(?: (?:i|that i) should know about| today| right now| in (?:the|my) dorm)?$", body):
        body = "what should i do today"
    return body + end


def _checkin_reserved_now(cur, uid, rec, t, today):
    """'check in Bianca Bautista now': a reserved client is checked in automatically at the check-in time; there is no
    'check in early' button, so say exactly what will happen and how to do it sooner."""
    if not re.match(r"^(?:check ?in|checkin|move in)\s+(.+?)(?:\s+(?:now|today|right now|immediately|early|earlier|na))?$", t):
        return None
    name_part = re.match(r"^(?:check ?in|checkin|move in)\s+(.+?)(?:\s+(?:now|today|right now|immediately|early|earlier|na))?$", t).group(1)
    if re.search(r"\b(room|bed|in|into|to|at)\b", name_part):
        return None                                    # "check in Ana in room S-101 bed 4" is a normal check-in request
    hits = _find_people(name_part, [("reserved", p.get("name"), p) for p in rec.prospects if not p.get("checkedIn") and not p.get("checkedOut")])
    if not hits:
        return None
    p = hits[0][2]
    rb = p.get("reservedBed") or {}
    room = rec.room(rb.get("roomId")) if rb.get("roomId") else None
    if not room:
        return R("checkin_reserved", "%s is a reserved client without a bed yet (check-in %s). Reserve a bed for them first, or check them in "
                 "on any vacant bed: press Check in on the bed and enter their name and dates." % (p.get("name"), _dt(p.get("checkIn")) or "not set"),
                 nav={"tab": "reserve"})
    return R("checkin_reserved",
             "%s already has Room %s, %s reserved, and the app checks them in automatically on %s. There is no button to check a reserved client "
             "in early. To move them in today instead: in Reserved Clients press Undo on their card (this frees the bed but keeps them on the list), "
             "then press Check in on Room %s, %s and enter their name and dates." % (
                 p.get("name"), room.get("room"), rb.get("slot"), _dt(p.get("checkIn")) or "their check-in date", room.get("room"), rb.get("slot")),
             nav={"tab": "reserve"}, suggestions=["Show the reservations"])


# ------------------------------------------------------------------------------------------ helpers
def _dt(v):
    """'2026-11-18T12:00' -> 'Nov 18, 2026 at 12:00 PM'; '2026-11-18' -> 'Nov 18, 2026'."""
    s = str(v or "")
    d = smart.parse_iso(s[:10])
    if not d:
        return None
    text = smart.pretty(d)
    m = re.match(r"^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})", s)
    if m and not s.endswith("Z"):
        h, mi = int(m.group(1)), int(m.group(2))
        text += " at %d:%02d %s" % ((h % 12) or 12, mi, "AM" if h < 12 else "PM")
    return text


TZ = threading.local()                                 # .offset: minutes to ADD to UTC for the user's local time (per request thread)


def _ts(v):
    """A saved time -> the user's LOCAL date (a check-out at 1 AM in Manila is still the same day there)."""
    try:
        if isinstance(v, dict) and "__ts" in v:
            v = v["__ts"]
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 + getattr(TZ, "offset", 0) * 60, timezone.utc).date()
        if isinstance(v, str):
            return smart.parse_iso(v[:10])
    except Exception:
        return None
    return None


def _days(n):
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n == -1:
        return "yesterday"
    return ("in %d days" % n) if n > 0 else ("%d days ago" % -n)


def _history(cur, uid):
    try:
        return [dict(d, id=i) for i, d, _v in list_docs(cur, KINDS["tenant_history"], [uid], limit=5000)]
    except Exception:
        return []


def _words(text):
    return re.findall(r"[a-zñ]+", (text or "").lower())


def _mentions(t, name):
    """True when the text names this person: the whole name, or every word of a 2+ word name."""
    words = _words(name)
    if not words:
        return False
    tw = set(_words(t))
    tw |= {w[:-1] for w in tw if len(w) > 3 and w.endswith("s")}     # "ana riveras check out" (the apostrophe was dropped)
    full = " ".join(words)
    if re.search(r"(?<![a-zñ])%s(?:'?s)?(?![a-zñ])" % re.escape(full), " ".join(_words(t))):
        return True
    return len(words) >= 2 and all(w in tw for w in words)


COMMON = set("""will when what who why how the and for are you can did does was has have not now new old all any out off
our my your his her its this that there here room rooms bed beds tenant tenants date time left leave leaving check checkin checkout
long longest stay stayed staying record records bad good reason which where until month week today tomorrow""".split())


def _people(rec, hist):
    """[(kind, name, data)] kind: now | reserved | history."""
    out = [("now", b.get("tenant"), (r, i, b)) for r, i, b in rec.occupied()]
    out += [("reserved", p.get("name"), p) for p in rec.prospects if not p.get("checkedIn")]
    out += [("history", h.get("tenant"), h) for h in hist]
    return [p for p in out if p[1]]


def _find_people(t, people):
    hits = [p for p in people if _mentions(t, p[1])]
    if hits:
        return hits
    # first name only, when exactly one person has it and it is not an everyday word
    tw = [w for w in _words(t) if len(w) >= 3 and w not in COMMON]
    for w in tw:
        same = [p for p in people if _words(p[1]) and _words(p[1])[0] == w]
        if same and len({p[1].lower() for p in same}) == 1:
            return same
    return []


# ------------------------------------------------------------------------------------------ 2. answers
def answer(conn, uid, q, today, ctx=None, page="admin"):
    t = re.sub(r"\s+", " ", str(q or "").lower()).strip()
    if not t:
        return None
    set_tz(ctx)
    r = _maths(t) or P2.app_facts(t) or (P2.can_you_change(t) if page in (None, "", "admin") else None)
    if r:
        return r
    if page not in (None, "", "admin"):
        try:                                           # "do you know Katilana?" on a page without names
            return P2.know_person(conn, uid, None, t, today, _self(), page)
        except Exception:
            return None
    for fn in (_howto, _gender_rule):
        r = fn(t)
        if r:
            return r
    cur = conn.cursor()
    rec = None
    me = _self()
    steps = [lambda c, u, rc, tt, td: P3.rename_room(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P3.temp_checkout(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P3.shape_command(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P3.room_size(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P3.bed_tenant(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P2.person_facts(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P3.who_named(conn, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P2.know_person(conn, u, rc, tt, td, me, page),
             _person_dates, _room_settings, _bad_records, _longest_newest, _left_in_month, _vacant_by_size,
             lambda c, u, rc, tt, td: P2.counts(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P2.ranks(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P2.compare_groups(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P2.rates(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P2.move_same_room(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P2.avg_stay(c, u, rc, tt, td, me),
             lambda c, u, rc, tt, td: P2.ranges(c, u, rc, tt, td, me),
             _checkin_reserved_now]
    for fn in steps:
        try:
            if rec is None:
                rec = smart.Records(cur, uid)
            r = fn(cur, uid, rec, t, today)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("precise answer %s failed", fn.__name__)
            r = None
        if r:
            return r
    return None


def _maths(t):
    if re.match(r"^(?:what(?:'s|s| is)\s+|calculate\s+|compute\s+|solve\s+)?-?\d+(?:\.\d+)?\s*(?:[-+*/x×÷]|plus|minus|times|multiplied by|divided by)\s*-?\d+(?:\.\d+)?\s*[?=]*$", t):
        return R("offtopic", "I only help with this Vacancy Tracker, so I don't do general maths. Ask me about your rooms, beds, tenants, "
                 "reservations or check-outs, like “what is the occupancy rate?”.")
    return None


ASK_HOW = r"^(?:how (?:do|can|should|would) (?:i|we|you)|how to|how do you|what are the steps to|steps to|paano|unsaon)\b"


def _howto(t):
    if not re.search(ASK_HOW, t):
        return None
    if re.search(r"\b(undo|reverse|take back|cancel|revert)\b.*\bcheck ?out\b|\bcheck ?out\b.*\b(undo|reverse|by mistake|wrong)\b", t):
        return R("howto_undo_checkout",
                 "A check-out can't be undone. The stay is already saved in Tenant History. If you checked someone out by mistake, check them in again: "
                 "press Check in on a vacant bed (their old bed if it's still free) and enter their name and dates.",
                 suggestions=["How do I check in a tenant?", "Open Tenant History"])
    if re.search(r"\b(print|download|export|save (it |this |the \w+ )?as (a )?pdf|pdf|excel|csv)\b", t):
        return R("howto_print",
                 "Say “print this page” and I'll open the print window, or press Ctrl+P (Cmd+P on a Mac). To keep a file, choose “Save as PDF” in "
                 "the print window. There is no separate download or export button. For a report, ask me “give me a vacancy report” first, then print.",
                 suggestions=["Give me a vacancy report", "Print this page"])
    if re.search(r"\bcheck ?in\b|\bcheckin\b", t) and not re.search(r"\bcheck ?out\b", t):
        text = ("On a vacant bed press Check in (it opens the room editor). Type the tenant's name, choose the resident group and gender, set the check-in "
                "and check-out dates, then press Save room.")
        if re.search(r"\b(reserv\w*|prospect|client)\b", t):
            text += (" A reserved client is checked in automatically: when their check-in time comes and the bed is free, the bed turns Occupied and "
                     "they leave the Reserved list.")
        else:
            text += " For someone arriving later, add them under Reserved Clients so the bed is held and they're checked in automatically."
        if re.search(r"\b(early|earlier|ahead|before)\b", t):
            text += (" To move someone in earlier than planned, edit their check-in date (on the reserved client card, or in the room editor) to today.")
        return R("howto_check_in", text, suggestions=["Who is checking in this week?", "Show the vacant beds"])
    return None


def _gender_rule(t):
    m = re.match(r"^(?:can|could|may|is it (?:ok|okay|possible|allowed)(?: for)?|are)\s+(?:a |an )?(male|female|boy|girl|man|woman|men|women|males|females|boys|girls)s?\b"
                 r".*\b(male|female|mixed|boys?|girls?)(?:'s)?\s+(?:room|rooms|dorm)\b", t)
    if not m:
        return None
    norm = {"boy": "Male", "man": "Male", "men": "Male", "male": "Male", "males": "Male", "boys": "Male",
            "girl": "Female", "woman": "Female", "women": "Female", "female": "Female", "females": "Female", "girls": "Female"}
    who, room = norm.get(m.group(1)), {"mixed": "Mixed"}.get(m.group(2)) or norm.get(m.group(2))
    if room == "Mixed" or who == room:
        text = "Yes. A %s room accepts %s residents." % (room, "both male and female" if room == "Mixed" else who.lower())
    else:
        text = ("No. A %s room only accepts %s residents. The app blocks putting a %s resident there, and that includes temporary guests. %s residents "
                "can stay in %s or Mixed rooms." % (room, room.lower(), who.lower(), who, who))
    return R("gender_rule", text, suggestions=["Are there free beds for a %s?" % (who or "female").lower()])


OUT_WORDS = r"\b(check[- ]?out|checks out|leav\w*|move out|moving out|moves out|end date|contract end\w*|until when|stay(?:ing)? until|depart\w*|due|aalis|mobiya)\b"
IN_WORDS = r"\b(check[- ]?in|checks in|arriv\w*|com(?:e|es|ing) in|move in|moving in|moves in|start date|start\w*|dating)\b"
WHY_WORDS = r"\b(why|reason|what happened)\b"
QUESTION = r"^(when|what|whats|what's|why|until|kailan|is|does|did|do|has|how long|tell me|give me|show|find|check if|which date)\b|\bwhen\b|\?$"


def _person_dates(cur, uid, rec, t, today):
    want_out, want_in, want_why = re.search(OUT_WORDS, t), re.search(IN_WORDS, t), re.search(WHY_WORDS, t)
    if not (want_out or want_in or want_why) or not re.search(QUESTION, t):
        return None
    if re.search(r"\b(who|everyone|all|list|how many|tenants|residents|people|clients)\b", t) and not re.search(r"\b(named|called)\b", t):
        return None                                    # about many people: the schedule answers do that
    hist = _history(cur, uid)
    hits = _find_people(t, _people(rec, hist))
    if not hits:
        # "when does Juan Cruz check out" with nobody of that name: say so instead of listing everyone
        m = re.search(r"^(?:when|why|until when|kailan)\s+(?:does|do|did|is|will|was)\s+(?:si\s+)?([a-zñ]+(?:\s+[a-zñ]+){0,2}?)(?:'?s)?\s+(?:check|leav|left|arriv|com|mov|stay|depart)", t)
        if m and not any(w in COMMON for w in m.group(1).split()):
            typed = " ".join(w.capitalize() for w in m.group(1).split())
            return R("person_search", "I couldn't find anyone named “%s” in your tenants, reserved clients or Tenant History. Check the spelling, "
                     "or ask “who checks out this week?” to see the list." % typed, suggestions=["Who checks out this week?", "List all tenants"])
        return None
    name = hits[0][1]
    now = [h for h in hits if h[0] == "now"]
    res = [h for h in hits if h[0] == "reserved"]
    old = sorted([h for h in hits if h[0] == "history"], key=lambda h: _ts(h[2].get("leftAt")) or date(1970, 1, 1), reverse=True)
    lines, nav = [], None
    if want_why or (re.search(r"\b(left|leave)\b", t) and re.search(r"\b(did|why|when)\b", t) and old and not now):
        if old:
            h = old[0][2]
            left = _ts(h.get("leftAt"))
            rec_txt = {"good": " They left with a good record.",
                       "bad": " They left with a BAD record: %s." % (h.get("recordReason") or "no reason written")}.get(h.get("record"), "")
            lines.append("%s left Room %s, %s%s. Reason: %s.%s" % (h.get("tenant"), h.get("room"), h.get("slot"),
                                                                    (" on " + smart.pretty(left)) if left else "", h.get("reason") or "not written", rec_txt))
            nav = {"tab": "history"}
        elif now:
            r, i, b = now[0][2]
            lines.append("%s hasn't left. They are staying in Room %s, %s, until %s." % (b.get("tenant"), r.get("room"), smart.bed_label(b, i),
                                                                                       _dt(b.get("end")) or "no end date"))
        else:
            return None
    else:
        if want_out or not want_in:
            if now:
                for r, i, b in [h[2] for h in now[:3]]:
                    end = smart.parse_iso(b.get("end"))
                    if not end:
                        lines.append("%s (Room %s, %s) has no check-out date set." % (b.get("tenant"), r.get("room"), smart.bed_label(b, i)))
                    elif end < today:
                        lines.append("%s was due to check out on %s (%s) and is still in Room %s, %s, so the stay is overdue. Extend it or check them out." % (
                            b.get("tenant"), _dt(b.get("end")), _days((end - today).days), r.get("room"), smart.bed_label(b, i)))
                    else:
                        lines.append("%s checks out on %s (%s), from Room %s, %s." % (b.get("tenant"), _dt(b.get("end")), _days((end - today).days),
                                                                                    r.get("room"), smart.bed_label(b, i)))
                r0 = now[0][2][0]
                nav = {"tab": "dashboard", "roomId": r0["id"]}
            elif res:
                p = res[0][2]
                lines.append("%s hasn't arrived yet. They are a reserved client: check-in %s, check-out %s." % (
                    p.get("name"), _dt(p.get("checkIn")) or "not set", _dt(p.get("checkOut")) or "not set"))
                nav = {"tab": "reserve"}
            elif old:
                h = old[0][2]
                left = _ts(h.get("leftAt"))
                lines.append("%s already checked out%s (Room %s, %s). Reason: %s." % (h.get("tenant"), (" on " + smart.pretty(left)) if left else "",
                                                                                   h.get("room"), h.get("slot"), h.get("reason") or "not written"))
                nav = {"tab": "history"}
        if want_in:
            if res:
                p = res[0][2]
                rb = p.get("reservedBed") or {}
                room = rec.room(rb.get("roomId")) if rb.get("roomId") else None
                ci = smart.parse_iso(p.get("checkIn"))
                where = (" into Room %s, %s (the bed is held)" % (room.get("room"), rb.get("slot"))) if room else " (no bed chosen yet)"
                lines.append("%s checks in on %s%s%s." % (p.get("name"), _dt(p.get("checkIn")) or "a date not set yet",
                                                         (" (%s)" % _days((ci - today).days)) if ci else "", where))
                nav = nav or {"tab": "reserve"}
            elif now:
                r, i, b = now[0][2]
                lines.append("%s already checked in on %s (Room %s, %s)." % (b.get("tenant"), _dt(b.get("start")) or "a date not saved",
                                                                            r.get("room"), smart.bed_label(b, i)))
                nav = nav or {"tab": "dashboard", "roomId": r["id"]}
            elif old:
                h = old[0][2]
                lines.append("%s stayed from %s to %s and has checked out." % (h.get("tenant"), _dt(h.get("start")) or "?", _dt(h.get("end")) or "?"))
                nav = nav or {"tab": "history"}
    if not lines:
        return None
    if len(now) > 1:
        lines.append("There are %d people with that name staying now." % len(now))
    return R("person_dates", " ".join(lines), nav=nav, suggestions=["Where is %s?" % name, "Contact details of %s" % name])


ATTR = [("gender", r"\b(gender|male or female|female or male|boys? or girls?|for (boys|girls|males?|females?|men|women)|is it (a )?(male|female|mixed))\b|"
                   r"\b(male|female|mixed) (room|only)\b|\bis room \S+ (a )?(male|female|mixed)\b"),
        ("ac", r"\b(aircon\w*|air ?con\w*|air-con\w*|ac|a/c|air[- ]conditioned|air conditioning|aircondition)\b"),
        ("type", r"\b(what )?type\b|\b(bed ?space\w*|whole room|tenancy)\b|\bkind of room\b"),
        ("group", r"\b(group|zoning|demographic|students? or reviewees?|reviewees? or students?|for (students?|reviewees?))\b"),
        ("capacity", r"\b(capacity|how many beds (does|do|is|in)|size|how big|beds does)\b"),
        ("all", r"\b(settings?|details?|info\w*|describe|setup)\b")]


def _yes(v):
    return v is True or str(v).strip().lower() in ("true", "yes", "1", "on")


def _room_settings(cur, uid, rec, t, today):
    if re.match(r"^(set|change|make|turn|mark|update|edit|switch|convert|put|add|remove|rename|create|new|build|register|delete)\b", t):
        return None                                    # "set S-110 to aircon" is a change request, answered by smart.py
    if re.search(r"\b(vacan\w*|free|available|occupied|who|whose|names?|how many (vacant|free|tenants|people)|reserv\w*|overdue)\b", t):
        return None
    wanted = [k for k, p in ATTR if re.search(p, t)]
    if not wanted:
        return None
    import expert
    refs = expert._rooms_in(t, rec)
    if not refs:
        return None
    room, tok = refs[0]
    if room is None:
        return R("room_missing", "I can't find Room %s in your records." % tok.upper())
    g = room.get("gender") or "Mixed"
    grp = room.get("demographic") or "Mixed"
    ac = _yes(room.get("ac"))
    cap = room.get("capacity") or len(room.get("beds") or [])
    mode = room.get("tenancyMode") or "Bedspace"
    name = "Room %s" % room.get("room")
    lead = []
    for k in wanted:
        if k == "gender":
            lead.append("%s is a %s room%s." % (name, g, " (male and female)" if g == "Mixed" else " (%s residents only)" % g.lower()))
        elif k == "ac":
            lead.append("%s, %s %s aircon." % ("Yes" if ac else "No", name, "has" if ac else "has no"))
        elif k == "type":
            lead.append("%s is a %s, rented as %s." % (name, room.get("type") or "Room", mode))
        elif k == "group":
            lead.append("%s is for %s." % (name, "students and reviewees (Mixed)" if grp == "Mixed" else grp.lower()))
        elif k == "capacity":
            lead.append("%s has %d beds." % (name, cap))
    summary = "%s: %s, %s, %s, %s, %d beds." % (name, g, grp, mode, "aircon" if ac else "no aircon", cap)
    text = (" ".join(dict.fromkeys(lead)) + " " + summary) if lead else summary
    return R("room_settings", text.strip(), nav={"tab": "dashboard", "roomId": room["id"]},
             suggestions=["Who is in %s?" % name, "How many vacant beds in %s?" % name])


def _bad_records(cur, uid, rec, t, today):
    m = re.search(r"\b(bad|good)\s+records?\b|\bblack ?list\w*\b", t)
    if not m or re.search(r"^how (do|can|to)|\b(what is|what's|whats|mean\w*|give (a|him|her|them))\b", t):
        return None
    if not re.search(r"\b(who|which|list|show|any|all|tenants?|people|names?|everyone|how many)\b", t):
        return None
    kind = "good" if m.group(1) == "good" else "bad"
    hist = _history(cur, uid)
    named = _find_people(t, [("history", h.get("tenant"), h) for h in hist])
    if named and not re.search(r"\b(who|which|list|all|everyone|how many)\b", t):
        return None                                    # "does X have a bad record" is answered by person_lookup
    rows = sorted([h for h in hist if h.get("record") == kind], key=lambda h: _ts(h.get("leftAt")) or date(1970, 1, 1), reverse=True)
    if not rows:
        return R("records_list", "Nobody in Tenant History has a %s record." % kind, nav={"tab": "history"})
    table = [[h.get("tenant"), "Room %s, %s" % (h.get("room"), h.get("slot")), smart.pretty(_ts(h.get("leftAt"))) if _ts(h.get("leftAt")) else "—",
              h.get("recordReason") or ("—" if kind == "good" else "no reason written")] for h in rows]
    names = "; ".join("%s (%s)" % (r[0], r[3]) if kind == "bad" else r[0] for r in table[:6])
    text = "%d %s with a %s record in Tenant History: %s%s." % (len(rows), "person" if len(rows) == 1 else "people", kind, names,
                                                               " and %d more" % (len(rows) - 6) if len(rows) > 6 else "")
    return R("records_list", text, [{"type": "table", "columns": ["Name", "Was in", "Left", "Reason" if kind == "bad" else "Note"], "rows": table}],
             nav={"tab": "history"}, suggestions=["Who moved out last month?"])


def _longest_newest(cur, uid, rec, t, today):
    longest = re.search(r"\b(longest|stayed (the )?long\w*|been here (the )?long\w*|oldest (tenant|resident)|staying the longest|most senior)\b", t)
    newest = re.search(r"\b(newest|latest|most recent(ly)?|last (person|tenant) (to )?(check(ed)? ?in|arriv\w*|mov\w* in)|just (moved|checked) in)\b", t)
    if not (longest or newest) or re.search(r"\b(reserv\w*|history|left|checked out|moved out)\b", t):
        return None
    if not re.search(r"\b(who|which|tenant|resident|person|people|list|show|whos|who's)\b", t):
        return None
    people = [(smart.parse_iso(b.get("start")), r, i, b) for r, i, b in rec.occupied() if smart.parse_iso(b.get("start"))]
    if not people:
        return R("tenants_stay", "None of your current tenants has a check-in date saved, so I can't tell.")
    people.sort(key=lambda p: p[0], reverse=bool(newest and not longest))
    top = people[:5]
    d0, r0, i0, b0 = top[0]
    days = (today - d0).days
    if newest and not longest:
        text = "The newest tenant is %s, checked in %s (%s), in Room %s, %s." % (b0.get("tenant"), smart.pretty(d0), _days(-days) if days else "today",
                                                                             r0.get("room"), smart.bed_label(b0, i0))
    else:
        text = "%s has stayed the longest: since %s, %d days (about %.1f months), in Room %s, %s." % (
            b0.get("tenant"), smart.pretty(d0), days, days / 30.44, r0.get("room"), smart.bed_label(b0, i0))
    rows = [[b.get("tenant"), "Room %s, %s" % (r.get("room"), smart.bed_label(b, i)), smart.pretty(d), "%d days" % (today - d).days] for d, r, i, b in top]
    return R("tenants_stay", text, [{"type": "table", "columns": ["Tenant", "Where", "Checked in", "Staying"], "rows": rows}],
             nav={"tab": "dashboard", "roomId": r0["id"]})


def _left_in_month(cur, uid, rec, t, today):
    if not re.search(r"\b(left|leave|checked out|check ?outs?|moved out|departed|departures?)\b", t):
        return None
    m = re.search(MONTH_RE, t)
    if not m or re.search(r"\b(will|next|coming|upcoming|going to|scheduled)\b", t):
        return None
    if not re.search(r"\b(who|how many|list|show|which|number|count|tenants|people)\b", t):
        return None
    mon = next(i for i, name in enumerate(MONTHS, 1) if name.startswith(m.group(1)[:3]))
    past = re.search(r"\b(left|checked out|moved out|departed|did|was|were)\b", t)
    if not past and mon > today.month and not re.search(r"\b20\d\d\b", t):
        return None                                    # "check-outs in December" (still to come): the period answers do that
    y = re.search(r"\b(20\d\d)\b", t)
    year = int(y.group(1)) if y else (today.year if mon <= today.month else today.year - 1)
    if year == today.year and mon > today.month:
        return None                                    # a future month: the schedule answers that
    hist = _history(cur, uid)
    rows = sorted([h for h in hist if (_ts(h.get("leftAt")) or date(1970, 1, 1)).timetuple()[:2] == (year, mon)],
                  key=lambda h: _ts(h.get("leftAt")))
    label = "%s %d" % (MONTHS[mon - 1].capitalize(), year)
    if not rows:
        return R("tenants_left", "Nobody checked out in %s." % label, nav={"tab": "history"})
    table = [[h.get("tenant"), h.get("room"), smart.pretty(_ts(h.get("leftAt"))), h.get("reason") or "—"] for h in rows]
    text = "%d %s checked out in %s: %s." % (len(rows), "tenant" if len(rows) == 1 else "tenants", label,
                                            "; ".join("%s (%s)" % (r[0], r[3]) for r in table[:6]) + (" and %d more" % (len(rows) - 6) if len(rows) > 6 else ""))
    return R("tenants_left", text, [{"type": "table", "columns": ["Tenant", "Room", "Left", "Reason"], "rows": table}], nav={"tab": "history"})


def _vacant_by_size(cur, uid, rec, t, today):
    if not re.search(r"\b(vacan\w*|free|available|empty|open)\b", t):
        return None
    m = re.search(r"\b(?:with|of|has|having)\s+(\d{1,2})\s+beds?\b|\b(\d{1,2})[- ]?(?:bed|beds|bedder)(?:ed)?\s+rooms?\b", t)
    if not m or re.search(r"\broom\s+[a-z]?-?\d", t.replace(m.group(0), "")):
        return None
    n = int(m.group(1) or m.group(2))
    gender = "Male" if re.search(r"\b(male|boys?|men)\b", t) else "Female" if re.search(r"\b(female|girls?|women|ladies)\b", t) else None
    import expert
    rows, total = [], 0
    for r in rec.rooms:
        if len(r["beds"]) != n:
            continue
        g = r.get("gender") or "Mixed"
        if gender and g not in (gender, "Mixed"):
            continue
        free = [smart.bed_label(b, i) for i, b in enumerate(r["beds"]) if expert.bed_status(r, b, today) == "vacant"]
        if free:
            total += len(free)
            rows.append([r.get("room"), len(free), n, ", ".join(free), g, r.get("demographic") or "Mixed"])
    who = (" for %s residents" % gender.lower()) if gender else ""
    if not rows:
        return R("vacancy_size", "No. There are no vacant beds%s in %d-bed rooms right now." % (who, n))
    text = "Yes: %d vacant bed%s%s in %d-bed rooms: %s." % (total, "" if total == 1 else "s", who, n,
                                                          "; ".join("Room %s (%s)" % (r[0], r[3]) for r in rows[:8]))
    if gender and any(r[4] == "Mixed" for r in rows):
        text += " Rooms marked Mixed take both male and female residents."
    return R("vacancy_size", text, [{"type": "table", "columns": ["Room", "Vacant", "Beds", "Which beds", "Gender", "Group"], "rows": rows}])
