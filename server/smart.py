"""Smarter Dorm Assistant layer (runs before the intent model in ai.py).

What it adds, using ONLY the signed-in user's own SQL records:
  * understands the screen the person is on and what they last clicked (sent by the browser as a
    hint; every id is re-checked against the user's own records here),
  * answers questions about the records (who is in a room, where is a tenant, who leaves this week,
    vacant beds for women, reservations, guests, a quick summary...),
  * turns requests into ONE proposed change ("check in Ana to room 201 until March 1"). It never
    writes. It first restates what it understood, the browser shows Confirm / Cancel, and only a
    confirmed change is applied through the app's normal, validated workflow,
  * asks a clear follow-up question when something is missing, and remembers the half-finished
    request (in ai_config) so the next answer can complete it.
Anything it does not recognise falls through to the trained intent model, unchanged.
"""
import json
import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dbcompat import Jsonb
from store import KINDS, list_docs

DRAFT_MINUTES = 15
INTENTS_FILE = Path(__file__).resolve().parent.parent / "intents.json"
TAB_LABELS = {"dashboard": "Room Canvas", "reminders": "Checkout Reminders", "hallway": "Hallway Layout",
              "analytics": "Analytics", "matrix": "Bed Matrix", "calendar": "Checkout Schedule",
              "reserve": "Reserved Clients", "temporary": "Temporary Dorm Clients", "history": "Tenant History",
              "viewers": "Viewer Access", "central": "Central Link", "transfer": "Data Transfer"}
TAB_HELP_TAG = {"dashboard": "bed_colors", "reminders": "overdue", "hallway": "hallway", "analytics": "analytics",
                "matrix": "bed_matrix", "calendar": "checkout_schedule", "reserve": "reserve_client",
                "temporary": "temporary_clients", "history": "tenant_history", "viewers": "viewer_setup",
                "central": "central_link", "transfer": "data_transfer"}
TAB_TIPS = {"dashboard": ["Who is in this room?", "Check in a tenant here", "Which rooms have vacant beds?"],
            "reminders": ["Who is overdue?", "Who leaves this week?"],
            "calendar": ["Who leaves this week?", "Who leaves this month?"],
            "reserve": ["Show my reservations", "Reserve a bed for a new client"],
            "temporary": ["Show temporary guests", "Add a temporary guest"],
            "analytics": ["Give me a summary", "Which rooms are full?"],
            "matrix": ["Vacant beds for female students", "Who leaves this week?"],
            "hallway": ["Add a facility called Laundry", "Explain this tab"],
            "history": ["Explain this tab", "Give me a summary"]}

MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
NAME_STOP = set("""in into to at on from until till til starting start since for room bed male female man woman boy girl
student students reviewee reviewees mixed tomorrow today tonight next this that who with and by as please pls now
check checkin checkout out up the a an is be will stays stay staying arriving arrives leave leaves leaving until
monday tuesday wednesday thursday friday saturday sunday jan feb mar apr may jun jul aug sep oct nov dec
january february march april june july august september october november december end here there it this that""".split())
TENANT_STOP = NAME_STOP | set("tenant resident guest client move transfer extend remove find where is who".split())


# --------------------------------------------------------------------------- small helpers
def norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def has(t, *patterns):
    return any(re.search(p, t) for p in patterns)


def iso(d):
    return d.isoformat() if d else None


def pretty(d):
    if isinstance(d, str):
        d = parse_iso(d)
    return d.strftime("%b %d, %Y").replace(" 0", " ") if d else "no end date"


def parse_iso(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def title(name):
    return " ".join(w[:1].upper() + w[1:] for w in name.split())


def bed_label(bed, i):
    return bed.get("slot") or "Bed %d" % (i + 1)


def bed_vacant(bed):
    return not bed.get("tenant") and not bed.get("reservedFor") and not bed.get("temporaryClientId")


# --------------------------------------------------------------------------- the user's records
class Records:
    def __init__(self, cur, uid):
        def load(kind):
            return [dict(doc, id=i) for i, doc, _v in list_docs(cur, KINDS[kind], [uid])]
        self.rooms = sorted(load("rooms"), key=lambda r: str(r.get("room") or ""))
        for r in self.rooms:
            r["beds"] = [b for b in (r.get("beds") or []) if isinstance(b, dict)]
        self.prospects = load("prospects")
        self.temps = load("temporary_dorm_clients")
        self.shapes = load("shapes")

    def room(self, rid):
        return next((r for r in self.rooms if r["id"] == rid), None)

    def room_by_name(self, tok):
        tok = norm(tok)
        hits = [r for r in self.rooms if norm(r.get("room")) == tok]
        return hits[0] if len(hits) == 1 else None

    def occupied(self):
        for r in self.rooms:
            for i, b in enumerate(r["beds"]):
                if b.get("tenant"):
                    yield r, i, b

    def vacant_beds(self, room=None, gender=None):
        out = []
        for r in ([room] if room else self.rooms):
            if gender in ("Male", "Female") and (r.get("gender") or "Mixed") not in (gender, "Mixed"):
                continue
            for i, b in enumerate(r["beds"]):
                if bed_vacant(b):
                    out.append((r, i, b))
        return out


# --------------------------------------------------------------------------- dates
def find_dates(text, today):
    """-> [(position, date, role)] role: 'start', 'end' or None, from words just before the date."""
    t = norm(text)
    found = []

    def add(m, d):
        if d and not any(a <= m.start() < b for a, b, _d in found):
            found.append((m.start(), m.end(), d))

    def ymd(y, mo, d):
        try:
            return date(y, mo, d)
        except ValueError:
            return None

    def guess_year(mo, d):
        x = ymd(today.year, mo, d)
        if x and x < today - timedelta(days=60):
            x = ymd(today.year + 1, mo, d)
        return x

    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t):
        add(m, ymd(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t):
        y = m.group(3)
        if y:
            y = int(y) + (2000 if len(y) == 2 else 0)
            add(m, ymd(y, int(m.group(1)), int(m.group(2))))
        else:
            add(m, guess_year(int(m.group(1)), int(m.group(2))))
    mon = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    for m in re.finditer(mon + r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", t):
        mo, d = MONTHS[m.group(1)], int(m.group(2))
        add(m, ymd(int(m.group(3)), mo, d) if m.group(3) else guess_year(mo, d))
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + mon + r"(?:,?\s+(\d{4}))?", t):
        mo, d = MONTHS[m.group(2)], int(m.group(1))
        add(m, ymd(int(m.group(3)), mo, d) if m.group(3) else guess_year(mo, d))
    for m in re.finditer(r"\bend of (?:the )?(next )?month\b", t):
        y, mo = today.year, today.month + (1 if m.group(1) else 0)
        if mo > 12:
            y, mo = y + 1, 1
        add(m, date(y, mo, monthrange(y, mo)[1]))
    for m in re.finditer(r"\b(?:in|after)\s+(\d{1,3}|a|an|one|two|three|four|five|six)\s+(day|week|month)s?\b", t):
        n = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}.get(m.group(1)) or int(m.group(1))
        add(m, today + timedelta(days=n * {"day": 1, "week": 7, "month": 30}[m.group(2)]))
    for m in re.finditer(r"\bnext (week|month)\b", t):
        add(m, today + timedelta(days=7 if m.group(1) == "week" else 30))
    for m in re.finditer(r"\b(today|tonight|tomorrow|tmrw|tmr)\b", t):
        add(m, today if m.group(1) in ("today", "tonight") else today + timedelta(days=1))
    for m in re.finditer(r"\b(?:next |this |on )?(" + "|".join(WEEKDAYS) + r")\b", t):
        delta = (WEEKDAYS.index(m.group(1)) - today.weekday()) % 7 or 7
        add(m, today + timedelta(days=delta))
    for m in re.finditer(r"\b(20[2-9]\d)\b", t):        # "check out 2027": a year alone means the end of that year
        add(m, ymd(int(m.group(1)), 12, 31))
    out = []
    for a, _b, d in sorted(found):
        before = t[max(0, a - 34):a]
        for _k in range(4):                               # "check out date will be <date>" -> "check out <date>"
            before = re.sub(r"(\bwill be|\bwould be|\bshould be|\bwill|\bis|\bbe|\bdates?|\bday|\bthe|\bthis|\byear|\bby|\bat|[:=,])\s*$", "", before)
        role = None
        if re.search(r"(until|till|til|to|through|thru|ending|end|out|leaves?|leaving|checkout|up to|-)\s*(on\s*)?$", before):
            role = "end"
        elif re.search(r"(from|starting|start|starts|since|arriving|arrives|arrival|check ?in|checkin|move in|moving in|in on|on|effective|beginning)\s*$", before):
            role = "start"
        out.append((a, d, role))
    return out


