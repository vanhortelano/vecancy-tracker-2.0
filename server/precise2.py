"""precise2.py: second set of "brain" rules (Branch Admin test, 2026-11-17). Used by precise.py.

  resolve(...)   fills in what a change request leaves out, from the records
  KNOW_*         "do you know Katilana?" / "who is Katilana?" -> a person in the records, or a clear "I don't know them"
  person_facts   is X a student / how long has X stayed / days left for X / who shares X's room
  counts         how many students / male rooms / tenants in room X
  ranks, rates   which room has the most tenants, vacancy rate for females, average stay of students, male vs female
  ranges         who checks out in December / between dates / on a date, who checks in next week, busiest day,
                 temporary guests in a period
  app_facts      room vs bedspace, how long Tenant History is kept, offline use"""
import calendar
import re
from datetime import date, timedelta

import agent
import smart

R = agent.reply

NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
       "eleven": 11, "twelve": 12}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def _n(word):
    word = str(word or "").lower()
    return int(word) if word.isdigit() else NUM.get(word)


def _mon(word):
    return next(i for i, m in enumerate(MONTHS, 1) if m.startswith(word[:3]))


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _p(part, whole):
    return ("%.1f%%" % (100.0 * part / whole)).replace(".0%", "%") if whole else "0%"


# ------------------------------------------------------------------------------------------ resolve change requests
def resolve(conn, uid, q, today, P):
    """'extend X by 1 month' -> 'extend X until 2026-12-17'; 'move X to bed 4' -> 'move X to room s-101 bed 4';
    'add 2 beds to room s-110' -> 'change room s-110 capacity to 4 beds'. Anything else comes back unchanged."""
    t = re.sub(r"\s+", " ", str(q or "")).strip()
    end_q = "?" if t.endswith("?") else ""
    t = t.rstrip(" ?.!")
    m_ext = re.match(r"^(extend|lengthen|prolong)\s+(?:the\s+stay\s+of\s+)?(.+?)(?:'s\s+stay)?\s+(?:by|for|another|for another|plus|\+)\s*"
                     r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*(more\s+)?(days?|weeks?|wks?|months?|mos?|years?|yrs?)\b(.*)$", t)
    m_bed = re.match(r"^(move|transfer)\s+(.+?)\s+to\s+bed\s*(?:no\.?\s*|number\s*)?(\d{1,2})$", t)
    m_cap = re.match(r"^(add|remove|delete|take out|take away)\s+(\d+|a|an|one|two|three|four|five|six)\s+(?:more\s+|extra\s+|new\s+)?beds?\s+"
                     r"(?:to|in|into|on|from|of|out of)\s+(room\s+[a-z0-9][a-z0-9-]*)$", t)
    if not (m_ext or m_bed or m_cap):
        return q
    rec = smart.Records(conn.cursor(), uid)
    if m_ext:
        hits = P._find_people(m_ext.group(2), [("now", b.get("tenant"), (r, i, b)) for r, i, b in rec.occupied()])
        n, unit = _n(m_ext.group(3)), m_ext.group(5)
        if not hits or not n:
            return q
        r, i, b = hits[0][2]
        base = smart.parse_iso(b.get("end")) or today
        if unit.startswith("d"):
            new = base + timedelta(days=n)
        elif unit.startswith("w"):
            new = base + timedelta(weeks=n)
        elif unit.startswith("y"):
            new = add_months(base, 12 * n)
        else:
            new = add_months(base, n)
        return "extend %s until %s%s%s" % (b.get("tenant").lower(), new.isoformat(), m_ext.group(6), end_q)
    if m_bed:
        return q                                       # answered by move_same_room (the app can't move inside one room)
    if m_cap:
        import expert
        refs = expert._rooms_in(m_cap.group(3), rec)
        n = _n(m_cap.group(2))
        if not refs or refs[0][0] is None or not n:
            return q
        room = refs[0][0]
        cap = len(room["beds"]) + (n if m_cap.group(1) == "add" else -n)
        return "change %s capacity to %d beds%s" % (m_cap.group(3), max(cap, 0), end_q)
    return q


# ------------------------------------------------------------------------------------------ do you know X?
KNOW = re.compile(r"^(?:do you know|do u know|you know|have you heard of|have you met|did you know|who is|who's|whos|who was|sino si|kinsa si)\s+"
                  r"(?:about\s+|si\s+|of\s+|a\s+person\s+named\s+|someone\s+named\s+|somebody\s+named\s+)?([a-zñ][a-zñ .'-]{1,40}?)\s*[?.!]*$")
NOT_A_NAME = set("""how what where when why if which whether who the my our your a an in on at about anything everything someone somebody anybody
anyone me you yourself it this that these those there here i we they he she him her them us now today tomorrow next last this
overdue reserved leaving coming staying checking moving newest latest oldest longest first best admin developer creator owner
viewer viewers super branch tenant tenants room rooms bed beds vacant free available occupied full empty dorm dormitory tracker
app system assistant ai bot robot google chatgpt siri alexa president weather""".split())


def _looks_like_name(x, P, people=None):
    """Only a bare name: "katilana", "ana rivera". Any ordinary word that is not part of someone's name ("ana dela's
    emergency contact", "the rules") means it is a different kind of question."""
    import lang
    words = [w for w in re.findall(r"[a-zñ]+", x) if len(w) > 1]
    if not words or len(words) > 4:
        return False
    known = set(getattr(lang, "VOCAB", [])) | set(getattr(lang, "_ENGLISH", [])) | NOT_A_NAME | set(P.COMMON)
    name_words = {w for _k, n, _d in (people or []) for w in re.findall(r"[a-zñ]+", str(n).lower())}
    return not any(w in known and w not in name_words for w in words) and not re.search(r"'s\b", x)


def know_person(conn, uid, rec, t, today, P, page):
    m = KNOW.match(t)
    if not m:
        return None
    x = m.group(1).strip(" .-")
    admin = page in (None, "", "admin")
    people = P._people(rec, P._history(conn.cursor(), uid)) if admin else []
    if not _looks_like_name(x, P, people):
        return None
    typed = " ".join(w.capitalize() for w in x.split())
    if not admin:
        return R("person_unknown", "I don't know who “%s” is. On this page I only see rooms and vacancies, never people's names, and I can't look "
                 "anyone up outside the tracker." % typed)
    hits = P._find_people(x, people)
    if hits:
        import expert
        found = expert.person_lookup(conn, uid, "find " + hits[0][1].lower(), "find " + hits[0][1].lower(), today)
        if found:
            found = dict(found)
            found["response"] = re.sub(r"^Yes, ", "Yes. ", found["response"])
            return found
    return R("person_unknown", "I don't know anyone named “%s”. I searched your tenants, reserved clients, temporary guests and Tenant History, "
             "and nobody has that name. I only know the people in your own records and can't look anyone up outside the tracker. "
             "Check the spelling, or try just the first name." % typed, suggestions=["List all tenants", "Open Tenant History"])


# ------------------------------------------------------------------------------------------ one person: type, stay length, days left, roommates
def person_facts(cur, uid, rec, t, today, P):
    roommate = re.search(r"\b(staying with|stays with|roommates?|room ?mates?|same room( as)?|shares? (a |the )?room|sharing (a |the )?room|with whom|"
                         r"living with|lives with|who else is in)\b", t)
    kind = re.search(r"^(?:is|was|are)\s+(.+?)\s+(?:(?:a|an)\s+)?(student|reviewee|male|female|boy|girl|man|woman)\b", t)
    length = re.search(r"\bhow long\b.*\b(stay\w*|been|lived|living|here|tenant)\b|\b(length|duration) of (the )?stay\b", t) and \
        not re.search(r"\b(until|till|before|left|remaining)\b", t)
    left = re.search(r"\b(days? left|how many days|days? remaining|remaining days|how long (until|till|before)|how much time|how many (more )?(weeks|months)|"
                     r"how many araw|ilang araw)\b", t)
    if not (roommate or kind or length or left):
        return None
    people = P._people(rec, P._history(cur, uid))
    hits = P._find_people(t, people)
    if not hits:
        return None
    now = [h for h in hits if h[0] == "now"]
    res = [h for h in hits if h[0] == "reserved"]
    old = [h for h in hits if h[0] == "history"]
    name = hits[0][1]
    if roommate:
        if not now:
            return R("roommates", "%s isn't staying now, so they have no roommates%s." % (
                name, " (they are a reserved client)" if res else " (they are in Tenant History)" if old else ""))
        r, i, b = now[0][2]
        others = [(smart.bed_label(o, j), o) for j, o in enumerate(r["beds"]) if j != i and o.get("tenant")]
        rows = [[s, o.get("tenant"), smart.pretty(smart.parse_iso(o.get("end"))) if o.get("end") else "—"] for s, o in others]
        if not others:
            text = "%s has no roommates right now: nobody else is staying in Room %s." % (b.get("tenant"), r.get("room"))
        else:
            text = "%s shares Room %s with %s: %s." % (b.get("tenant"), r.get("room"), _plural(len(others), "other tenant"),
                                                     "; ".join("%s (%s)" % (o.get("tenant"), s) for s, o in others))
        reserved = [(smart.bed_label(o, j), o) for j, o in enumerate(r["beds"]) if j != i and not o.get("tenant") and o.get("reservedFor")]
        if reserved:
            text += " %s is reserved for someone arriving later." % ", ".join(s for s, _o in reserved)
        return R("roommates", text, [{"type": "table", "columns": ["Bed", "Tenant", "Until"], "rows": rows}] if rows else [],
                 nav={"tab": "dashboard", "roomId": r["id"]})
    if kind:
        want = kind.group(2)
        if now:
            r, i, b = now[0][2]
            typ, gen, where = b.get("residentType") or "", b.get("residentGender") or "", "staying in Room %s, %s" % (r.get("room"), smart.bed_label(b, i))
        elif res:
            p = res[0][2]
            typ, gen, where = p.get("demographic") or "", p.get("gender") or "", "a reserved client"
        else:
            h = old[0][2]
            typ, gen, where = h.get("residentType") or "", h.get("residentGender") or "", "in Tenant History"
        if want in ("student", "reviewee"):
            if not typ:
                return R("person_kind", "%s's resident group isn't saved, so I can't tell whether they're a %s." % (name, want))
            yes = typ.lower().startswith(want)
            return R("person_kind", "%s. %s is a %s (%s)." % ("Yes" if yes else "No", name, typ.lower(), where))
        g = {"male": "Male", "boy": "Male", "man": "Male", "female": "Female", "girl": "Female", "woman": "Female"}[want]
        if not gen:
            return R("person_kind", "%s's gender isn't saved, so I can't tell." % name)
        return R("person_kind", "%s. %s is %s (%s)." % ("Yes" if gen == g else "No", name, gen.lower(), where))
    if length:
        if now:
            r, i, b = now[0][2]
            start = smart.parse_iso(b.get("start"))
            if not start:
                return R("person_stay", "%s's check-in date isn't saved, so I can't tell how long they've stayed." % b.get("tenant"))
            d = (today - start).days
            return R("person_stay", "%s has been staying for %s (about %.1f months), since %s, in Room %s, %s." % (
                b.get("tenant"), _plural(d, "day"), d / 30.44, smart.pretty(start), r.get("room"), smart.bed_label(b, i)),
                nav={"tab": "dashboard", "roomId": r["id"]})
        if old:
            h = old[0][2]
            s, e = smart.parse_iso(h.get("start")), smart.parse_iso(h.get("end"))
            if s and e:
                return R("person_stay", "%s stayed %s (%s to %s) and has checked out." % (h.get("tenant"), _plural((e - s).days, "day"), smart.pretty(s), smart.pretty(e)),
                         nav={"tab": "history"})
        if res:
            return R("person_stay", "%s hasn't arrived yet. They are a reserved client, check-in %s." % (name, P._dt(res[0][2].get("checkIn")) or "not set"))
        return None
    # days left
    if now:
        r, i, b = now[0][2]
        end = smart.parse_iso(b.get("end"))
        if not end:
            return R("person_left", "%s has no check-out date set, so there's no end to count down to." % b.get("tenant"))
        d = (end - today).days
        if d < 0:
            text = "%s's stay ended %s ago (%s), so it is overdue. Extend it or check them out." % (b.get("tenant"), _plural(-d, "day"), smart.pretty(end))
        else:
            text = "%s has %s left: check-out on %s, from Room %s, %s." % (b.get("tenant"), _plural(d, "day"), P._dt(b.get("end")), r.get("room"), smart.bed_label(b, i))
        return R("person_left", text, nav={"tab": "dashboard", "roomId": r["id"]})
    if res:
        p = res[0][2]
        ci = smart.parse_iso(p.get("checkIn"))
        return R("person_left", "%s hasn't arrived yet. They check in %s%s." % (name, P._dt(p.get("checkIn")) or "on a date not set",
                                                                               (" (%s)" % P._days((ci - today).days)) if ci else ""))
    return R("person_left", "%s has already checked out, so there are no days left." % name, nav={"tab": "history"})


# ------------------------------------------------------------------------------------------ counts
TYPE_W = [("Student", r"\b(students?|estudyante)\b"), ("Reviewee", r"\breviewees?\b")]
GEN_W = [("Male", r"\b(males?|boys?|men|man|lalaki)\b"), ("Female", r"\b(females?|girls?|women|woman|ladies|babae)\b")]


def counts(cur, uid, rec, t, today, P):
    if not re.search(r"^(?:how many|number of|count of|total)\b", t):
        return None
    import expert
    refs = expert._rooms_in(t, rec)
    # tenants in one room: count the PEOPLE (a reserved bed is not a tenant yet)
    if refs and re.search(r"\b(tenants?|people|persons?|residents?|occupants?|boarders?|staying|living)\b", t) and not re.search(r"\b(vacan\w*|free|available|beds?)\b", t):
        room, tok = refs[0]
        if room is None:
            return R("room_missing", "I can't find Room %s in your records." % tok.upper())
        people = [(smart.bed_label(b, i), b) for i, b in enumerate(room["beds"]) if b.get("tenant")]
        res = [smart.bed_label(b, i) for i, b in enumerate(room["beds"]) if not b.get("tenant") and b.get("reservedFor")]
        text = "Room %s has %s staying now%s" % (room.get("room"), _plural(len(people), "tenant"),
                                               (": " + ", ".join("%s (%s)" % (b.get("tenant"), s) for s, b in people)) if people else "")
        text += ". %d of %d beds are vacant" % (sum(1 for b in room["beds"] if expert.bed_status(room, b, today) == "vacant"), len(room["beds"]))
        text += (", and %s %s reserved for someone arriving later." % (", ".join(res), "is" if len(res) == 1 else "are")) if res else "."
        return R("room_tenants", text, nav={"tab": "dashboard", "roomId": room["id"]})
    if refs:
        return None
    if re.search(r"\b(vacan\w*|free|available|empty|full|overdue|reserv\w*|left|checked out|check ?outs?|check ?ins?|leaving|days?|weeks?|months?)\b", t):
        return None
    typ = [k for k, p in TYPE_W if re.search(p, t)]
    gen = [k for k, p in GEN_W if re.search(p, t)]
    if re.search(r"\brooms?\b", t):
        conds = []
        if gen:
            conds.append(("gender", gen[0], lambda r, g=gen[0]: (r.get("gender") or "Mixed") == g))
        elif re.search(r"\bmixed\b", t):
            conds.append(("gender", "Mixed", lambda r: (r.get("gender") or "Mixed") == "Mixed"))
        if typ:
            conds.append(("group", typ[0] + "s", lambda r, g=typ[0] + "s": (r.get("demographic") or "Mixed") == g))
        if re.search(r"\b(non[- ]?ac|non[- ]?aircon\w*|without (ac|aircon\w*)|no aircon)\b", t):
            conds.append(("ac", "Non-AC", lambda r: not P._yes(r.get("ac"))))
        elif re.search(r"\b(ac|aircon\w*|air ?con\w*|air[- ]?conditioned)\b", t):
            conds.append(("ac", "AC", lambda r: P._yes(r.get("ac"))))
        if re.search(r"\b(whole[- ]room|private)\b", t):
            conds.append(("mode", "private (whole room)", lambda r: r.get("tenancyMode") == "Whole Room"))
        elif re.search(r"\bbed ?space\b", t):
            conds.append(("mode", "Bedspace", lambda r: (r.get("tenancyMode") or "Bedspace") == "Bedspace"))
        if not conds:
            return None
        rooms = [r for r in rec.rooms if all(c[2](r) for c in conds)]
        label = " ".join(c[1] for c in conds)
        text = "You have %s %s room%s%s" % (len(rooms), label, "" if len(rooms) == 1 else "s",
                                            (": " + ", ".join(str(r.get("room")) for r in rooms[:20])) if rooms else "")
        if gen and gen[0] != "Mixed":
            mixed = sum(1 for r in rec.rooms if (r.get("gender") or "Mixed") == "Mixed")
            if mixed:
                text += ". %s Mixed room%s also take %s residents" % (mixed, "" if mixed == 1 else "s", gen[0].lower())
        return R("rooms_count", text + ".", [{"type": "table", "columns": ["Room", "Beds", "Gender", "Group", "AC"],
                                              "rows": [[r.get("room"), len(r["beds"]), r.get("gender") or "Mixed", r.get("demographic") or "Mixed",
                                                        "AC" if P._yes(r.get("ac")) else "Non-AC"] for r in rooms]}])
    if not (typ or gen):
        return None
    if re.search(r"\bbeds?\b", t):
        return None
    people = [b for _r, _i, b in rec.occupied()]
    pick = [b for b in people if (not typ or (b.get("residentType") or "").lower().startswith(typ[0].lower())) and
            (not gen or (b.get("residentGender") or "") == gen[0])]
    label = " ".join(([gen[0].lower()] if gen else []) + ([typ[0].lower()] if typ else []))
    text = "%d %s %s staying now, out of %d tenants." % (len(pick), label, "tenant is" if len(pick) == 1 else "tenants are", len(people))
    if gen and not typ:
        st = sum(1 for b in pick if (b.get("residentType") or "").lower().startswith("student"))
        text += " %d are students and %d are reviewees." % (st, len(pick) - st)
    elif typ and not gen:
        m = sum(1 for b in pick if b.get("residentGender") == "Male")
        text += " %d are male and %d are female." % (m, len(pick) - m)
    return R("tenants_kind", text)


# ------------------------------------------------------------------------------------------ rankings, rates, averages, comparisons
def ranks(cur, uid, rec, t, today, P):
    m = re.search(r"\b(most|least|fewest|lowest|highest|biggest number of|smallest number of)\s+(tenants|residents|people|occupants|boarders|occupied beds)\b", t)
    if not m or not re.search(r"\b(which|what|who|show|list|room)\b", t):
        return None
    rows = sorted([(sum(1 for b in r["beds"] if b.get("tenant")), r) for r in rec.rooms], key=lambda x: x[0],
                  reverse=m.group(1) in ("most", "highest", "biggest number of"))
    if not rows:
        return None
    best = rows[0][0]
    top = [r for n, r in rows if n == best]
    most = m.group(1) in ("most", "highest", "biggest number of")
    text = "%s %s the %s tenants: %s (%s of %s beds)." % (
        ", ".join("Room %s" % r.get("room") for r in top[:6]), "has" if len(top) == 1 else "have", "most" if most else "fewest",
        _plural(best, "tenant"), best, len(top[0]["beds"]) if len(top) == 1 else "their")
    if len(top) > 1:
        text = "%d rooms are tied with %s each: %s." % (len(top), _plural(best, "tenant"), ", ".join("Room %s" % r.get("room") for r in top[:10]))
    table = [[r.get("room"), n, len(r["beds"]), _p(n, len(r["beds"]))] for n, r in rows[:10]]
    return R("rooms_by_tenants", text, [{"type": "table", "columns": ["Room", "Tenants", "Beds", "Filled"], "rows": table}])


def _group_of(t):
    if re.search(r"\b(females?|girls?|women|ladies)\b", t):
        return "Female", lambda r: (r.get("gender") or "Mixed") == "Female", "female rooms"
    if re.search(r"\b(males?|boys?|men)\b", t):
        return "Male", lambda r: (r.get("gender") or "Mixed") == "Male", "male rooms"
    if re.search(r"\bmixed\b", t):
        return "Mixed", lambda r: (r.get("gender") or "Mixed") == "Mixed", "mixed rooms"
    if re.search(r"\bstudents?\b", t):
        return "Students", lambda r: (r.get("demographic") or "Mixed") == "Students", "student rooms"
    if re.search(r"\breviewees?\b", t):
        return "Reviewees", lambda r: (r.get("demographic") or "Mixed") == "Reviewees", "reviewee rooms"
    if re.search(r"\b(non[- ]?ac|non[- ]?aircon)\b", t):
        return "Non-AC", lambda r: not _yes(r.get("ac")), "non-aircon rooms"
    if re.search(r"\b(ac|aircon\w*|air ?con\w*|air[- ]?conditioned)\b", t):
        return "AC", lambda r: _yes(r.get("ac")), "aircon rooms"
    return None


def _yes(v):
    return v is True or str(v).strip().lower() in ("true", "yes", "1", "on")


def _tally(rooms, today):
    import expert
    c = {"beds": 0, "vacant": 0, "occupied": 0, "reserved": 0}
    for r in rooms:
        for b in r["beds"]:
            st = expert.bed_status(r, b, today)
            c["beds"] += 1
            if st == "vacant":
                c["vacant"] += 1
            elif st == "reserved":
                c["reserved"] += 1
            else:
                c["occupied"] += 1
    return c


def rates(cur, uid, rec, t, today, P):
    if not re.search(r"\b(vacancy|occupancy)\s*(rate|percentage|percent|%|level)?\b", t) or re.search(r"\b(mean\w*|formula|define|definition|computed|calculated)\b", t):
        return None
    g = _group_of(t)
    if not g:
        return None
    name, ok, label = g
    rooms = [r for r in rec.rooms if ok(r)]
    if not rooms:
        return R("rates_group", "You have no %s." % label)
    c = _tally(rooms, today)
    text = "In your %s (%s, %d beds): occupancy %s and vacancy %s. %d occupied, %d vacant and %d reserved." % (
        label, _plural(len(rooms), "room"), c["beds"], _p(c["occupied"], c["beds"]), _p(c["vacant"], c["beds"]), c["occupied"], c["vacant"], c["reserved"])
    if name in ("Male", "Female"):
        text += " Mixed rooms are counted separately."
    return R("rates_group", text, [{"type": "note", "text": "Occupancy = occupied ÷ all beds. Vacancy = vacant ÷ all beds. Reserved beds are neither."}])


def compare_groups(cur, uid, rec, t, today, P):
    if not (re.search(r"\b(compare|comparison|vs\.?|versus|difference between)\b", t) and
            re.search(r"\bmales?\b", t) and re.search(r"\bfemales?\b", t) and not re.search(r"\b(tenants?|people|residents?)\b(?! occupancy)", t)):
        return None
    rows, parts = [], []
    for g in ("Male", "Female", "Mixed"):
        rooms = [r for r in rec.rooms if (r.get("gender") or "Mixed") == g]
        if not rooms:
            continue
        c = _tally(rooms, today)
        rows.append([g, len(rooms), c["beds"], c["occupied"], c["vacant"], c["reserved"], _p(c["occupied"], c["beds"]), _p(c["vacant"], c["beds"])])
        parts.append("%s rooms %s occupied (%d of %d beds, %d vacant)" % (g, _p(c["occupied"], c["beds"]), c["occupied"], c["beds"], c["vacant"]))
    if not rows:
        return None
    occ = {r[0]: float(r[6].rstrip("%")) for r in rows}
    hi = max(occ, key=occ.get)
    text = "; ".join(parts) + ". %s rooms are the fullest." % hi
    return R("compare_gender", text, [{"type": "table", "columns": ["Rooms", "Count", "Beds", "Occupied", "Vacant", "Reserved", "Occupancy", "Vacancy"], "rows": rows}])


def avg_stay(cur, uid, rec, t, today, P):
    if not re.search(r"\baverage\b.*\b(stay|stays|length|duration)\b|\b(stay|length of stay)\b.*\baverage\b", t):
        return None
    typ = [k for k, p in TYPE_W if re.search(p, t)]
    gen = [k for k, p in GEN_W if re.search(p, t)]
    if not (typ or gen):
        return None
    stays = [(b.get("start"), b.get("end"), b.get("residentType"), b.get("residentGender")) for _r, _i, b in rec.occupied()]
    stays += [(h.get("start"), h.get("end"), h.get("residentType"), h.get("residentGender")) for h in P._history(cur, uid)]
    days = []
    for s, e, ty, ge in stays:
        s, e = smart.parse_iso(s), smart.parse_iso(e)
        if not (s and e and e >= s):
            continue
        if typ and not str(ty or "").lower().startswith(typ[0].lower()):
            continue
        if gen and (ge or "") != gen[0]:
            continue
        days.append((e - s).days)
    label = " ".join(([gen[0].lower()] if gen else []) + ([typ[0].lower() + "s"] if typ else ["tenants"]))
    if not days:
        return R("contracts_average", "I have no %s with both a check-in and a check-out date, so I can't work out an average." % label)
    avg = sum(days) / len(days)
    return R("contracts_average", "The average stay for %s is %d days (about %.1f months), from %s with both dates. Shortest %s, longest %s." % (
        label, round(avg), avg / 30.44, _plural(len(days), "stay"), _plural(min(days), "day"), _plural(max(days), "day")))


# ------------------------------------------------------------------------------------------ periods: check-outs, check-ins, busiest day, temporary guests
def _one_date(s, today):
    s = s.strip()
    m = re.search(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b%s\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(20\d\d))?" % MON, s) or \
        re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?%s\b(?:,?\s+(20\d\d))?" % MON, s)
    if not m:
        return None
    g = m.groups()
    if g[0].isdigit():
        day, mon, yr = int(g[0]), _mon(g[1]), g[2]
    else:
        mon, day, yr = _mon(g[0]), int(g[1]), g[2]
    year = int(yr) if yr else today.year
    try:
        d = date(year, mon, day)
    except ValueError:
        return None
    if not yr and (today - d).days > 180:
        d = date(year + 1, mon, day)
    return d


