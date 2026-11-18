"""precise3.py: third set of "brain" rules (2026-11-17). Used by precise.py.

  shape_command   delete / rename / recolour / reshape a hallway shape by its name ("delete cr in the hallway layout")
  who_named       "who is Carlo?" when several people share the name, a name on its own, "info about Carlo Santos"
  bed_tenant      "who is the tenant in S-101 bed 3"
  pronouns        remember the last person talked about, so "when does she check out?" knows who "she" is"""
import re
from datetime import datetime, timezone

import agent
import smart
from precise2 import KNOW, _looks_like_name

R = agent.reply


# ------------------------------------------------------------------------------------------ hallway shapes
COLORS = {"red": "#e57373", "pink": "#f48fb1", "orange": "#ffb74d", "yellow": "#fff176", "green": "#81c784", "blue": "#64b5f6",
          "light blue": "#b3e5fc", "navy": "#3f51b5", "purple": "#ba68c8", "violet": "#ba68c8", "brown": "#a1887f", "gray": "#bdbdbd",
          "grey": "#bdbdbd", "black": "#424242", "white": "#ffffff", "teal": "#4db6ac", "mint": "#dce8e4"}
GEOS = ("rectangle", "circle", "triangle")
DELETE = ("delete", "remove", "erase", "take out", "take away", "get rid of")


def _shape_hits(t, shapes):
    """Shapes whose label is named in the text, as whole words ('cr' finds 'Cr', 'comfort room' finds 'Comfort Room').
    The longest matching label wins, so 'cr 2' beats 'cr'."""
    hits = []
    for s in shapes:
        label = re.sub(r"\s+", " ", str(s.get("label") or "").lower()).strip()
        if label and re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(label), t):
            hits.append((len(label), s))
    if not hits:
        return []
    top = max(n for n, _s in hits)
    return [s for n, s in hits if n == top]


def shape_command(cur, uid, rec, t, today, P):
    t = re.sub(r"\s+", " ", t.strip(" ?.!"))
    verb = re.match(r"^(delete|remove|erase|take out|take away|get rid of|rename|change|edit|update|make|turn|set|colou?r|paint|recolou?r|reshape|move)\b", t)
    if not verb:
        return None
    v = verb.group(1)
    where = re.search(r"\b(hallway|layout|map|floor plan|shape|facility|walkway|landmark)\b", t) or \
        (re.search(r"\bcolou?r\b.*\b(to|into)\b|\b(circle|rectangle|triangle)\b", t) and not re.search(r"\b(room|bed|tenant|page|theme|mode)\b", t))
    shapes = list(rec.shapes or [])
    body = re.sub(r"\b(in|on|from|at) (the )?(hallway( layout)?|layout|map|floor plan)\b", " ", t)
    hits = _shape_hits(body, shapes)
    import expert
    if not hits:
        if where and (v in DELETE + ("rename",) or re.search(r"\bcolou?r|paint|circle|rectangle|triangle\b", t)):
            names = ", ".join("“%s”" % s.get("label") for s in shapes[:15]) or "none yet"
            return R("clarify", "I can't find a hallway shape with that name. Your hallway shapes: %s." % names, nav={"tab": "hallway"})
        return None
    if expert._rooms_in(t, rec) and not where:
        return None                                    # "delete room S-101" is about a room
    if len(hits) > 1:
        return R("clarify", "%d hallway shapes are called “%s”. Rename one of them on the Hallway Layout first." % (len(hits), hits[0].get("label")),
                 nav={"tab": "hallway"})
    s = hits[0]
    label = str(s.get("label"))
    desc = "hallway %s “%s” (%s)" % (s.get("kind") or "facility", label, s.get("geometry") or "rectangle")
    if v in DELETE:
        summary = "delete the %s. This can't be undone." % desc
        return R("action_proposal", "Here's what I understood: %s Please check it and press Confirm. Nothing changes until you do." % summary,
                 action={"type": "delete_shape", "shapeId": s["id"], "summary": summary})
    low = label.lower()
    rest = body[body.find(low) + len(low):] if low in body else body
    changes, said = {}, []
    m = re.search(r"\b(?:to|as|into)\s+[\"“]?([a-z0-9][a-z0-9 '&/-]{0,30}?)[\"”]?$", rest)
    if m and (v == "rename" or re.search(r"\b(name|label|call\w*)\b", t)):
        new = m.group(1).strip()
        if new not in COLORS and new not in GEOS and new not in ("walkway", "facility"):
            new = new.upper() if len(new) <= 3 else " ".join(w.capitalize() for w in new.split())
            changes["label"] = new
            said.append("name to “%s”" % new)
    for g in GEOS:
        if re.search(r"\b%s\b" % g, rest) and g != s.get("geometry"):
            changes["geometry"] = g
            said.append("shape to %s" % g)
    for k in ("walkway", "facility"):
        if re.search(r"\b%s\b" % k, rest) and k != s.get("kind"):
            changes["kind"] = k
            said.append("type to %s" % k)
    hexm = re.search(r"#[0-9a-f]{6}\b", rest)
    if hexm:
        changes["color"] = hexm.group(0)
        said.append("colour to %s" % hexm.group(0))
    else:
        for name in sorted(COLORS, key=len, reverse=True):
            if re.search(r"\b%s\b" % name, rest):
                changes["color"] = COLORS[name]
                said.append("colour to %s" % name)
                break
    if not changes:
        if v == "move":
            return R("clarify", "Shapes are moved by dragging them on the Hallway Layout (press Layout locked to unlock it first). "
                                "I can delete a shape or change its name, shape, type or colour.", nav={"tab": "hallway"})
        return R("clarify", "What should I change on the %s? I can change its name, its shape (rectangle, circle or triangle), its type "
                            "(facility or walkway) or its colour." % desc, nav={"tab": "hallway"})
    summary = "in the %s, change %s." % (desc, ", ".join(said))
    return R("action_proposal", "Here's what I understood: %s Please check it and press Confirm. Nothing changes until you do." % summary,
             action={"type": "edit_shape", "shapeId": s["id"], "changes": changes, "summary": summary})