def duration_days(text):
    m = re.search(r"\bfor\s+(\d{1,3}|a|an|one|two|three|four|five|six)\s+(day|night|week|month)s?\b", norm(text))
    if not m:
        return None
    n = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}.get(m.group(1)) or int(m.group(1))
    return n * {"day": 1, "night": 1, "week": 7, "month": 30}[m.group(2)]


def split_dates(text, today, single_role):
    dates = find_dates(text, today)
    start = next((d for _p, d, r in dates if r == "start"), None)
    end = next((d for _p, d, r in dates if r == "end"), None)
    rest = [d for _p, d, r in dates if r is None]
    if len(rest) >= 2 and not start and not end:
        start, end = rest[0], rest[1]
    elif rest:
        if single_role == "end" and not end:
            end = rest[0]
        elif single_role == "start" and not start:
            start = rest[0]
        elif not start:
            start = rest[0]
        elif not end:
            end = rest[0]
    dur = duration_days(text)
    if dur and not end:
        end = (start or today) + timedelta(days=dur)
    return start, end


# --------------------------------------------------------------------------- entities
def gender_in(t):
    if has(t, r"\b(female|woman|women|girl|girls|lady|ladies)\b"):
        return "Female"
    if has(t, r"\b(male|man|men|boy|boys|guy|guys)\b"):
        return "Male"
    if has(t, r"\b(mixed|coed|co-ed)\b"):
        return "Mixed"
    if has(t, r"\bany\s*(gender)?\b"):
        return "Any"
    return None


def group_in(t):
    if has(t, r"\breviewees?\b"):
        return "Reviewee"
    if has(t, r"\bstudents?\b"):
        return "Student"
    return None


def capacity_in(t):
    m = re.search(r"\b(\d{1,2})\s*(?:-\s*)?(?:beds?|bedspaces?|pax|persons?|people|slots?|capacity|capacities)\b", t) or \
        re.search(r"\b(?:capacity|capacities)\s*(?:of|to|is|=|:)?\s*(\d{1,2})\b", t) or \
        re.search(r"\b(?:good |room )?for\s+(\d{1,2})\b(?!\s*(?:-|days?|weeks?|months?|nights?|years?))", t)
    return int(m.group(1)) if m else None


ROOM_NAME_STOP = (r"with|for|and|that|which|having|has|have|capacity|capacities|beds?|bedspaces?|bedspacers?|pax|persons?|people|slots?|female|male|mixed|girls?|"
                  r"boys?|women|men|students?|reviewees?|whole|aircon\w*|ac|non-?ac|on|in|at|floor|please|then|it|is|to|as|of|the|a|an|room|only|type|gender|group|good|"
                  r"new|another|should|will|must|can|be|i|we|want|need|make|add|create|its|named?|called")


def new_room_name(text):
    """The name of a room being created, in any word order:
    'add room t567 for female students', 'add room name terin 123 4 capacity', 'create a room called Alpha with 6 beds', 'new room: B-12'."""
    t = norm(text)
    # take the capacity out first, so "terin 123 4 capacity" keeps "terin 123" as the name
    t = re.sub(r"\b\d{1,2}\s*(?:-\s*)?(?:beds?|bedspaces?|pax|persons?|people|slots?|capacity|capacities)\b", " , ", t)
    t = re.sub(r"\b(?:capacity|capacities)\s*(?:of|to|is|=|:)?\s*\d{1,2}\b", " , ", t)
    t = re.sub(r"\bfor\s+\d{1,2}\b(?!\s*-)", " , ", t)
    grab = r"((?:(?!\b(?:%s)\b)[a-z0-9][a-z0-9-]*\s*){1,3})" % ROOM_NAME_STOP
    for pat in (r"\b(?:name[ds]?|called|call it|label(?:ed|led)?|numbered|number|no\.?|#|title[d]?)\s*(?:is|as|to|of|it|:|=)?\s*" + grab,
                r"\brooms?\s*[:#-]?\s*" + grab):
        for m in re.finditer(pat, t):
            name = re.sub(r"\s+", " ", m.group(1)).strip(" -")
            if name and not re.fullmatch(r"(?:%s|new|another|add|create|make|name|number|called)" % ROOM_NAME_STOP, name):
                return name
    return None


def room_refs(text, rec, ctx_room):
    """Rooms mentioned, in order: [(room or None, token)]. 'this room' / 'here' -> the clicked room."""
    t = norm(text)
    refs = []
    for m in re.finditer(r"\broom(?:\s+(?:no\.?|number|#)\s*|\s*#\s*|\s+)([a-z0-9][a-z0-9-]*)", t):
        tok = m.group(1)
        if tok in ("this", "that", "it", "here", "the", "a", "an", "with", "for", "to", "name", "number", "capacity", "gender", "type"):
            continue
        if not re.search(r"\d", tok) and rec.room_by_name(tok) is None:
            continue                                              # "room status", "room for two": not a room name
        refs.append((m.start(), rec.room_by_name(tok), tok))
    if not refs:
        for m in re.finditer(r"\b([a-z]*\d[a-z0-9-]*)\b", t):
            r = rec.room_by_name(m.group(1))
            if r and len(m.group(1)) >= 2 and not re.match(r"\s*(beds?|days?|weeks?|months?|pax|people)\b", t[m.end():]):
                refs.append((m.start(), r, m.group(1)))
    if ctx_room and has(t, r"\b(this|that|the same) room\b", r"\bhere\b", r"\bthis one\b", r"\bin it\b"):
        refs.insert(0, (-1, ctx_room, "this room"))
    return [(r, tok) for _p, r, tok in sorted(refs, key=lambda x: x[0])]


def bed_token(text):
    m = re.search(r"\bbed\s*(?:no\.?|number|#)?\s*([a-z0-9]{1,6})\b", norm(text))
    if m and m.group(1) not in ("in", "for", "at", "to", "on", "space", "s"):
        return m.group(1)
    return None


def match_slot(room, tok):
    if not tok:
        return None
    for i, b in enumerate(room["beds"]):
        s = norm(bed_label(b, i))
        if s == tok or s == "bed " + tok or re.sub(r"\D", "", s) == tok and tok.isdigit():
            return i
    return None


def people_hits(text, people):
    """people: [(name, payload)] -> best-scoring matches (full name beats single words)."""
    t = " " + norm(text) + " "
    scored = []
    for name, payload in people:
        n = norm(name)
        if not n:
            continue
        if re.search(r"\b" + re.escape(n) + r"\b", t):
            score = 100 + len(n)
        else:
            toks = [w for w in re.findall(r"[a-z0-9]+", n) if len(w) >= 3 and w not in TENANT_STOP]
            score = sum(1 for w in toks if re.search(r"\b" + re.escape(w) + r"\b", t))
        if score:
            scored.append((score, name, payload))
    if not scored:
        return []
    best = max(s for s, _n, _p in scored)
    return [(n, p) for s, n, p in scored if s == best]