def period(t, today):
    """-> (start, end, label, explicit) or None."""
    m = re.search(r"\b(?:between|from)\s+(.+?)\s+(?:and|to|until|till|through|-)\s+(.+?)(?=\s+(?:who|for)\b|[?.!]|$)", t)
    if m:
        a, b = _one_date(m.group(1), today), _one_date(m.group(2), today)
        if a and b:
            if b < a:
                a, b = b, a
            return a, b, "%s to %s" % (smart.pretty(a), smart.pretty(b)), True
    d = _one_date(t, today)
    if d:
        return d, d, "on %s" % smart.pretty(d), True
    if re.search(r"\btoday\b|\bngayon\b|\bkaron\b", t):
        return today, today, "today", True
    if re.search(r"\btomorrow\b|\bbukas\b|\bugma\b", t):
        d = today + timedelta(days=1)
        return d, d, "tomorrow", True
    if re.search(r"\bthis weekend\b", t):
        s = today + timedelta(days=(5 - today.weekday()) % 7)
        return s, s + timedelta(days=1), "this weekend", True
    if re.search(r"\bnext week\b", t):
        s = today + timedelta(days=7 - today.weekday())
        return s, s + timedelta(days=6), "next week (%s to %s)" % (smart.pretty(s), smart.pretty(s + timedelta(days=6))), True
    if re.search(r"\bthis week\b", t):                 # the next 7 days, the same as the check-out answer for "this week"
        return today, today + timedelta(days=6), "this week (%s to %s)" % (smart.pretty(today), smart.pretty(today + timedelta(days=6))), True
    if re.search(r"\bnext month\b", t):
        s = add_months(date(today.year, today.month, 1), 1)
        return s, date(s.year, s.month, calendar.monthrange(s.year, s.month)[1]), "in %s %d" % (MONTHS[s.month - 1].capitalize(), s.year), True
    if re.search(r"\bthis month\b", t):
        return today, date(today.year, today.month, calendar.monthrange(today.year, today.month)[1]), "this month", True
    m = re.search(r"\b%s\b(?:\s+(20\d\d))?" % MON, t)
    if m:
        mon = _mon(m.group(1))
        year = int(m.group(2)) if m.group(2) else (today.year if mon >= today.month else today.year + 1)
        s = date(year, mon, 1)
        return s, date(year, mon, calendar.monthrange(year, mon)[1]), "in %s %d" % (MONTHS[mon - 1].capitalize(), year), True
    return None