# ------------------------------------------------------------------------------------------ people
NAME_ONLY = re.compile(r"^([a-zñ][a-zñ'-]+(?:\s+[a-zñ][a-zñ'-]+){0,3})\s*[?.!]*$")
ABOUT = re.compile(r"^(?:info(?:rmation)?|profile|everything)\s+(?:about|on|of|for|ni)\s+(.+?)\s*[?.!]*$")   # "details of X" = contact details (expert)
SHOW = re.compile(r"^(?:tell me about|tell me everything about|show me|find|look up|search for|search)\s+(?:the\s+)?(?:tenant\s+|resident\s+|client\s+)?"
                  r"([a-zñ][a-zñ .'-]{1,40}?)\s*[?.!]*$")


def who_named(conn, uid, rec, t, today, P):
    """'who is Carlo?' (three Carlos), a name on its own ('Ana Rivera'), 'info about Carlo Santos'."""
    m = KNOW.match(t) or ABOUT.match(t) or SHOW.match(t) or NAME_ONLY.match(t)
    if not m:
        return None
    x = re.sub(r"^(?:the\s+)?(?:tenant|resident|client|guest|boarder)\s+", "", m.group(1).strip(" .-"))
    people = P._people(rec, P._history(conn.cursor(), uid))
    if not _looks_like_name(x, P, people):
        return None
    import expert
    full = [p for p in people if P._mentions(x, p[1])]
    if full:
        return expert.person_lookup(conn, uid, "find " + full[0][1].lower(), "find " + full[0][1].lower(), today)
    words = [w for w in re.findall(r"[a-zñ]+", x) if len(w) >= 2]
    part = [p for p in people
            if all(any(nw == w or (len(w) >= 3 and nw.startswith(w)) for nw in re.findall(r"[a-zñ]+", p[1].lower())) for w in words)]
    if not part:
        return None                                    # know_person answers "I don't know anyone named …"
    seen, rows = set(), []
    for kind, name, d in part:
        if (kind, name.lower()) in seen:
            continue
        seen.add((kind, name.lower()))
        if kind == "now":
            r, i, b = d
            rows.append([name, "tenant staying now", "Room %s, %s" % (r.get("room"), smart.bed_label(b, i))])
        elif kind == "reserved":
            rows.append([name, "reserved client", "check-in %s" % (P._dt(d.get("checkIn")) or "not set")])
        else:
            rows.append([name, "Tenant History", "was in Room %s, %s" % (d.get("room"), d.get("slot"))])
    if len(rows) == 1:
        return expert.person_lookup(conn, uid, "find " + rows[0][0].lower(), "find " + rows[0][0].lower(), today)
    typed = " ".join(w.capitalize() for w in words)
    return R("person_search", "I found %d people named %s: %s. Which one do you mean? Say the full name." % (
        len(rows), typed, "; ".join("%s (%s, %s)" % tuple(r) for r in rows[:8])),
        [{"type": "table", "columns": ["Name", "Record", "Where"], "rows": rows[:20]}])