def new_name(text):
    """A new person's name from a request ('check in Juan Dela Cruz to room 201', 'reserve for "Ana Reyes"')."""
    q = re.search(r"[\"“]([^\"”]{2,60})[\"”]", text)
    if q:
        return title(q.group(1).strip())
    # every place a name could start is tried in turn: "book a bed for Paul Reyes" -> "a bed" gives nothing, "Paul Reyes" does
    # (a lookahead, so the matches may overlap: the one at "book" must not swallow the one at "for")
    for m in re.finditer(r"\b(?=(?:named|name is|called|for|check(?:ing)?[\s-]?in|checkin|put|assign|book|add(?:ing)?|new)\s+"
                         r"(?:(?:a|an|new|the)\s+)?(?:(?:tenant|resident|guest|client|boarder|bedspacer|reserve client|temporary (?:guest|client))\s+)?"
                         r"(?:named\s+|called\s+)?([A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){0,5}))", text, re.I):
        words = []
        for w in m.group(1).split():
            if norm(w).strip(".") in NAME_STOP or re.match(r"^\d", w):
                break
            words.append(w)
        words = [w for w in words if norm(w) not in ("tenant", "resident", "guest", "client", "temporary", "reserve", "a", "new")]
        if words and len(" ".join(words)) >= 2:
            return title(" ".join(words))
    return None


# --------------------------------------------------------------------------- drafts (multi-turn)
def load_settings(cur, uid):
    row = cur.execute("SELECT settings FROM ai_config WHERE owner_uid=%s", (uid,)).fetchone()
    return dict(row["settings"] or {}) if row else {}


def save_settings(cur, uid, settings):
    cur.execute("INSERT INTO ai_config (owner_uid, settings) VALUES (%s,%s) ON CONFLICT (owner_uid) "
                "DO UPDATE SET settings=EXCLUDED.settings, updated_at=now()", (uid, Jsonb(settings)))


def get_draft(cur, uid, now):
    d = load_settings(cur, uid).get("draft")
    if d and d.get("exp", 0) > now.timestamp():
        return d
    return None


def set_draft(cur, uid, draft, now):
    s = load_settings(cur, uid)
    if draft:
        draft["exp"] = now.timestamp() + DRAFT_MINUTES * 60
        s["draft"] = draft
    else:
        s.pop("draft", None)
    save_settings(cur, uid, s)


# --------------------------------------------------------------------------- result helpers
def reply(text, tag, action=None, draft=None, suggestions=None):
    return {"response": text, "intent": tag, "action": action or {"type": "none"}, "draft": draft,
            "suggestions": suggestions or []}


def ask(text, draft, tag="clarify", suggestions=None):
    return reply(text, tag, draft=draft, suggestions=suggestions)


def propose(understood, action, notes=(), tag="action_proposal"):
    action["summary"] = understood
    text = "Here's what I understood: " + understood
    if notes:
        text += " " + " ".join(notes)
    text += " Please check it and press Confirm. Nothing changes until you do."
    return reply(text, tag, action=action)


def vacancy_hint(rec, gender=None):
    rooms = {}
    for r, _i, _b in rec.vacant_beds(gender=gender):
        rooms[r["room"]] = rooms.get(r["room"], 0) + 1
    if not rooms:
        return "There are no vacant beds right now."
    return "Rooms with vacant beds: " + ", ".join("%s (%d)" % kv for kv in list(rooms.items())[:8]) + "."


# --------------------------------------------------------------------------- read-only answers
def reserved_name(prospects, pid):
    """A bed's reservedFor holds the reservation's id: show the guest's name (and check-in), never the raw id."""
    p = next((x for x in prospects or [] if x.get("id") == pid), None)
    if not p:
        return "a reservation"
    ci = parse_iso(p.get("checkIn"))
    return "%s%s" % (p.get("name") or "a guest", (" (check-in %s)" % pretty(ci)) if ci else "")


def describe_room(r, today, prospects=None):
    beds = []
    for i, b in enumerate(r["beds"]):
        if b.get("tenant"):
            end = parse_iso(b.get("end"))
            tag = " (overdue)" if end and end < today else ""
            beds.append("%s: %s, until %s%s" % (bed_label(b, i), b["tenant"], pretty(end) if end else "no end date", tag))
        elif b.get("reservedFor"):
            beds.append("%s: reserved for %s" % (bed_label(b, i), reserved_name(prospects, b["reservedFor"])))
        else:
            beds.append("%s: vacant" % bed_label(b, i))
    meta = "%s, %s, %s" % (r.get("gender") or "Mixed", r.get("demographic") or "Mixed", r.get("tenancyMode") or "Bedspace")
    return "Room %s (%s, %d beds). %s." % (r.get("room"), meta, len(r["beds"]), "; ".join(beds) or "No beds")


def departures(rec, today, start, end):
    rows = []
    for r, i, b in rec.occupied():
        d = parse_iso(b.get("end"))
        if d and start <= d <= end:
            rows.append((d, "%s (Room %s, %s) on %s" % (b["tenant"], r["room"], bed_label(b, i), pretty(d))))
    return [x for _d, x in sorted(rows)]


def summary(rec, today):
    total = sum(len(r["beds"]) for r in rec.rooms)
    occ = sum(1 for _ in rec.occupied())
    vac = len(rec.vacant_beds())
    overdue = sum(1 for _r, _i, b in rec.occupied() if parse_iso(b.get("end")) and parse_iso(b.get("end")) < today)
    week = len(departures(rec, today, today, today + timedelta(days=7)))
    res = sum(1 for p in rec.prospects if not p.get("checkedIn") and not p.get("checkedOut"))
    temps = sum(1 for c in rec.temps if c.get("status") != "Checked out")
    pct = round(occ * 100 / total) if total else 0
    return ("You have %d rooms and %d beds: %d occupied (%d%%), %d vacant, %d overdue. %d leave in the next 7 days. "
            "%d reserve client(s) waiting and %d temporary guest(s)." % (len(rec.rooms), total, occ, pct, vac, overdue, week, res, temps))