OUT_W = r"\b(checks? ?outs?|checkouts?|check[- ]outs?|leav\w*|moving out|move out|moves out|departures?|depart\w*|ending|ends|expir\w*|due)\b"
IN_W = r"\b(checks? ?ins?|checkins?|check[- ]ins?|arriv\w*|arrivals?|coming|come in|comes in|moving in|move in|moves in|new tenants?|incoming)\b"


def ranges(cur, uid, rec, t, today, P):
    if not re.search(r"\b(who|whos|how many|list|show|any|which|what|when|number of|give me|tell me|busiest)\b", t):
        return None
    if re.search(r"\b(left|checked out|moved out|departed)\b", t) and not re.search(r"\b(will|going to)\b", t):
        return None                                    # the past: Tenant History answers
    busiest = re.search(r"\b(busiest|most (check ?outs|checkouts|departures|check ?ins|checkins|arrivals))\b", t)
    temp = re.search(r"\b(temporary|temp)\s+(guests?|clients?|stays?)\b", t)
    is_in, is_out = bool(re.search(IN_W, t)), bool(re.search(OUT_W, t))
    if not (busiest or temp or is_in or is_out):
        return None
    per = period(t, today)
    if busiest:
        a, b, label, _x = per or (today, date(today.year, today.month, calendar.monthrange(today.year, today.month)[1]), "this month", False)
        want_in = bool(re.search(r"check ?ins|checkins|arrivals", busiest.group(0)))
        items = _arrivals(rec, a, b) if want_in else _departures(rec, a, b)
        if not items:
            return R("busiest_day", "There are no %s %s." % ("check-ins" if want_in else "check-outs", label))
        by = {}
        for d, who, where in items:
            by.setdefault(d, []).append("%s (%s)" % (who, where))
        top = max(by.values(), key=len)
        days = [d for d, v in by.items() if len(v) == len(top)]
        if len(top) == 1:
            return R("busiest_day", "No day stands out %s: there %s %s, each on a different day (%s)." % (
                label, "is" if len(items) == 1 else "are", _plural(len(items), "check-in" if want_in else "check-out"),
                ", ".join(smart.pretty(d) for d in sorted(by))))
        if len(days) > 3:
            return R("busiest_day", "%d days are tied %s with %s each: %s." % (len(days), label, _plural(len(top), "check-in" if want_in else "check-out"),
                                                                             ", ".join(smart.pretty(d) for d in sorted(days))))
        text = "The busiest day %s is %s with %s: %s." % (label, " and ".join(smart.pretty(d) for d in sorted(days)), _plural(len(top), "check-in" if want_in else "check-out"),
                                                         "; ".join(by[sorted(days)[0]]))
        rows = [[smart.pretty(d), len(v)] for d, v in sorted(by.items())]
        return R("busiest_day", text, [{"type": "table", "columns": ["Date", "Check-ins" if want_in else "Check-outs"], "rows": rows}])
    if not per:
        return None
    a, b, label, _x = per
    if temp:
        rows = [c for c in rec.temps if c.get("status") != "Checked out" and (smart.parse_iso(c.get("start")) or a) <= b and (smart.parse_iso(c.get("end")) or b) >= a]
        if not rows:
            return R("temps_period", "No temporary guests %s." % label)
        return R("temps_period", "%s %s: %s." % (_plural(len(rows), "temporary guest"), label, "; ".join(
            "%s in Room %s, %s, %s to %s" % (c.get("name"), c.get("room"), c.get("slot"), smart.pretty(c.get("start")), smart.pretty(c.get("end"))) for c in rows[:10])))
    if is_in and not is_out:
        items = _arrivals(rec, a, b)
        kind, intent = "check-in", "checkins_period"
    elif is_out and not is_in:
        # "this week / today / tomorrow / next month" check-outs already have a good answer; months, dates and ranges don't
        if re.search(r"\b(today|tomorrow|this week|next month|this month)\b", t) and not re.search(r"\bbetween|from\b", t):
            return None
        items = _departures(rec, a, b)
        kind, intent = "check-out", "checkouts_period"
    else:
        return None
    if not items:
        return R(intent, "No %ss %s." % (kind, label))
    many = re.search(r"\bhow many|number of\b", t)
    text = "%s %s: %s%s." % (_plural(len(items), kind), label, "; ".join("%s (%s) on %s" % (w, where, smart.pretty(d)) for d, w, where in items[:8]),
                             " and %d more" % (len(items) - 8) if len(items) > 8 else "")
    if many and len(items) > 8:
        text = "%s %s. The list is in the table." % (_plural(len(items), kind), label)
    return R(intent, text, [{"type": "table", "columns": ["Name", "Where", "Date"], "rows": [[w, where, smart.pretty(d)] for d, w, where in items]}])