def bed_tenant(cur, uid, rec, t, today, P):
    """'who is the tenant in S-101 bed 3', 'who is in bed 1 of room S-101', 'name of the tenant in room s-101 bed 5'."""
    if not re.search(r"\b(who|whos|name|tenant|occupant|resident|staying|sleeping)\b", t):
        return None
    bm = re.search(r"\bbed\s*(?:no\.?\s*|number\s*|#)?(\d{1,2})\b", t)
    if not bm or re.search(r"\b(move|transfer|check|reserve|book|extend|assign|put|add|register|place|insert|new|change|update|edit)\b", t):
        return None
    import expert
    refs = expert._rooms_in(t, rec)
    if not refs or refs[0][0] is None:
        return None
    room, n = refs[0][0], int(bm.group(1))
    if n < 1 or n > len(room["beds"]):
        return R("clarify", "Room %s has %d beds, so there is no Bed %d." % (room.get("room"), len(room["beds"]), n))
    b = room["beds"][n - 1]
    slot = smart.bed_label(b, n - 1)
    st = expert.bed_status(room, b, today)
    if b.get("tenant"):
        text = "Room %s, %s: %s, staying %s to %s%s." % (room.get("room"), slot, b.get("tenant"), P._dt(b.get("start")) or "?",
                                                        P._dt(b.get("end")) or "no end date",
                                                        " (overdue)" if st == "overdue" else " (temporary guest)" if st == "temporary" else "")
    elif b.get("reservedFor"):
        p = next((p for p in rec.prospects if p.get("id") == b.get("reservedFor")), None)
        text = "Room %s, %s is empty now and reserved for %s (check-in %s)." % (
            room.get("room"), slot, p.get("name") if p else "a reserved client", (P._dt(p.get("checkIn")) or "not set") if p else "not set")
    else:
        text = "Room %s, %s is vacant: nobody is staying there." % (room.get("room"), slot)
    return R("bed_tenant", text, nav={"tab": "dashboard", "roomId": room["id"]})


# ------------------------------------------------------------------------------------------ remembering who "she" is
PRONOUN = re.compile(r"\b(he|she|him|her|his|hers|they|them|their|theirs|siya|sya|niya|nya|kaniya|kanya|that person|that tenant|this tenant|"
                     r"that client|this client|the same person|same tenant)\b")
POSS_NOUN = (r"(?:room|rooms|bed|beds|contact|contacts|number|numbers|phone|mobile|emergency|address|email|check[- ]?out|checkout|check[- ]?in|"
             r"checkin|date|dates|stay|record|records|roommates?|name|details|info|information|profile|reason|history|end|start|contract|"
             r"gender|group|status|tenant|bed's)")
MEMORY_SECONDS = 1800


def fill_pronouns(conn, uid, q, cid, P):
    """'when does she check out?' -> 'when does ana rivera check out?' when Ana Rivera was the person talked about last,
    in this same chat, in the last 30 minutes. Nothing changes when the question already names someone."""
    if not cid or not PRONOUN.search(q):
        return q
    cur = conn.cursor()
    last = (smart.load_settings(cur, uid).get("lastPerson") or {})
    try:
        fresh = last.get("cid") == cid and datetime.now(timezone.utc).timestamp() - float(last.get("at") or 0) < MEMORY_SECONDS
    except (TypeError, ValueError):
        fresh = False
    if not fresh or not last.get("name"):
        return q
    rec = smart.Records(cur, uid)
    if any(P._mentions(q, p[1]) for p in P._people(rec, P._history(cur, uid))):
        return q                                       # a name is already there
    name = str(last["name"]).lower()
    t = q
    # "check her out" / "check him out" -> "check out NAME"
    t = re.sub(r"\bcheck\s+(?:him|her|them|siya|sya)\s+out\b", "check out " + name, t)
    # possessive: "her room", "his contact number", "their check-out date"
    t = re.sub(r"\b(?:his|her|their|niya|nya|kaniya|kanya)\s+(?=%s\b)" % POSS_NOUN, name + "'s ", t)
    t = re.sub(r"\b(?:that person|that tenant|this tenant|that client|this client|the same person|same tenant)\b", name, t)
    plural = re.search(r"\b(rooms|beds|tenants|people|residents|clients|guests|all|everyone|those|these)\b", t)
    t = re.sub(r"\b(?:he|she|him|her|hers|his|siya|sya)\b", name, t)
    if not plural:                                     # "they" can be plural ("how many beds do they have"): only for one person
        t = re.sub(r"\b(?:they|them|theirs)\b", name, t)
    return t


def remember_person(conn, uid, q, answer_text, cid, P):
    """After an answer: if the question (or, failing that, the answer) is about exactly one person, remember them."""
    if not cid:
        return
    try:
        cur = conn.cursor()
        rec = smart.Records(cur, uid)
        people = P._people(rec, P._history(cur, uid))
        names = {p[1] for p in people if P._mentions(q, p[1])}
        if not names and answer_text:
            names = {p[1] for p in people if P._mentions(answer_text[:400], p[1])}
        if len({n.lower() for n in names}) != 1:
            return
        with conn.transaction():
            st = smart.load_settings(cur, uid)
            st["lastPerson"] = {"name": sorted(names)[0], "cid": cid, "at": datetime.now(timezone.utc).timestamp()}
            smart.save_settings(cur, uid, st)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("could not remember the person")