def answer_question(t, text, rec, ctx, today):
    ctx_room = rec.room(ctx.get("roomId")) if ctx.get("roomId") else None
    tab = ctx.get("tab")
    if has(t, r"\b(what|explain|how)\b.*\b(this|current)\s+(tab|page|screen|view)\b", r"^\s*explain this\s*\??$",
           r"\bwhere am i\b", r"\bhelp( me)? here\b", r"\bwhat can i do here\b"):
        if tab in TAB_LABELS:
            return reply("You're on %s. %s" % (TAB_LABELS[tab], tab_help(tab)), "context_help",
                         suggestions=TAB_TIPS.get(tab, []))
    rooms = [r for r, _tok in room_refs(text, rec, ctx_room) if r]
    if has(t, r"\bwho('s| is| are)?\b.*\b(in|inside|staying)\b", r"\b(status|details|info|tenants?)\b.*\broom\b",
           r"\broom\b.*\b(status|details|info|tenants?)\b", r"^\s*(show|open)\s+(me\s+)?room\b"):
        if not rooms and ctx_room and has(t, r"\b(this|here|it)\b"):
            rooms = [ctx_room]
        if rooms:
            return reply(" ".join(describe_room(r, today, rec.prospects) for r in rooms[:3]), "data_room")
    if has(t, r"\b(where is|where's|find|which room is|look up|lookup|search for)\b"):
        hits = people_hits(text, [(b["tenant"], (r, i, b)) for r, i, b in rec.occupied()])
        if hits:
            parts = []
            for name, (r, i, b) in hits[:5]:
                parts.append("%s is in Room %s, %s, until %s." % (name, r["room"], bed_label(b, i), pretty(b.get("end")) if b.get("end") else "no end date"))
            return reply(" ".join(parts), "data_find")
        ph = people_hits(text, [(p.get("name"), p) for p in rec.prospects])
        if ph:
            return reply(" ".join("%s is a reserve client, check-in %s." % (n, pretty(p.get("checkIn"))) for n, p in ph[:3]), "data_find")
        th = people_hits(text, [(c.get("name"), c) for c in rec.temps if c.get("status") != "Checked out"])
        if th:
            return reply(" ".join("%s is a temporary guest in Room %s, %s, until %s." % (n, c.get("room"), c.get("slot"), pretty(c.get("end"))) for n, c in th[:3]), "data_find")
        if has(t, r"\b(where is|where's|find)\b"):
            return reply("I couldn't find that name among your tenants, reserve clients or guests. Check the spelling or try the last name.", "data_find")
    if has(t, r"\b(leav|check(ing|s)? ?out|move out|moving out|depart)"):
        if has(t, r"\btoday\b"):
            rng, label = (today, today), "today"
        elif has(t, r"\btomorrow\b"):
            rng, label = (today + timedelta(days=1),) * 2, "tomorrow"
        elif has(t, r"\bnext week\b"):
            rng, label = (today + timedelta(days=7 - today.weekday()), today + timedelta(days=13 - today.weekday())), "next week"
        elif has(t, r"\bthis month\b"):
            rng, label = (today, date(today.year, today.month, monthrange(today.year, today.month)[1])), "this month"
        elif has(t, r"\bnext month\b"):
            y, mo = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            rng, label = (date(y, mo, 1), date(y, mo, monthrange(y, mo)[1])), "next month"
        elif has(t, r"\b(this week|7 days|soon|upcoming|coming)\b") or has(t, r"^\s*who\b"):
            rng, label = (today, today + timedelta(days=7)), "in the next 7 days"
        else:
            rng = None
        if rng and has(t, r"\bwho\b|\blist\b|\bshow\b|\bany(one)?\b|\bhow many\b"):
            rows = departures(rec, today, *rng)
            if not rows:
                return reply("Nobody is scheduled to leave %s." % label, "data_departures")
            return reply("%d leaving %s: %s." % (len(rows), label, "; ".join(rows[:15])), "data_departures")
    if has(t, r"\b(full|no vacan)\w*\b.*\brooms?\b", r"\brooms?\b.*\b(full|no vacan)"):
        full = [r["room"] for r in rec.rooms if r["beds"] and not rec.vacant_beds(room=r)]
        return reply(("Full rooms: " + ", ".join(map(str, full)) + ".") if full else "None of your rooms are full.", "data_full")
    if has(t, r"\b(empty|unoccupied)\b.*\brooms?\b", r"\brooms?\b.*\b(empty|unoccupied)\b"):
        empty = [r["room"] for r in rec.rooms if r["beds"] and not any(b.get("tenant") for b in r["beds"])]
        return reply(("Empty rooms: " + ", ".join(map(str, empty)) + ".") if empty else "You have no completely empty rooms.", "data_empty")
    g = gender_in(t)
    if has(t, r"\bvacan", r"\bfree beds?\b", r"\bavailable beds?\b") and (g in ("Male", "Female") or group_in(t) or rooms):
        grp = group_in(t)
        beds = rec.vacant_beds(room=rooms[0] if rooms else None, gender=g if g in ("Male", "Female") else None)
        if grp:
            want = grp + "s"
            beds = [(r, i, b) for r, i, b in beds if (r.get("demographic") or "Mixed") in (want, "Mixed")]
        if not beds:
            return reply("No vacant beds match that.", "data_vacant")
        byroom = {}
        for r, i, b in beds:
            byroom.setdefault(r["room"], []).append(bed_label(b, i))
        who = " ".join(x for x in [g if g in ("Male", "Female") else "", grp.lower() + "s" if grp else ""] if x)
        return reply("%d vacant bed(s)%s: %s." % (len(beds), " for " + who if who else "",
                     "; ".join("Room %s (%s)" % (k, ", ".join(v)) for k, v in byroom.items())), "data_vacant")
    if has(t, r"\b(reservations?|reserved clients?|reserve list|incoming|upcoming check-?ins?|waiting list)\b") and not has(t, r"\b(add|new|cancel|delete|remove|make)\b"):
        waiting = [p for p in rec.prospects if not p.get("checkedIn") and not p.get("checkedOut")]
        if not waiting:
            return reply("You have no reserve clients waiting.", "data_reservations")
        rows = sorted(waiting, key=lambda p: str(p.get("checkIn") or ""))
        return reply("%d reserve client(s): %s." % (len(rows), "; ".join("%s (%s %s), check-in %s%s" % (
            p.get("name"), p.get("gender") or "", (p.get("demographic") or "").lower(), pretty(p.get("checkIn")),
            ", bed held" if p.get("reservedBed") else "") for p in rows[:12])), "data_reservations")
    if has(t, r"\b(temporary|temp) (guests?|clients?)\b", r"\bguests\b") and not has(t, r"\b(add|new|check ?out|remove)\b"):
        active = [c for c in rec.temps if c.get("status") != "Checked out"]
        if not active:
            return reply("You have no temporary guests right now.", "data_temps")
        return reply("%d temporary guest(s): %s." % (len(active), "; ".join("%s in Room %s %s until %s" % (
            c.get("name"), c.get("room"), c.get("slot"), pretty(c.get("end"))) for c in active[:12])), "data_temps")
    if has(t, r"\b(summary|overview|status of (my|the) dorm|how is my dorm|dashboard numbers|how are we doing)\b"):
        return reply(summary(rec, today), "data_summary")
    if has(t, r"\bhow many (rooms|tenants|residents|beds)\b") and not has(t, r"\bvacan|\boverdue"):
        return reply(summary(rec, today), "data_summary")
    return None


_HELP = None


def tab_help(tab):
    global _HELP
    if _HELP is None:
        try:
            data = json.loads(INTENTS_FILE.read_text(encoding="utf-8"))
            _HELP = {i["tag"]: i["responses"][0] for i in data["intents"]}
        except Exception:
            _HELP = {}
    return _HELP.get(TAB_HELP_TAG.get(tab), "")


# --------------------------------------------------------------------------- change requests
ACTION_WORDS = r"\b(add|create|new|make|set|change|update|edit|rename|delete|remove|check ?in|checkin|check ?out|checkout|" \
               r"put|assign|move|transfer|relocate|extend|prolong|reserve|book|cancel|vacate)\b"


def detect(t):
    """Which change is being asked for (or None)."""
    if has(t, r"^\s*(how|what|why|where|when|can you explain|explain|is it|does|do i)\b") and not has(t, r"^\s*(how about|what about)\b"):
        return None                                               # questions go to help / data answers
    if has(t, r"^\s*(can i|can a|can we|can the|could i|could a|is it possible|is there|are there|which|who|whom|how many|do we|do you|"
              r"show|list|give me|display|find|any|is|are|was|were|does|did|should|would|will|am|has|have)\b", r"\bwhat happens\b", r"\bwhat if\b", r"^\s*if\b", r"^\s*a (tenant|room|female|male)\b"):
        return None                                               # asking about something, not asking to do it
    if has(t, r"\b(cancel|delete|remove)\b.*\b(reservations?|reserve|reserved|booking)\b",
           r"\b(reservation|booking)\b.*\b(cancel|delete|remove)\b"):
        return "cancel_reservation"
    if has(t, r"\b(delete|remove)\b\s+(the\s+)?room\b"):
        return "delete_room"
    if has(t, r"\b(add|create|new|make)\b.*\b(facility|walkway|shape|landmark)\b"):
        return "create_shape"
    if has(t, r"\b(temporary|temp|transient|short[- ]stay)\b") and has(t, r"\b(add|new|put|check ?in|assign|place)\b"):
        return "add_temp"
    if has(t, r"^\s*(add|new|make|put|register|list|book|reserve)\b") and has(t, r"\b(as (a |an )?(reserved?|reservation)|reserved? clients?|to (the )?reserved?|reservation)\b", r"^\s*(reserve|book)\b"):
        return "reserve"                                          # "add X as a reserve, check in today, check out 2027"
    if has(t, r"\b(check ?out|checkout|vacate|move out|remove)\b") and not has(t, r"\bwho\b|\bwhen\b|\blist\b|\bshow\b"):
        return "checkout"
    if has(t, r"\b(extend|prolong|lengthen)\b"):
        return "extend"
    if has(t, r"\b(move|transfer|relocate|switch)\b(?!\s+in\b)") and has(t, r"\bto\b"):
        return "transfer"
    if has(t, r"\b(reserve|book|reservation)\b") and has(t, r"\b(add|new|make|reserve|book|for)\b"):
        return "reserve"
    if (has(t, r"\b(add|create|new|make|build|register|open|set ?up|insert)\b.{0,24}\brooms?\b", r"^\s*new room\b", r"\banother room\b") and
            not has(t, r"\b(to|in|into|sa|from|of)\s+(the\s+)?rooms?\b", r"\b(tenant|resident|boarder|client|guest|reserve|reservation|temporary)\b",
                    r"\bhow (do|to|can)\b")):
        return "create_room"
    if has(t, r"\b(check ?in|checkin|move in|put|assign|add (a |new )?(tenant|resident|boarder|bedspacer))\b"):
        return "checkin"
    if has(t, r"\b(change|set|make|update|edit|rename|turn)\b") and has(t, r"\broom\b|\bit\b|\bhere\b"):
        return "edit_room"
    return None