def _departures(rec, a, b):
    out = []
    for r, i, bed in rec.occupied():
        e = smart.parse_iso(bed.get("end"))
        if e and a <= e <= b:
            out.append((e, bed.get("tenant"), "Room %s, %s" % (r.get("room"), smart.bed_label(bed, i))))
    return sorted(out, key=lambda x: (x[0], str(x[1])))


def _arrivals(rec, a, b):
    out = []
    for p in rec.prospects:
        if p.get("checkedIn") or p.get("checkedOut"):
            continue
        d = smart.parse_iso(p.get("checkIn"))
        if d and a <= d <= b:
            rb = p.get("reservedBed") or {}
            room = rec.room(rb.get("roomId")) if rb.get("roomId") else None
            out.append((d, p.get("name"), ("Room %s, %s" % (room.get("room"), rb.get("slot"))) if room else "no bed chosen yet"))
    for c in rec.temps:
        d = smart.parse_iso(c.get("start"))
        if c.get("status") != "Checked out" and d and a <= d <= b:
            out.append((d, "%s (temporary)" % c.get("name"), "Room %s, %s" % (c.get("room"), c.get("slot"))))
    return sorted(out, key=lambda x: (x[0], str(x[1])))


# ------------------------------------------------------------------------------------------ facts about the app
def app_facts(t):
    if re.search(r"\b(difference|different|vs\.?|versus|compare)\b.*\b(rooms?|whole room|private)\b.*\bbed ?spac\w*|\bbed ?spac\w*\b.*\b(difference|vs\.?|versus)\b|"
                 r"^what(?:'s| is)? (?:a |the )?(?:bed ?spacer?|whole room|private room)\??$", t):
        return R("tenancy_explained",
                 "Bedspace means each bed is rented to a different person, so strangers can share the room and every bed counts on its own. "
                 "Whole Room (private room) means the room is rented to one person or one group: once someone checks in, the other beds count as "
                 "occupied too, so nobody else is placed there. You choose this under Tenancy when you add or edit a room. The Type field "
                 "(Room or Bedspacer) is only a label on the room card.")
    if re.search(r"\b(how long|until when|kept|keep|stored|store|retention|deleted|delete|expire\w*|erased|saved)\b.*\b(tenant )?history\b|"
                 r"\bhistory\b.*\b(kept|keep|stored|deleted|expire\w*|how long|erased|last)\b", t) and not re.search(r"^(open|show|go)\b", t):
        return R("history_kept", "Tenant History keeps each record for 2 years after the check-out, then deletes it automatically. The table shows "
                                 "how many days each record has left. If you need it longer, print the page (Save as PDF) before it expires.",
                 nav={"tab": "history"})
    if re.search(r"\b(offline|off-line|without (the )?(internet|wifi|wi-fi|data|connection)|no (internet|wifi|connection)|walang internet|walay internet)\b", t):
        return R("offline", "Not fully. Your records are saved on the tracker's server, so the page needs a connection to it to load and save. "
                            "In local test mode (START-LOCAL.bat) the server runs on this computer, so it works without internet. Voice typing "
                            "and Chrome's Google voice always need internet.")
    return None