# ------------------------------------------------------------------------------------------ more change requests
def resolve_more(conn, uid, q, today, P):
    """'update ana delas number to 0917…' -> 'change the contact number of ana dela to 0917…' (the wording smart.py knows)."""
    t = q.strip()
    m = re.match(r"^(?:update|change|set|edit|replace|new)\s+(?:the\s+)?(?:(?:contact|phone|mobile|cell(?:phone)?)\s+)?(?:number\s+of\s+)?(.+?)(?:'s|s)?\s+"
                 r"(?:(?:contact|phone|mobile|cell(?:phone)?)\s+)?(?:number|contact|phone|mobile)\s+(?:to|into|with|is)\s+(\+?\d[\d\s-]{6,})$", t)
    if not m:
        return q
    rec = smart.Records(conn.cursor(), uid)
    hits = P._find_people(m.group(1), [("now", b.get("tenant"), (r, i, b)) for r, i, b in rec.occupied()])
    if not hits:
        return q
    return "change the contact number of %s to %s" % (hits[0][1].lower(), re.sub(r"[\s-]", "", m.group(2)))


def rename_room(cur, uid, rec, t, today, P):
    """'rename room VINCE 123 to S-125': room names with spaces are found by their whole name."""
    m = re.match(r"^(?:rename|change the name of|change name of)\s+(?:room\s+)?(.+?)\s+(?:to|as|into)\s+(?:room\s+)?(.+?)\s*[?.!]*$", t)
    if not m:
        return None
    old = m.group(1).strip()
    room = next((r for r in rec.rooms if str(r.get("room") or "").lower() == old), None)
    if not room or not re.search(r"\s", old):
        return None                                    # one-word room names are already handled by smart.py
    new = m.group(2).strip()
    new = new.upper() if re.fullmatch(r"[a-z0-9-]+", new) and re.search(r"\d", new) else " ".join(w.capitalize() for w in new.split())
    if any(str(r.get("room") or "").lower() == new.lower() for r in rec.rooms):
        return R("clarify", "There is already a Room %s." % new)
    summary = "in Room %s, change name to %s." % (room.get("room"), new)
    return R("action_proposal", "Here's what I understood: %s Please check it and press Confirm. Nothing changes until you do." % summary,
             action={"type": "edit_room", "roomId": room["id"], "changes": {"room": new}, "summary": summary})


def temp_checkout(cur, uid, rec, t, today, P):
    """'check out the temporary guest Leo Tan' when there is no such guest: say so (it asked "which tenant?")."""
    m = re.match(r"^(?:check ?out|checkout|remove)\s+(?:the\s+)?(?:temporary|temp)\s+(?:guest|client)\s+(.+?)\s*[?.!]*$", t)
    if not m:
        return None
    active = [c for c in rec.temps if c.get("status") != "Checked out"]
    if P._find_people(m.group(1), [("temp", c.get("name"), c) for c in active]):
        return None                                    # found: smart.py prepares the check-out
    typed = " ".join(w.capitalize() for w in m.group(1).split())
    now = "; ".join("%s (Room %s, %s)" % (c.get("name"), c.get("room"), c.get("slot")) for c in active[:8]) or "none right now"
    return R("clarify", "I can't find a temporary guest named “%s”. Your temporary guests: %s." % (typed, now), nav={"tab": "temporary"})


def room_size(cur, uid, rec, t, today, P):
    """'what is the biggest room', 'smallest room', 'which rooms have the most beds'."""
    big = re.search(r"\b(biggest|largest|most beds|widest)\b", t)
    small = re.search(r"\b(smallest|tiniest|fewest beds|least beds)\b", t)
    if not (big or small) or not re.search(r"\brooms?\b", t) or re.search(r"\b(vacan\w*|free|tenants?|people|occupied)\b", t):
        return None
    if not rec.rooms:
        return None
    sizes = sorted(rec.rooms, key=lambda r: len(r["beds"]), reverse=bool(big))
    n = len(sizes[0]["beds"])
    top = [r for r in sizes if len(r["beds"]) == n]
    word = "biggest" if big else "smallest"
    names = ", ".join("Room %s" % r.get("room") for r in top[:12])
    text = ("%s is the %s room, with %d beds." % (names, word, n)) if len(top) == 1 else         ("%d rooms are the %s, with %d beds each: %s." % (len(top), word, n, names))
    rows = [[r.get("room"), len(r["beds"]), r.get("gender") or "Mixed", r.get("demographic") or "Mixed"] for r in sizes[:10]]
    return R("room_size", text, [{"type": "table", "columns": ["Room", "Beds", "Gender", "Group"], "rows": rows}])