def fields_from(text, rec, ctx, today):
    t = norm(text)
    ctx_room = rec.room(ctx.get("roomId")) if ctx.get("roomId") else None
    f = {}
    refs = room_refs(text, rec, ctx_room)
    if refs:
        f["rooms"] = [(r["id"] if r else None, tok) for r, tok in refs]
    if bed_token(text):
        f["bed"] = bed_token(text)
    g = gender_in(t)
    if g:
        f["gender"] = g
    grp = group_in(t)
    if grp:
        f["group"] = grp
    cap = capacity_in(t)
    if cap:
        f["capacity"] = cap
    if detect(t) == "create_room":
        nm = new_room_name(text)
        if nm:
            f["newRoom"] = nm
    if has(t, r"\bwhole[- ]room\b"):
        f["tenancy"] = "Whole Room"
    elif has(t, r"\bbed ?space\b") and not has(t, r"\bbedspacer\b"):
        f["tenancy"] = "Bedspace"
    if has(t, r"\bbedspacer\b"):
        f["roomType"] = "Bedspacer"
    # aircon on / off: "set S-110 to aircon", "make it non-ac", "remove the aircon from S-110"
    if has(t, r"\b(non[- ]?ac|non[- ]?aircon\w*|no (ac|aircon\w*|air ?con\w*)|without (ac|aircon\w*|air ?con\w*)|not (ac|aircon\w*|air[- ]?conditioned))\b",
           r"\b(remove|take out|turn off)\b.{0,12}\b(ac|aircon\w*|air ?con\w*)\b"):
        f["ac"] = False
    elif has(t, r"\b(ac|aircon\w*|air ?con\w*|air-con\w*|air[- ]?conditioned|air conditioning)\b"):
        f["ac"] = True
    m = re.search(r"\b(?:rename(?:\s+(?:room\s+)?[a-z0-9-]+)?|name)\s+(?:it\s+)?(?:to|as|into)\s+(?:room\s+)?([a-z0-9][a-z0-9-]*)", t)
    if m:
        # "s-300" -> "S-300" (room codes are upper case; the text was lower-cased before it got here)
        f["renameTo"] = m.group(1).upper() if re.fullmatch(r"[a-z0-9-]+", m.group(1)) and any(c.isdigit() for c in m.group(1)) else m.group(1)
    if has(t, r"\b(no end( date)?|open[- ]ended|indefinite(ly)?|no checkout)\b"):
        f["noEnd"] = True
    if has(t, r"\b(walkway|corridor|hall)\b"):
        f["shapeKind"] = "walkway"
    for shape in ("circle", "triangle", "rectangle"):
        if shape in t:
            f["geometry"] = shape
    m = re.search(r"\b(?:called|named|labell?ed)\s+[\"“]?([A-Za-z0-9][A-Za-z0-9 '&/-]{0,30}?)[\"”]?\s*$", text.strip(), re.I)
    if m:
        f["label"] = m.group(1).strip()
        if f["label"] == f["label"].lower():             # the question arrives lower-cased: "kitchen" -> "Kitchen", "cr" -> "CR"
            f["label"] = f["label"].upper() if len(f["label"]) <= 3 else title(f["label"])
    name = new_name(text)
    if name:
        f["name"] = name
    start, end = split_dates(text, today, single_role="end")
    if start:
        f["start"] = iso(start)
    if end:
        f["end"] = iso(end)
    if re.search(r"\b20[2-9]\d\b", t) and not re.search(r"\b\d{4}-\d{1,2}-\d{1,2}\b|/\d{2,4}\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+\d{1,2},?\s+20\d\d|\d\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*,?\s+20\d\d", t):
        f["yearOnly"] = True
    f["text"] = text[:300]
    return f


def first_room(rec, f, idx=0, ctx=None):
    rooms = [rid for rid, _tok in f.get("rooms", [])]
    if len(rooms) > idx and rooms[idx]:
        return rec.room(rooms[idx])
    return None


def unknown_room(f, idx=0):
    rooms = f.get("rooms", [])
    if len(rooms) > idx and rooms[idx][0] is None:
        return rooms[idx][1]
    return None


def record_in(text, f=None):
    """'give him a bad record because he did not pay' -> ('bad', 'He did not pay'); 'with a good record' -> ('good', None)."""
    f = f or {}
    t = norm(text)
    record = f.get("record")
    if not record:
        if has(t, r"\bbad (record|mark|remark|standing|reputation)\b", r"\bblack ?list\w*\b", r"\b(record|mark)\b.{0,12}\bbad\b", r"\bnegative record\b"):
            record = "bad"
        elif has(t, r"\bgood (record|mark|remark|standing)\b", r"\b(record|mark)\b.{0,12}\bgood\b", r"\bclean record\b", r"\bno problems?\b"):
            record = "good"
    reason = f.get("reason")
    if record == "bad" and not reason:
        m = re.search(r"\b(?:because|since|cause|coz|due to|for|kay|kasi|reason is|reason:)\s+(?!a\s+(?:bad|good)\b)(.{3,200})$", text.strip(" .!?"), re.I)
        if m:
            reason = m.group(1).strip()
            reason = re.sub(r"^(it|he|she|they)\b", lambda x: x.group(1).capitalize(), reason)
            reason = re.sub(r"^It\b", "They", reason)
            reason = reason[0].upper() + reason[1:]
    return record, (reason[:300] if reason else None)


def best_beds(rec, gender, group, only_room=None):
    """Vacant beds that fit, best first -> [(room, bed index, why)].
    Best = a room for exactly this gender and group, that already has people in it (so empty rooms stay free for groups)."""
    out = []
    for r in ([only_room] if only_room else rec.rooms):
        rg, rd = r.get("gender") or "Mixed", r.get("demographic") or "Mixed"
        if gender in ("Male", "Female") and rg not in (gender, "Mixed"):
            continue
        if group in ("Student", "Reviewee") and rd not in (group + "s", "Mixed"):
            continue
        whole = r.get("tenancyMode") == "Whole Room"
        used = sum(1 for b in r["beds"] if not bed_vacant(b))
        if whole and used:
            continue
        free = [i for i, b in enumerate(r["beds"]) if bed_vacant(b)]
        if not free:
            continue
        score = (2 if rg == gender else 0) + (2 if group in ("Student", "Reviewee") and rd == group + "s" else 0) + (0 if whole else 1) + (1 if used else 0)
        why = []
        if rg == gender:
            why.append("it is a %s room" % gender.lower())
        elif rg == "Mixed":
            why.append("it accepts any gender")
        if group in ("Student", "Reviewee"):
            why.append("it is for %ss" % group.lower() if rd == group + "s" else "it accepts %ss" % group.lower())
        why.append("it has %d free bed%s%s" % (len(free), "" if len(free) == 1 else "s", " and people already staying" if used else ""))
        for i in (free[:1] if whole else free):
            out.append((score, -used, str(r.get("room") or ""), i, r, ", ".join(why)))
    out.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))
    return [(r, i, why) for _s, _u, _n, i, r, why in out]


def pick_tenant(rec, f):
    hits = people_hits(f.get("text", ""), [(b["tenant"], (r["id"], i)) for r, i, b in rec.occupied()])
    if len(hits) == 1:
        return hits[0][1], None
    if len(hits) > 1:
        return None, hits
    room = first_room(rec, f)
    if room and f.get("bed"):
        i = match_slot(room, f["bed"])
        if i is not None and room["beds"][i].get("tenant"):
            return (room["id"], i), None
    return None, None