def move_same_room(cur, uid, rec, t, today, P):
    """'move Carlo Santos to bed 4' (no room named). The app's Move / Transfer only offers beds in OTHER rooms."""
    m = re.match(r"^(?:move|transfer)\s+(.+?)\s+to\s+bed\s*(?:no\.?\s*|number\s*)?(\d{1,2})$", t.rstrip(" ?.!"))
    if not m:
        return None
    hits = P._find_people(m.group(1), [("now", b.get("tenant"), (r, i, b)) for r, i, b in rec.occupied()])
    if not hits:
        return None
    r, i, b = hits[0][2]
    n = int(m.group(2))
    if n < 1 or n > len(r["beds"]):
        return R("clarify", "Room %s only has %d beds, so there is no Bed %d there. Which room should %s move to?" % (r.get("room"), len(r["beds"]), n, b.get("tenant")))
    if n - 1 == i:
        return R("clarify", "%s is already in Room %s, Bed %d." % (b.get("tenant"), r.get("room"), n))
    return R("clarify", "Move (Transfer) only moves a tenant to a bed in another room, so I can't move %s from Bed %d to Bed %d inside Room %s. "
             "Tell me another room, for example “move %s to room S-102 bed 5”." % (b.get("tenant"), i + 1, n, r.get("room"), b.get("tenant")),
             suggestions=["Show the vacant beds"])


def can_you_change(t):
    # "can you edit my data?" arrives here as "edit my data?" ("can you" was already taken off)
    t = re.sub(r"^(?=(?:edit|change|update|modify|manage)\s+(?:my|the|our)\s+(?:data|records?|database|info\w*)\s*[?.!]*$)", "can you ", t)
    if re.match(r"^(?:can|could|will|do|are)\s+(?:you|u)\s+(?:able to\s+)?(?:edit|change|update|modify|make changes|do changes|write|save|manage|delete|add|remove)"
                r"(?:\s+(?:to|in|on))?(?:\s+(?:my|the|our|your))?(?:\s+(?:data|records?|rooms?|tenants?|info\w*|database|beds?|reservations?|anything|things|stuff))?\s*[?.!]*$", t):
        return R("ask_to_change", "Yes. I can prepare changes to your records: add, edit or delete a room, check tenants in or out, extend stays, move "
                 "tenants to another room, reserve beds, add temporary guests and update contact numbers. Tell me exactly what to do, for example "
                 "“extend Ana Cruz until June 30”. I show you what I understood, and nothing is saved until you press Confirm.",
                 suggestions=["Check out a tenant", "Reserve a bed"])
    return None