def build(kind, f, rec, ctx, today):
    """-> reply dict: a proposal, a follow-up question (with draft) or an explanation."""
    draft = {"kind": kind, "f": f}
    room = first_room(rec, f)
    bad_room = unknown_room(f)
    if bad_room and kind not in ("create_room",):
        return reply("I can't find room %s in your records. %s" % (bad_room.upper(), vacancy_hint(rec)), "clarify")

    if kind == "create_room":
        name = f.get("newRoom") or ((f.get("rooms") or [(None, None)])[0][1] if f.get("rooms") else None)
        if name and rec.room_by_name(name):
            return reply("Room %s already exists. Did you mean to edit it?" % name.upper(), "clarify")
        if not name:
            return ask("What room number or name should the new room have?", dict(draft, need="room"))
        cap = f.get("capacity")
        if not cap:
            return ask("How many beds will Room %s have (1 to 20)?" % name.upper(), dict(draft, need="capacity"))
        if not 1 <= cap <= 20:
            return ask("A room can have 1 to 20 beds. How many beds should Room %s have?" % name.upper(), dict(draft, need="capacity"))
        gender = f.get("gender") if f.get("gender") in ("Male", "Female", "Mixed") else "Mixed"
        demo = {"Student": "Students", "Reviewee": "Reviewees"}.get(f.get("group"), "Mixed")
        tenancy = f.get("tenancy") or "Bedspace"
        notes = []
        if not f.get("gender"):
            notes.append("Gender wasn't given, so I used Mixed.")
        if not f.get("group"):
            notes.append("Resident group wasn't given, so I used Mixed.")
        action = {"type": "create_room", "room": name.upper(), "capacity": cap, "gender": gender, "demographic": demo,
                  "tenancyMode": tenancy, "roomType": f.get("roomType") or "Room"}
        if f.get("ac") is not None:                                # "… 6 beds, aircon"
            action["ac"] = bool(f["ac"])
        return propose("create Room %s with %d bed(s), %s, %s, %s%s." % (name.upper(), cap, gender, demo, tenancy,
                                                                         "" if f.get("ac") is None else ", AC" if f["ac"] else ", Non-AC"), action, notes)

    if kind == "delete_room":
        if not room:
            return ask("Which room should I delete?", dict(draft, need="room"))
        busy = [b for b in room["beds"] if b.get("tenant") or b.get("reservedFor") or b.get("temporaryClientId")]
        if busy:
            return reply("Room %s still has %d tenant(s), reservation(s) or guest(s), so the tracker won't delete it. "
                         "Check them out or move them first." % (room["room"], len(busy)), "clarify")
        return propose("delete Room %s and its %d empty bed(s). This can't be undone." % (room["room"], len(room["beds"])),
                       {"type": "delete_room", "roomId": room["id"]})

    if kind == "edit_room":
        if not room:
            return ask("Which room should I change?", dict(draft, need="room"))
        changes, said = {}, []
        if f.get("capacity"):
            occupied = sum(1 for b in room["beds"] if b.get("tenant") or b.get("reservedFor"))
            if f["capacity"] < occupied:
                return reply("Room %s has %d occupied or reserved bed(s), so it can't go down to %d beds." % (room["room"], occupied, f["capacity"]), "clarify")
            changes["capacity"] = f["capacity"]
            said.append("capacity to %d beds" % f["capacity"])
        if f.get("gender") in ("Male", "Female", "Mixed"):
            changes["gender"] = f["gender"]
            said.append("gender to %s" % f["gender"])
        if f.get("group"):
            changes["demographic"] = f["group"] + "s"
            said.append("resident group to %ss" % f["group"])
        if f.get("tenancy"):
            changes["tenancyMode"] = f["tenancy"]
            said.append("tenancy to %s" % f["tenancy"])
        if f.get("roomType"):
            changes["type"] = f["roomType"]
            said.append("type to %s" % f["roomType"])
        if f.get("ac") is not None and bool(f["ac"]) != (room.get("ac") is True or str(room.get("ac")).lower() == "true"):
            changes["ac"] = bool(f["ac"])
            said.append("air conditioning to %s" % ("AC" if f["ac"] else "Non-AC"))
        if f.get("renameTo") and norm(f["renameTo"]) != norm(room["room"]):
            if rec.room_by_name(f["renameTo"]):
                return reply("There is already a Room %s." % f["renameTo"], "clarify")
            changes["room"] = f["renameTo"]
            said.append("name to %s" % f["renameTo"])
        if not changes:
            if f.get("ac") is not None:
                return reply("Room %s is already %s." % (room["room"], "AC" if f["ac"] else "Non-AC"), "clarify")
            return ask("What should I change in Room %s? For example: capacity, gender, resident group, aircon, tenancy or name." % room["room"],
                       dict(draft, need="changes"))
        return propose("in Room %s, change %s." % (room["room"], ", ".join(said)),
                       {"type": "edit_room", "roomId": room["id"], "changes": changes})

    if kind == "checkin":
        name = f.get("name")
        if not name:
            return ask("What is the new tenant's full name?", dict(draft, need="name"))
        if any(norm(b["tenant"]) == norm(name) for _r, _i, b in rec.occupied()):
            return reply("%s is already checked in. Did you want to move them or extend their stay instead?" % name, "clarify")
        if not room:
            return ask("Which room should %s go to? %s" % (name, vacancy_hint(rec, f.get("gender"))), dict(draft, need="room"))
        notes = []
        if f.get("bed"):
            i = match_slot(room, f["bed"])
            if i is None:
                return reply("Room %s has no bed called %s. Its beds are: %s." % (room["room"], f["bed"],
                             ", ".join(bed_label(b, k) for k, b in enumerate(room["beds"]))), "clarify")
            if not bed_vacant(room["beds"][i]):
                b = room["beds"][i]
                return reply("%s in Room %s isn't free (%s). %s" % (bed_label(b, i), room["room"],
                             b.get("tenant") or ("reserved for " + reserved_name(rec.prospects, b.get("reservedFor"))), vacancy_hint(rec)), "clarify")
        else:
            free = rec.vacant_beds(room=room)
            if not free:
                return reply("Room %s has no vacant bed. %s" % (room["room"], vacancy_hint(rec)), "clarify")
            i = free[0][1]
            notes.append("No bed was named, so I picked the first vacant one.")
        if not f.get("end") and not f.get("noEnd"):
            return ask("Until when will %s stay? (for example 'until March 1', 'for 6 months' or 'no end date')" % name,
                       dict(draft, need="end"))
        start = f.get("start") or iso(today)
        rg = f.get("gender") if f.get("gender") in ("Male", "Female") else (room.get("gender") if room.get("gender") in ("Male", "Female") else "Unspecified")
        rtype = f.get("group") or "Student"
        if not f.get("group"):
            notes.append("Resident group wasn't given, so I used Student.")
        slot = bed_label(room["beds"][i], i)
        change = {"slot": slot, "tenant": name, "residentType": rtype, "residentGender": rg, "start": start}
        if f.get("end"):
            change["end"] = f["end"]
        return propose("check in %s to Room %s, %s, from %s until %s (%s, %s)." % (
            name, room["room"], slot, pretty(start), pretty(f.get("end")) if f.get("end") else "no end date", rtype, rg),
            {"type": "edit_room", "roomId": room["id"], "changes": {"bedChanges": [change]}}, notes, tag="action_checkin")

    if kind in ("checkout", "extend", "transfer"):
        temps = people_hits(f.get("text", ""), [(c.get("name"), c) for c in rec.temps if c.get("status") != "Checked out"])
        if kind == "checkout" and len(temps) == 1:
            c = temps[0][1]
            return propose("check out temporary guest %s and free Room %s, %s." % (c.get("name"), c.get("room"), c.get("slot")),
                           {"type": "checkout_temporary_client", "clientId": c["id"]})
        if kind == "checkout" and not f.get("record"):            # keep "bad record because …" while I ask which tenant
            r0, why0 = record_in(f.get("text", ""), f)
            if r0:
                f["record"] = r0
                if why0:
                    f["reason"] = why0
                draft = {"kind": kind, "f": f}
        loc, many = pick_tenant(rec, f)
        if many:
            opts = "; ".join("%s (Room %s)" % (n, rec.room(p[0])["room"]) for n, p in many[:6])
            return ask("I found more than one match: %s. Which one do you mean? Say the full name." % opts, dict(draft, need="tenant"))
        if not loc:
            return ask("Which tenant do you mean? Say their name, or the room and bed.", dict(draft, need="tenant"))
        src = rec.room(loc[0])
        i = loc[1]
        bed = src["beds"][i]
        slot = bed_label(bed, i)
        if kind == "checkout":
            if bed.get("temporaryClientId"):
                return reply("%s is a temporary guest. Check them out from Temporary Dorm Clients, or say 'check out guest %s'." % (bed["tenant"], bed["tenant"]), "clarify")
            record, reason = record_in(f.get("text", ""), f)
            if record == "bad" and not reason:
                return ask("What is the reason for %s's bad record? (for example “did not pay the rent”)" % bed["tenant"], dict(draft, need="reason"))
            action = {"type": "checkout_tenant", "roomId": src["id"], "slot": slot}
            if record:
                action["record"] = record
                if record == "bad":
                    action["reason"] = reason
            rec_txt = (" with a GOOD record" if record == "good" else " with a BAD record (reason: %s)" % reason if record == "bad" else "")
            notes = [] if record else ["No good or bad record will be saved. Say “with a good record” or “bad record because …” if you want one."]
            return propose("check out %s from Room %s, %s%s. The bed becomes vacant and the stay is saved in Tenant History." % (
                bed["tenant"], src["room"], slot, rec_txt), action, notes)
        if kind == "extend":
            if not f.get("end"):
                return ask("Until when should %s's stay be extended? Their current end is %s." % (bed["tenant"], pretty(bed.get("end")) if bed.get("end") else "not set"),
                           dict(draft, need="end"))
            cur_end = parse_iso(bed.get("end"))
            notes = []
            if cur_end and parse_iso(f["end"]) <= cur_end:
                notes.append("Note: that date is not later than the current end (%s)." % pretty(cur_end))
            return propose("extend %s's stay in Room %s, %s, until %s." % (bed["tenant"], src["room"], slot, pretty(f["end"])),
                           {"type": "edit_room", "roomId": src["id"], "changes": {"bedChanges": [{"slot": slot, "end": f["end"]}]}},
                           notes, tag="action_extend")
        # transfer
        targets = [rid for rid, _tok in f.get("rooms", []) if rid and rid != src["id"]]
        target = rec.room(targets[-1]) if targets else None
        if not target:
            return ask("Which room should %s move to? %s" % (bed["tenant"], vacancy_hint(rec)), dict(draft, need="target"))
        notes = []
        tb = re.search(r"\bto\s+(?:room\s*)?[a-z0-9-]+\s*,?\s*bed\s*([a-z0-9]{1,6})\b", norm(f.get("text", "")))
        ti = match_slot(target, tb.group(1)) if tb else None
        if ti is None:
            free = rec.vacant_beds(room=target)
            if not free:
                return reply("Room %s has no vacant bed. %s" % (target["room"], vacancy_hint(rec)), "clarify")
            ti = free[0][1]
            notes.append("I picked the first vacant bed in Room %s." % target["room"])
        elif not bed_vacant(target["beds"][ti]):
            return reply("%s in Room %s isn't free. %s" % (bed_label(target["beds"][ti], ti), target["room"], vacancy_hint(rec)), "clarify")
        tslot = bed_label(target["beds"][ti], ti)
        return propose("move %s from Room %s, %s to Room %s, %s." % (bed["tenant"], src["room"], slot, target["room"], tslot),
                       {"type": "transfer_resident", "sourceRoomId": src["id"], "sourceSlot": slot,
                        "targetRoomId": target["id"], "targetSlot": tslot}, notes)

    if kind == "reserve":
        name = f.get("name")
        if not name:
            return ask("What is the reserve client's full name?", dict(draft, need="name"))
        gender = f.get("gender") if f.get("gender") in ("Male", "Female", "Any") else None
        if not gender:
            return ask("Is %s male or female? (You can also say 'any'.)" % name, dict(draft, need="gender"))
        if not f.get("group"):
            return ask("Is %s a student or a reviewee?" % name, dict(draft, need="group"))
        check_in = f.get("start") or f.get("end")
        check_out = f.get("end") if f.get("start") else None
        if not check_in:
            return ask("When will %s check in?" % name, dict(draft, need="start"))
        action = {"type": "add_reserve_client", "name": name, "gender": gender, "demographic": f["group"], "checkIn": check_in}
        if check_out:
            action["checkOut"] = check_out
        notes = []
        if f.get("yearOnly"):
            notes.append("You gave only the year, so I used %s as the check-out date." % pretty(check_out or check_in))
        picks = best_beds(rec, gender, f["group"], room)
        where = ""
        if picks:
            r0, i0, why = picks[0]
            action["roomId"], action["slot"] = r0["id"], bed_label(r0["beds"][i0], i0)
            where = " and hold Room %s, %s for them" % (r0["room"], action["slot"])
            notes.append("I chose Room %s because %s." % (r0["room"], why))
            nxt = next(((r, i) for r, i, _w in picks[1:] if r["id"] != r0["id"]), None) or (picks[1][:2] if len(picks) > 1 else None)
            if nxt:
                notes.append("Next best: Room %s, %s." % (nxt[0]["room"], bed_label(nxt[0]["beds"][nxt[1]], nxt[1])))
        elif room:
            return reply("Room %s has no free bed that fits a %s %s. %s" % (room["room"], gender.lower(), f["group"].lower(), vacancy_hint(rec, gender)), "clarify")
        else:
            notes.append("No vacant bed fits a %s %s right now, so I will add them without a bed. You can pick one later in Reserved Clients." % (gender.lower(), f["group"].lower()))
        return propose("add %s (%s %s) to Reserved Clients%s, check-in %s%s." % (
            name, gender, f["group"].lower(), where, pretty(check_in), ", check-out " + pretty(check_out) if check_out else ""),
            action, notes)

    if kind == "cancel_reservation":
        hits = people_hits(f.get("text", ""), [(p.get("name"), p) for p in rec.prospects if not p.get("checkedIn")])
        if len(hits) > 1:
            return ask("Which reserve client: %s?" % ", ".join(n for n, _p in hits[:6]), dict(draft, need="tenant"))
        if not hits:
            return ask("Which reserve client's reservation should I cancel? Say their name.", dict(draft, need="tenant"))
        p = hits[0][1]
        if p.get("reservedBed") and not has(norm(f.get("text", "")), r"\b(delete|remove)\b"):
            return propose("cancel %s's bed reservation. They stay on the reserve list without a bed." % p.get("name"),
                           {"type": "cancel_reservation", "prospectId": p["id"]})
        return propose("remove %s from Reserved Clients." % p.get("name"), {"type": "delete_reserve_client", "prospectId": p["id"]})

    if kind == "add_temp":
        name = f.get("name")
        if not name:
            return ask("What is the temporary guest's name?", dict(draft, need="name"))
        gender = f.get("gender") if f.get("gender") in ("Male", "Female", "Mixed") else None
        if not gender:
            return ask("Is %s male or female?" % name, dict(draft, need="gender"))
        start, end = f.get("start"), f.get("end")
        if not start and end:
            start = iso(today)
        if not end:
            return ask("Until when will %s stay? (for example 'until Friday' or 'for 3 days')" % name, dict(draft, need="end"))
        notes = []
        if room:
            i = match_slot(room, f.get("bed")) if f.get("bed") else None
            if i is None:
                free = rec.vacant_beds(room=room, gender=gender)
                if not free:
                    return reply("Room %s has no vacant bed for a %s guest. %s" % (room["room"], gender.lower(), vacancy_hint(rec, gender)), "clarify")
                i = free[0][1]
        else:
            picks = best_beds(rec, gender, "Temporary", None)
            if not picks:
                return reply("There's no vacant bed for a %s guest right now." % gender.lower(), "clarify")
            room, i = picks[0][0], picks[0][1]
            notes.append("I chose Room %s because %s." % (room["room"], picks[0][2]))
            nxt = next(((r, j) for r, j, _w in picks[1:] if r["id"] != room["id"]), None)
            if nxt:
                notes.append("Next best: Room %s, %s." % (nxt[0]["room"], bed_label(nxt[0]["beds"][nxt[1]], nxt[1])))
        slot = bed_label(room["beds"][i], i)
        return propose("add temporary guest %s (%s) to Room %s, %s, from %s to %s." % (name, gender, room["room"], slot, pretty(start), pretty(end)),
                       {"type": "add_temporary_client", "name": name, "gender": gender, "start": start, "end": end,
                        "roomId": room["id"], "slot": slot}, notes)

    if kind == "create_shape":
        label = f.get("label")
        if not label:
            return ask("What should the facility or walkway be called?", dict(draft, need="label"))
        kindw = f.get("shapeKind") or "facility"
        geo = f.get("geometry") or "rectangle"
        return propose("add a hallway %s called “%s” as a %s." % (kindw, label, geo),
                       {"type": "create_shape", "label": label, "kind": kindw, "geometry": geo})
    return None


def merge_followup(draft, text, rec, ctx, today):
    """Fill what the last question asked for. Bare answers count ('205', 'female', 'March 1', 'Juan Cruz')."""
    f = dict(draft["f"])
    new = fields_from(text, rec, ctx, today)
    t = norm(text)
    need = draft.get("need")
    if need in ("room", "target") and "rooms" not in new:
        r = rec.room_by_name(t.replace("room", "").strip())
        new["rooms"] = [(r["id"] if r else None, t.replace("room", "").strip())]
    if draft["kind"] == "create_room":
        # any order works: "add room" -> "for female students, capacity of 5" -> "t567"
        detail = bool(new.get("gender") or new.get("group") or new.get("capacity") or new.get("tenancy"))
        named = new_room_name(text) if has(t, r"\b(room|name[ds]?|called|call it|number|label\w*)\b") else None
        bare = re.sub(r"^(room|name|it is|its|call it|called)\s+", "", t).strip()
        if named:
            new["newRoom"] = named
        elif need == "room" and not detail and re.fullmatch(r"[a-z0-9][a-z0-9 -]{0,20}", bare) and len(bare.split()) <= 3:
            new["newRoom"] = bare
        elif need == "room" and detail:
            # "z9 with 3 beds for male reviewees": the words before the details are the name
            lead = re.match(r"((?:(?!\b(?:%s)\b)[a-z0-9][a-z0-9-]*\s*){1,3})" % ROOM_NAME_STOP, re.sub(r"\b\d{1,2}\s*(?:beds?|pax|persons?|people|slots?|capacity)\b.*$", "", t))
            if lead and lead.group(1).strip():
                new["newRoom"] = lead.group(1).strip()
        elif need == "room" and not detail:
            return None
        new.pop("rooms", None)
        if need == "room" and (new.get("newRoom") or f.get("newRoom")):
            f.pop("rooms", None)
    if need == "capacity" and "capacity" not in new and re.fullmatch(r"\d{1,2}", t):
        new["capacity"] = int(t)
    if need == "name" and not new.get("name") and re.fullmatch(r"[a-z][a-z .'-]{1,60}", t):
        new["name"] = title(text.strip())
    if need in ("end", "start") and not new.get("end") and not new.get("start") and not new.get("noEnd"):
        return None
    if need == "end" and new.get("start") and not new.get("end"):
        new["end"], new["start"] = new["start"], f.get("start")
    if need == "start" and new.get("end") and not new.get("start"):
        new["start"], new["end"] = new["end"], f.get("end")
    if need == "gender" and not new.get("gender"):
        return None
    if need == "group" and not new.get("group"):
        return None
    if need == "reason":
        if len(t) < 3:
            return None
        f["reason"] = text.strip()[:300]
        f["record"] = "bad"
        return f
    if need == "tenant":
        f["text"] = text
    if need == "target":
        new["rooms"] = f.get("rooms", [])[:1] + new.get("rooms", [])
    for k, v in new.items():
        if k == "text" and need != "tenant":
            continue
        if v not in (None, [], ""):
            f[k] = v
    return f


# --------------------------------------------------------------------------- entry point
def handle(conn, uid, question, context):
    """-> reply dict, or None to let the intent model answer."""
    ctx = context if isinstance(context, dict) else {}
    ctx = {"tab": str(ctx.get("tab") or "")[:30], "roomId": str(ctx.get("roomId") or "")[:80] or None,
           "today": str(ctx.get("today") or "")[:10]}
    now = datetime.now(timezone.utc)
    today = parse_iso(ctx["today"]) or now.date()
    if abs((today - now.date()).days) > 2:                  # the browser's clock is only a hint
        today = now.date()
    cur = conn.cursor()
    rec = Records(cur, uid)
    if ctx["roomId"] and not rec.room(ctx["roomId"]):         # never trust ids from the browser
        ctx["roomId"] = None
    t = norm(question)

    with conn.transaction():
        draft = get_draft(cur, uid, now)
        if draft and has(t, r"^(cancel|never ?mind|nevermind|stop|forget it|no thanks?|nope)\b"):
            set_draft(cur, uid, None, now)
            return reply("Okay, I dropped that request. Nothing was changed.", "clarify_cancelled")
        kind = detect(t)
        result = None
        if draft and kind is None and (has(t, r"\?\s*$") or has(t, r"^(which|what|who|where|when|how|is|are|do|does|can|could|show|list|give|any)\b")) \
                and draft.get("need") not in ("tenant",):
            ans = answer_question(t, question, rec, ctx, today)
            set_draft(cur, uid, None, now)                        # a new question: drop the half-finished request
            return ans
        if draft and kind is None and has(t, r"^(who|what|where|when|which|how|show|list|is|are|do|does|give)\b"):
            ans = answer_question(t, question, rec, ctx, today)
            if ans:
                set_draft(cur, uid, None, now)
                return ans
        if draft and kind == draft["kind"] and kind == "checkout" and (pick_tenant(rec, fields_from(question, rec, ctx, today))[0]):
            set_draft(cur, uid, None, now)                       # a complete new check-out: do not reuse the old one's record or reason
            draft = None
        if draft and (kind is None or kind == draft["kind"]):
            f = merge_followup(draft, question, rec, ctx, today)
            if f is not None:
                result = build(draft["kind"], f, rec, ctx, today)
            elif not kind:
                misses = int(draft.get("miss") or 0) + 1
                if misses >= 2:                                   # never keep asking the same thing forever
                    set_draft(cur, uid, None, now)
                    return reply("I still didn't get that, so I stopped that request. Nothing was changed. You can start again any time, "
                                 "for example “reserve a bed for Ana Reyes, female student, check-in Dec 1”.", "clarify_cancelled")
                draft = dict(draft, miss=misses)
                result = ask("Sorry, I didn't catch that. " + _repeat_question(draft), draft)
        if result is None and kind:
            f = fields_from(question, rec, ctx, today)
            if ctx["roomId"] and not f.get("rooms") and kind in ("checkin", "edit_room", "delete_room") and \
                    has(t, r"\b(this|here|it|current|selected)\b"):
                f["rooms"] = [(ctx["roomId"], "this room")]
            result = build(kind, f, rec, ctx, today)
        if result is None:
            if draft:
                set_draft(cur, uid, None, now)
            return answer_question(t, question, rec, ctx, today)
        set_draft(cur, uid, result.get("draft"), now)
        return result


def _repeat_question(draft):
    need = draft.get("need")
    return {"room": "Which room?", "target": "Which room should they move to?", "capacity": "How many beds?",
            "name": "What's the name?", "end": "Until when? (a date, or 'no end date')", "start": "Which date?",
            "gender": "Male, female or any?", "group": "Student or reviewee?", "tenant": "Which tenant?",
            "label": "What should it be called?", "changes": "What should change?", "reason": "What is the reason for the bad record?"}.get(need, "Could you say that again?") + \
        " (Say 'cancel' to stop.)"


def suggestions_for(ctx, rec=None):
    tab = (ctx or {}).get("tab")
    return TAB_TIPS.get(tab, ["Give me a summary", "Who leaves this week?", "Which rooms have vacant beds?"])
