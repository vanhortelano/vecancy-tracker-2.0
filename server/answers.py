"""More answers for the Vacancy Assistant, computed from the signed-in account's own records.

Runs after the language step (lang.to_english), so Cebuano, Tagalog, Taglish and misspelled questions arrive here
as simple English. Covers the question list the owners collected: vacancy with several filters at once (gender,
student/reviewee, bedspace/whole room, floor, aircon, group size, dates), tenants and contracts, reservations,
records checks, operations, forecasts, branches (Super Admin) and marketing.

Privacy (same rules as the pages):
  * Names, contact numbers, emergency contacts and addresses come ONLY from the Branch Admin's own records and are
    shown ONLY on the Branch Admin page.
  * Dormitory Viewer, Marketing Directory and Super Admin answers never contain them (their data has no names).
  * Money (rent, payments, revenue) is not recorded in the app, so the assistant says so instead of guessing.
Nothing here changes data. Changes still go through smart.py's proposals, which the user must confirm.
"""
import re
from calendar import monthrange
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import agent
import agent_viewer
import smart
import vacancy_core as vc
from smart import bed_label, has, parse_iso, pretty
from store import KINDS, list_docs

R = agent.reply
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
       "a": 1, "an": 1, "single": 1, "couple": 2}
NUMW = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
ORD = {"ground": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}
VAC = r"\b(vacan\w*|available|availability|free|open|empty|space|spaces|slots?|left|unoccupied|room for|accommodate|fit|suitable|fits)\b"
ACTION_START = re.compile(r"^(please )?(check (in|out)|checkin|checkout|reserve|book|add|create|delete|remove|move|transfer|extend|"
                          r"cancel|update|change|set|edit|rename|put|assign|mark|make)\b")
QUESTIONISH = re.compile(r"\?|^(which|what|who|where|when|how|is|are|do|does|did|can|could|will|would|should|show|list|give|find|"
                         r"tell|count|any|check|display|summari[sz]e|compare|predict|generate|identify|calculate|forecast|recommend|"
                         r"suggest|create a (report|strategy|marketing)|report|analy[sz]e|i need|need|whats|wheres)\b")


def n_of(tok):
    return int(tok) if str(tok).isdigit() else NUM.get(tok)


def _plural(n, word, many=None):
    return "%d %s" % (n, word if n == 1 else (many or word + "s"))


# ============================================================================== filters from the question
class Want:
    """What the question asks for: who the bed is for, which rooms, and when."""

    def __init__(self, t, today, floors=None):
        self.t, self.today = t, today
        g = smart.gender_in(t)
        self.gender = g if g in ("Male", "Female") else None
        self.mixed_gender = bool(re.search(r"\bmixed[- ]gender\b|\bco-?ed\b|\bmixed rooms?\b", t))
        grp = smart.group_in(t)
        self.group = grp + "s" if grp else None
        self.mode = "Whole Room" if re.search(r"\bwhole[- ]?room|\bentire room|\bprivate room|\bsolo room\b", t) else \
            "Bedspace" if re.search(r"\bbed ?spac\w*|\bbedspacer|\bshared\b", t) else None
        self.ac = True if re.search(r"\b(aircon\w*|air-?con\w*|air[- ]conditioned|with ac)\b", t) else \
            False if re.search(r"\b(non-?aircon\w*|non-?ac|no aircon|fan room)\b", t) else None
        self.floor = None
        m = re.search(r"\b(ground|first|second|third|fourth|fifth|1st|2nd|3rd|4th)\s+floor\b|\bfloor\s*(\d)\b", t)
        if m:
            self.floor = ORD.get(m.group(1)) if m.group(1) else int(m.group(2))
        self.people = None
        m = re.search(r"\b(?:accommodate|fit|for|group of|room for|space for)\s+(?:a group of\s+)?" + NUMW +
                      r"\s+(?:people|persons|pax|tenants|students?|reviewees?|female|male|girls|boys|ladies|guys|of them)", t) or \
            re.search(r"\bgroup of\s+" + NUMW + r"\b", t)
        if m:
            self.people = n_of(m.group(1))
        self.start, self.end, self.when_label = self._window(t, today)
        # understand.exclusions() marks "don't include the rooms that already have someone coming in"
        self.no_incoming = bool(re.search(r"\bexcluding incoming\b", t))
        # "which one can be reserved next week": the question is about free beds, not about the reservation list
        self.bookable = bool(re.search(r"\b(can|could) (still )?(be )?(reserv|book)\w*|\b(reservable|bookable)\b|\bavailable (to|for) (reserv|book)\w*|"
                                       r"\bfree to (reserv|book)\w*", t))

    def _window(self, t, today):
        dates = smart.find_dates(t, today)
        start = end = None
        label = None
        for _pos, d, role in dates:
            if role == "end" and start:
                end = d
            elif start is None:
                start = d
            elif end is None:
                end = d
        if re.search(r"\bnext week\b", t) and not any(r == "start" for _p, _d, r in dates):
            start = today + timedelta(days=7 - today.weekday())
            label = "from next week (%s)" % pretty(start)
        if re.search(r"\bnext month\b", t) and not re.search(r"\bfor (a|one|1) month\b", t):
            y, mo = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            start = date(y, mo, 1)
            label = "from next month (%s)" % pretty(start)
        if re.search(r"\bnext semester\b", t):
            start = date(today.year + (1 if today.month >= 6 else 0), 6 if today.month < 6 else 1, 1) if today.month not in (1, 6) else today
            label = "from next semester (about %s)" % pretty(start)
        m = re.search(r"\bfor (?:a |an )?" + NUMW + r"?[- ]?(day|week|month|year)s?(?:[- ]stay)?\b", t) or \
            re.search(r"\b" + NUMW + r"[- ](day|week|month|year)s?[- ]stay\b", t)
        if m:
            k = n_of(m.group(1)) if m.group(1) else 1
            days = (k or 1) * {"day": 1, "week": 7, "month": 30, "year": 365}[m.group(2)]
            start = start or today
            end = start + timedelta(days=days)
        if start and end and end < start:
            start, end = end, start
        if start and end and start == end:            # "today … today" (often from the small talk around the question) is not a stay
            end = None
        if start and start < today:
            start = today
        if start and not label:
            label = ("from %s to %s" % (pretty(start), pretty(end))) if end else ("from %s" % pretty(start))
        elif start and end:
            label += " to %s" % pretty(end)
        return start, end, label

    def describe(self):
        parts = [x for x in [self.gender, ("student" if self.group == "Students" else "reviewee" if self.group == "Reviewees" else None),
                             "bedspace" if self.mode == "Bedspace" else "whole-room" if self.mode else None,
                             "aircon" if self.ac else "non-aircon" if self.ac is False else None] if x]
        s = " ".join(parts)
        if self.floor is not None:
            s += (" " if s else "") + "on the %s floor" % ({0: "ground", 1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}.get(self.floor, str(self.floor)))
        return s

    def room_ok(self, r, floor_of):
        if self.gender and (r.get("gender") or "Mixed") not in (self.gender, "Mixed"):
            return False
        if self.group and (r.get("demographic") or "Mixed") not in (self.group, "Mixed"):
            return False
        if self.mode and (r.get("tenancyMode") or "Bedspace") != self.mode:
            return False
        if self.ac is not None and bool(r.get("ac")) != self.ac:
            return False
        if self.floor is not None and floor_of(r) != self.floor:
            return False
        if self.mixed_gender and (r.get("gender") or "Mixed") != "Mixed":
            return False
        if self.no_incoming and any(b.get("reservedFor") or b.get("temporaryClientId") for b in r.get("beds") or []):
            return False
        return True


def bed_free(b, start, end, today):
    """Can a new person use this bed for [start, end]? Occupied beds count once their check-out date has passed."""
    if b.get("reservedFor") or b.get("temporaryClientId"):
        return False
    if not b.get("tenant"):
        return True
    e = parse_iso(b.get("end"))
    s = start or today
    # same-day turnover is fine: check-out is at 12:00 and check-in at 14:00 (same rule as Reserve Client)
    return bool(e and e <= s and s > today)


# ============================================================================== Branch Admin: records
class Data:
    def __init__(self, cur, uid, today):
        self.cur, self.uid, self.today = cur, uid, today
        self.rec = smart.Records(cur, uid)
        self._tenants = self._hist = self._floors = self._transfers = None

    @property
    def tenants(self):
        if self._tenants is None:
            self._tenants = {i: d for i, d, _v in list_docs(self.cur, KINDS["tenants"], [self.uid], limit=5000)}
        return self._tenants

    @property
    def hist(self):
        if self._hist is None:
            self._hist = [dict(d, id=i) for i, d, _v in list_docs(self.cur, KINDS["tenant_history"], [self.uid], limit=5000)]
        return self._hist

    @property
    def transfers(self):
        if self._transfers is None:
            self._transfers = [dict(d, id=i) for i, d, _v in list_docs(self.cur, KINDS["bed_transfers"], [self.uid], limit=2000)]
        return self._transfers

    @property
    def floors(self):
        """[(id, name)] in the order the Branch Admin set them up."""
        if self._floors is None:
            self._floors = []
            for i, d, _v in list_docs(self.cur, KINDS["settings"], [self.uid]):
                if i == "floors" and isinstance(d.get("floors"), list):
                    self._floors = [(f.get("id"), f.get("name") or "") for f in d["floors"] if isinstance(f, dict)]
        return self._floors

    def floor_no(self, r):
        fid = r.get("floor")
        for k, (i, name) in enumerate(self.floors):
            if i == fid:
                m = re.search(r"(\d+)", name) or None
                low = name.lower()
                for w, n in ORD.items():
                    if w in low:
                        return n
                return int(m.group(1)) if m else k + 1
        return None

    def floor_name(self, r):
        return next((n for i, n in self.floors if i == r.get("floor")), "")

    def info(self, b):
        return self.tenants.get(b.get("tenantId")) or {}

    def counts(self, r):
        beds = r["beds"]
        return {"total": len(beds), "vacant": sum(1 for b in beds if smart.bed_vacant(b)),
                "occupied": sum(1 for b in beds if b.get("tenant") or b.get("temporaryClientId")),
                "reserved": sum(1 for b in beds if b.get("reservedFor") and not b.get("tenant"))}


def _table(cols, rows):
    return {"type": "table", "columns": cols, "rows": rows}


def _list(items):
    return {"type": "list", "items": items}


def _note(text):
    return {"type": "note", "text": text}


def admin(conn, uid, t, ctx, today):
    """Branch Admin questions. t is the English question. Returns a reply or None."""
    t = re.sub(r"\b(my|our|this) (branch|dorm\w*)\b|\bbranch (mine|ko)\b", "my dorm", t)
    cur = conn.cursor()
    D = Data(cur, uid, today)
    if re.search(NOT_TRACKED_OPS, t) and re.search(r"\b(update|set|mark|change|put|make)\b", t):
        return R("not_tracked_ops", "Rooms don't have a maintenance status in the Vacancy Tracker yet, so I can't mark a room as under maintenance. "
                 "Nothing was changed.")
    if re.search(r"\b(delete|remove|wipe|erase|clear) (all|every|everything)\b", t) or re.search(r"\b(change|update|edit) (this |that |the |a )?tenants? (contract|check ?out|end) date\b", t):
        out = admin_policy(D, Want(t, today), t, today, ctx)
        if out:
            return out
    if ACTION_START.match(t) and not re.search(r"^(please )?(make|create|add|set)\b.{0,25}\b(list|report|summary|table|chart)\b", t):
        return None                                   # a command: smart.py prepares it for confirmation
    rooms = D.rec.rooms
    if not rooms:
        return None
    W = Want(t, today)
    floor_of = D.floor_no
    if re.search(r"\b(another|other|different) (branch\w*|dorm\w*)\b", t) and re.search(r"\b(tenants?|private|information|names?|contacts?|records?)\b", t):
        return R("privacy", "You can only see your own dormitory's tenants. Other branches' tenant information is private to their Branch Admins, "
                 "and not even a Super Admin can see it.")
    # comparing branches ("which branch is fullest", "all branches"), not "the occupied rooms in the branch" (= my own dorm)
    if (re.search(r"\b(branches|other (branch|dorm)\w*|each (branch|dorm)|every (branch|dorm)|all (the )?(branches|dorms))\b", t) or
            (re.search(r"\b(branch|place)\b", t) and re.search(r"\b(which|compare|highest|lowest|best|most|doing better)\b", t))):
        tot = sum(len(r["beds"]) for r in rooms)
        occ = sum(1 for _ in D.rec.occupied())
        return R("branch_admin_only", "Comparing branches is a Super Admin feature (they only see dormitories that approved sharing). "
                 "For your own dormitory: %d of %d beds occupied (%s), %s." % (occ, tot, agent._p(agent._pct(occ, tot)), _plural(len(D.rec.vacant_beds()), "vacant bed")))
    fn = [admin_policy, admin_scenarios, admin_insights, admin_operations, admin_checks, admin_reservations, admin_contracts,
          admin_tenants, admin_forecast, admin_rooms]
    if (W.no_incoming or W.bookable) and re.search(VAC + r"|\b(reserv|book)\w*", t):
        fn = [admin_rooms] + [f for f in fn if f is not admin_rooms]   # "which vacant rooms can be reserved …": free beds first
    for f in fn:
        out = f(D, W, t, today, ctx)
        if out:
            return out
    return None


# ---------------------------------------------------------------------------------- rooms & vacancy
def admin_rooms(D, W, t, today, ctx):
    rooms, floor_of = D.rec.rooms, D.floor_no
    pick = [r for r in rooms if W.room_ok(r, floor_of)]
    who = W.describe()
    for_who = (" for " + who) if who else ""

    def vac_of(r):
        free = [bed_label(b, i) for i, b in enumerate(r["beds"]) if bed_free(b, W.start, W.end, today)]
        if (r.get("tenancyMode") or "") == "Whole Room" and len(free) < len(r["beds"]):
            return []                                 # a whole room is rented as one: any guest blocks it
        return free

    if has(t, r"\b(occupancy|vacancy) rate\b", r"\bhow full\b", r"\bpercent(age)? (occupied|vacant)\b") and not has(t, r"\b(predict|expect|next|after|will|compare|last month)\b"):
        tot = sum(len(r["beds"]) for r in pick)
        occ = sum(D.counts(r)["occupied"] for r in pick)
        vac = sum(D.counts(r)["vacant"] for r in pick)
        res = sum(D.counts(r)["reserved"] for r in pick)
        return R("rates", "Occupancy %s and vacancy %s%s: %d occupied, %d vacant and %d reserved of %d beds." % (
            agent._p(agent._pct(occ, tot)), agent._p(agent._pct(vac, tot)), for_who, occ, vac, res, tot),
                 [_note("Occupancy = occupied ÷ all beds. Vacancy = vacant ÷ all beds. Reserved beds are neither vacant nor occupied.")])
    # a specific room
    rm = re.search(r"\broom\s*(?:no\.?|number|#)?\s*([a-z]?-?\d[\w-]*)", t)
    if rm and re.search(r"\b(occupied|occupancy|capacity|how many beds|status)\b", t) and not re.search(VAC, t):
        room = D.rec.room_by_name(rm.group(1)) or next((r for r in rooms if str(r.get("room")).lower().endswith("-" + rm.group(1).lower())), None)
        if not room:
            return R("room_missing", "I can't find Room %s. Your rooms are named like %s." % (rm.group(1).upper(), ", ".join(str(r["room"]) for r in rooms[:6])))
        c = D.counts(room)
        return R("room_status", "Room %s: %d beds (capacity %s) — %d occupied, %d vacant, %d reserved." % (room["room"], c["total"], room.get("capacity") or c["total"], c["occupied"], c["vacant"], c["reserved"]))
    if rm and re.search(VAC, t):
        room = D.rec.room_by_name(rm.group(1)) or next((r for r in rooms if str(r.get("room")).lower().endswith("-" + rm.group(1).lower())), None)
        if not room:
            return R("room_missing", "I can't find Room %s. Your rooms are named like %s." % (rm.group(1).upper(), ", ".join(str(r["room"]) for r in rooms[:6])))
        v = vac_of(room)
        when = (" " + W.when_label) if W.when_label else " right now"
        return R("room_vacancy", ("Yes: Room %s has %s%s (%s)." % (room["room"], _plural(len(v), "free bed"), when, ", ".join(v))) if v else
                 "Room %s has no free bed%s." % (room["room"], when))
    # rooms that are completely empty
    if has(t, r"\b(fully|completely|entirely|totally|wholly) (vacant|empty|free|available)\b", r"\bempty rooms?\b", r"\ball beds (are )?(free|vacant)\b",
           r"\brooms? with no (tenants|one|occupants)\b"):
        rows = [[r["room"], len(r["beds"]), r.get("gender") or "Mixed", r.get("demographic") or "Mixed"] for r in pick
                if r["beds"] and all(bed_free(b, W.start, W.end, today) for b in r["beds"])]
        if not rows:
            return R("rooms_empty", "No room%s is completely vacant%s." % (for_who, (" " + W.when_label) if W.when_label else " right now"))
        return R("rooms_empty", "%s completely vacant%s: %s." % (_plural(len(rows), "room is", "rooms are"), for_who, ", ".join(str(x[0]) for x in rows)),
                 [_table(["Room", "Beds", "Gender", "Group"], rows)])
    # almost full
    if has(t, r"\b(almost|nearly|close to) (full|occupied)\b", r"\bone bed left\b", r"\blast bed\b"):
        rows = [[r["room"], D.counts(r)["vacant"], len(r["beds"])] for r in pick if len(r["beds"]) > 1 and D.counts(r)["vacant"] == 1]
        return R("rooms_almost_full", ("%s almost full (one vacant bed left)%s: %s." % (_plural(len(rows), "room is", "rooms are"), for_who, ", ".join(str(x[0]) for x in rows)))
                 if rows else "No room%s is down to its last vacant bed." % for_who, [_table(["Room", "Vacant", "Beds"], rows)] if rows else [])
    # full rooms
    if has(t, r"\bfully (occupied|booked)\b", r"\bfull rooms?\b", r"\brooms? (that are |are )?(already )?full\b", r"\bno vacan\w*\b.*\brooms?\b",
           r"\b(unavailable|not available|cannot|cant) (be )?(for )?(reserv|book)\w*\b", r"\bwhich rooms? (is|are) full\b"):
        full = [r for r in pick if r["beds"] and not D.counts(r)["vacant"]]
        reserve = re.search(r"reserv|book", t)
        label = "can't take a reservation (no vacant bed)" if reserve else "fully occupied"
        if not full:
            return R("rooms_full", "No room%s is %s right now." % (for_who, label))
        return R("rooms_full", "%s %s%s: %s." % (_plural(len(full), "room", "rooms"), label, for_who, ", ".join(str(r["room"]) for r in full)),
                 [_table(["Room", "Beds", "Occupied", "Reserved"], [[r["room"], len(r["beds"]), D.counts(r)["occupied"], D.counts(r)["reserved"]] for r in full])])
    # exactly N vacant beds / only one
    m = re.search(r"\b(?:only|exactly|just)\s+" + NUMW + r"\s+(?:available|vacant|free|open)?\s*beds?\b", t) or \
        re.search(r"\b" + NUMW + r"\s+(?:available|vacant|free)\s+beds? (?:only|left)\b", t)
    if m and re.search(r"\brooms?\b", t):
        n = n_of(m.group(1))
        rows = [[r["room"], len(vac_of(r)), len(r["beds"]), ", ".join(vac_of(r))] for r in pick if len(vac_of(r)) == n]
        return R("rooms_exact", ("%s exactly %s%s: %s." % (_plural(len(rows), "room has", "rooms have"), _plural(n, "vacant bed"), for_who, ", ".join(str(x[0]) for x in rows)))
                 if rows else "No room%s has exactly %s." % (for_who, _plural(n, "vacant bed")), [_table(["Room", "Vacant", "Beds", "Which beds"], rows)] if rows else [])
    # mixed-gender rooms / occupancy
    if W.mixed_gender or has(t, r"\bmixed[- ]gender occupancy\b", r"\bboth (male|genders)\b"):
        rows = []
        for r in D.rec.rooms:
            gs = sorted({b.get("residentGender") for b in r["beds"] if b.get("tenant") and b.get("residentGender")})
            if (r.get("gender") or "Mixed") == "Mixed" or len(gs) > 1:
                rows.append([r["room"], r.get("gender") or "Mixed", ", ".join(gs) or "—", D.counts(r)["vacant"]])
        return R("rooms_mixed", ("%s mixed-gender: %s." % (_plural(len(rows), "room is", "rooms are"), ", ".join(str(x[0]) for x in rows))) if rows
                 else "No room is set as mixed gender, and no room has both male and female tenants.",
                 [_table(["Room", "Room setting", "Tenants now", "Vacant beds"], rows)] if rows else [])
    # by floor / which floor
    if has(t, r"\b(by|per|each|every) floor\b", r"\bwhich floor\b", r"\bfloors?\b.*\b(occupancy|vacan|full)\w*\b") and W.floor is None:
        if not D.floors:
            return R("floors_none", "Your dormitory has no floors set up yet, so I can't group by floor. Add floors on the Hallway Layout tab.")
        rows = []
        for fid, name in D.floors:
            rs = [r for r in D.rec.rooms if r.get("floor") == fid and W.room_ok(r, lambda _r: None)]
            tot = sum(len(r["beds"]) for r in rs)
            vac = sum(D.counts(r)["vacant"] for r in rs)
            occ = sum(D.counts(r)["occupied"] for r in rs)
            rows.append([name or "Floor", len(rs), tot, occ, vac, agent._p(agent._pct(occ, tot)) if tot else "—"])
        if has(t, r"\bwhich floor\b"):
            key = 3 if re.search(r"occup|full|busiest", t) else 4
            best = max(rows, key=lambda x: x[key]) if rows else None
            word = "highest occupancy" if key == 3 else "most vacant beds"
            return R("floors", "%s has the %s (%s)." % (best[0], word, best[5] if key == 3 else _plural(best[4], "vacant bed")), [_table(["Floor", "Rooms", "Beds", "Occupied", "Vacant", "Occupancy"], rows)])
        return R("floors", "Vacant beds by floor%s:" % for_who, [_table(["Floor", "Rooms", "Beds", "Occupied", "Vacant", "Occupancy"], rows)])
    # which rooms have people in them ("show all occupied rooms", "occupied rooms on the 2nd floor", "pakita ang occupied rooms")
    if re.search(r"\b(occupied|taken|filled|in use|with (tenants|people|someone))\b", t) and re.search(r"\brooms?\b", t) and \
            re.search(r"\b(show|list|which|what|all|give|display|check|where|see|find)\b", t) and \
            not re.search(VAC + r"|\b(how many|rate|percent\w*|trend|forecast|predict|compare|report|summary|why|fully|full)\b", t):
        if W.floor is not None and not D.floors:
            return R("floors_none", "Your dormitory has no floors set up yet, so I can't tell which rooms are on the %s floor. Add floors on the Hallway "
                     "Layout tab, then ask me again." % {0: "ground", 1: "first", 2: "second", 3: "third", 4: "fourth"}.get(W.floor, "that"))
        rows = []
        for r in pick:
            c = D.counts(r)
            if c["occupied"]:
                rows.append([r["room"], c["occupied"], c["total"], c["vacant"], c["reserved"], r.get("gender") or "Mixed", r.get("demographic") or "Mixed"])
        rows.sort(key=lambda x: (-x[1] / max(1, x[2]), str(x[0])))
        if not rows:
            return R("rooms_occupied", "Nobody is staying in any room%s right now." % for_who)
        full = sum(1 for x in rows if not x[3] and not x[4])
        text = "%s someone staying in %s%s right now — %s full. %s" % (
            "There's" if len(rows) == 1 else "You have", _plural(len(rows), "room"), for_who, "none of them is" if not full else
            ("%d of them is" % full if full == 1 else "%d of them are" % full),
            "Busiest first: " + ", ".join("%s (%d of %d)" % (x[0], x[1], x[2]) for x in rows[:8]) + (" …" if len(rows) > 8 else "."))
        return R("rooms_occupied", text, [_table(["Room", "Occupied", "Beds", "Vacant", "Reserved", "Gender", "Group"], rows[:40])])
    # rooms of a kind ("show me the girls' rooms")
    if (W.gender or W.group or W.mode or W.ac is not None) and re.search(r"\brooms\b", t) and re.search(r"\b(show|list|which|what|all|give)\b", t) and not re.search(VAC, t):
        rows = [[r["room"], len(r["beds"]), D.counts(r)["occupied"], D.counts(r)["vacant"], r.get("gender") or "Mixed", r.get("demographic") or "Mixed"] for r in pick]
        return R("rooms_kind", "%s%s: %s." % (_plural(len(rows), "room"), for_who, ", ".join("%s (%d vacant)" % (x[0], x[3]) for x in rows[:12])) if rows else "No rooms%s." % for_who,
                 [_table(["Room", "Beds", "Occupied", "Vacant", "Gender", "Group"], rows)] if rows else [])
    # the main vacancy question
    vac = re.search(VAC, t) or W.people or W.bookable or re.search(r"\b(can (i|we|a \w+)|is it possible to) (reserve|book)\b", t)
    asks = re.search(r"\b(which|what|where|show|list|any|is there|are there|how many|do we have|do you have|can|got|have|give|find|left|remaining|available|open|check)\b", t)
    filters = W.gender or W.group or W.mode or W.floor is not None or W.ac is not None or W.people or W.start or W.no_incoming
    if vac and (asks or filters or len(t.split()) <= 6) and not re.search(r"\b(report|summary|trend|forecast|predict|why|compare|revenue|rent|income|percent|rate)\b", t):
        if not filters and not re.search(r"\b(which|show|list|where|rooms|left|remaining|most|highest|reserve|book|check)\b", t):
            return None                               # a plain count: the live answer (with per-room numbers) handles it
        if W.floor is not None and not D.floors:
            return R("floors_none", "Your dormitory has no floors set up yet, so I can't tell which beds are on the %s floor. "
                     "Add floors on the Hallway Layout tab." % {1: "first", 2: "second", 3: "third"}.get(W.floor, "that"))
        rows = []
        for r in pick:
            v = vac_of(r)
            if W.people and len(v) < W.people:
                continue
            if v:
                rows.append([r["room"], len(v), len(r["beds"]), ", ".join(v), r.get("gender") or "Mixed", r.get("demographic") or "Mixed",
                             r.get("tenancyMode") or "Bedspace"] + ([D.floor_name(r)] if D.floors else []))
        rows.sort(key=lambda x: (-x[1], str(x[0])))
        nbeds = sum(x[1] for x in rows)
        when = (" " + W.when_label) if W.when_label and W.start and (W.start > today or W.end) else " right now"
        need = (" with room for %s" % _plural(W.people, "person", "people")) if W.people else ""
        if not rows:
            text = "No vacant bed%s%s%s." % (for_who, need, when)
            later = sorted([(parse_iso(b.get("end")), r["room"], bed_label(b, i)) for r in pick for i, b in enumerate(r["beds"])
                            if b.get("tenant") and parse_iso(b.get("end")) and parse_iso(b.get("end")) >= today], key=lambda x: x[0])
            if later and not W.people:
                text += " The next one%s frees up after %s (Room %s, %s)." % (for_who, pretty(later[0][0]), later[0][1], later[0][2])
            return R("vacancy", text)
        most = re.search(r"\b(most|highest|largest|biggest)\b", t)
        if most:
            top = rows[0]
            text = "Room %s has the most vacant beds%s%s: %d of %d." % (top[0], for_who, when, top[1], top[2])
        elif re.search(r"\bhow many\b", t) and not re.search(r"\bwhich|what rooms|show|list\b", t):
            text = "%s%s%s%s, in %s." % (_plural(nbeds, "vacant bed"), for_who, need, when, _plural(len(rows), "room"))
        else:
            text = "Yes: %s%s%s%s in %s — %s." % (_plural(nbeds, "vacant bed"), for_who, need, when, _plural(len(rows), "room"),
                                                 "; ".join("Room %s (%s)" % (x[0], x[3]) for x in rows[:8]) + (" …" if len(rows) > 8 else ""))
            if not re.search(r"^(is|are) there|any\b|^can\b", t):
                text = text[5].upper() + text[6:]
        cols = ["Room", "Vacant", "Beds", "Which beds", "Gender", "Group", "Type"] + (["Floor"] if D.floors else [])
        blocks = [_table(cols, rows[:30])]
        if W.start and W.start > today:
            blocks.append(_note("Includes beds whose current tenant checks out before %s. Reserved beds are left out." % pretty(W.start)))
        if W.group or W.gender:
            blocks.append(_note("Mixed rooms count for everyone, so they are included."))
        if re.search(r"\b(reserve|book)\b", t):
            blocks.append(_note("To hold one, say for example: reserve a bed in Room %s for <full name> from <date>. I'll prepare it and you confirm." % rows[0][0]))
        return R("vacancy", text, blocks)
    return None


# ---------------------------------------------------------------------------------- tenants (Branch Admin only)
def _tenant_rows(D):
    for r, i, b in D.rec.occupied():
        yield r, i, b, D.info(b)


def admin_tenants(D, W, t, today, ctx):
    if not re.search(r"\b(tenants?|residents?|boarders?|people|occupants?|profiles?|contacts?|emergency|registered|registration|"
                     r"staying|who|gender breakdown|active|checked out|moved out|left)\b", t):
        return None
    occ = list(_tenant_rows(D))
    # contact information of tenants in a room
    m = re.search(r"\broom\s*(?:no\.?|number|#)?\s*([a-z]?-?\d[\w-]*)", t)
    room = D.rec.room_by_name(m.group(1)) if m else None
    if m and not room:
        cand = [r for r in D.rec.rooms if str(r.get("room")).lower().endswith(m.group(1).lower())]
        room = cand[0] if len(cand) == 1 else None
    if has(t, r"\b(contact|phone|number|mobile|cell)\w*\b") and not has(t, r"\bemergency\b") and room:
        rows = [[bed_label(b, i), b["tenant"], info.get("contact") or "— missing", info.get("address") or "—"] for r, i, b, info in occ if r is room]
        return R("tenant_contacts", "Contact details in Room %s:" % room["room"] if rows else "Room %s has no tenants right now." % room["room"],
                 [_table(["Bed", "Tenant", "Contact number", "Address"], rows)] if rows else [])
    if m and not room and re.search(r"\b(who|tenants?|staying|contact)\b", t):
        return R("room_missing", "I can't find Room %s. Your rooms are named like %s." % (m.group(1).upper(), ", ".join(str(r["room"]) for r in D.rec.rooms[:6])))
    # missing information
    if has(t, r"\b(missing|no|without|incomplete|lacking|empty)\b.*\b(contact|emergency|profile|information|info|details|address|phone|number)",
           r"\b(contact|profile|emergency)\w*\b.*\b(missing|incomplete)\b", r"\bnot (completed|finished) (their )?registration\b", r"\bincomplete (profile|registration)s?\b"):
        want_ec = has(t, r"\bemergency\b")
        want_contact = has(t, r"\b(contact|phone|number)\b") and not want_ec
        rows = []
        for r, i, b, info in occ:
            miss = []
            if not info.get("contact"):
                miss.append("contact number")
            if not (info.get("ec1") or info.get("ec2")):
                miss.append("emergency contact")
            if not info.get("address"):
                miss.append("address")
            if want_ec:
                miss = [x for x in miss if x == "emergency contact"]
            elif want_contact:
                miss = [x for x in miss if x == "contact number"]
            if miss:
                rows.append([b["tenant"], "Room %s, %s" % (r["room"], bed_label(b, i)), ", ".join(miss)])
        what = "an emergency contact" if want_ec else "a contact number" if want_contact else "complete Tenant Information"
        if not rows:
            return R("tenants_missing", "Every current tenant has %s." % what)
        return R("tenants_missing", "%s without %s." % (_plural(len(rows), "tenant"), what),
                 [_table(["Tenant", "Bed", "Missing"], rows[:40]), _note("Fill them in on the Tenant Information tab.")])
    # emergency contact of a named tenant
    if has(t, r"\bemergency\b"):
        hits = smart.people_hits(t, [(b["tenant"], (r, i, b, info)) for r, i, b, info in occ])
        if not hits:
            return R("clarify", "Whose emergency contact? Say the tenant's name, for example: emergency contact of Ana Reyes.")
        out = []
        for name, (r, i, b, info) in hits[:3]:
            ecs = [e for e in (info.get("ec1"), info.get("ec2")) if isinstance(e, dict) and (e.get("name") or e.get("phone"))]
            out.append("%s: %s" % (name, "; ".join("%s (%s) %s" % (e.get("name") or "?", e.get("relation") or "contact", e.get("phone") or "") for e in ecs)
                                   if ecs else "no emergency contact saved"))
        return R("tenant_emergency", " · ".join(out))
    # recently registered / checked in this week (before the plain count)
    if has(t, r"\brecent(ly)? (registered|added|checked in|arrived|joined)\b", r"\bnew tenants\b", r"\b(checked|moved) in (this|last) (week|month)\b",
           r"\bhow many (tenants )?(checked|moved) in\b"):
        days = 30 if has(t, r"\bmonth\b") else 7 if has(t, r"\bweek\b") else 14
        rows = sorted([(parse_iso(b.get("start")), b["tenant"], r["room"], bed_label(b, i)) for r, i, b, info in occ
                       if parse_iso(b.get("start")) and today - timedelta(days=days) <= parse_iso(b.get("start")) <= today], key=lambda x: x[0], reverse=True)
        if not rows:
            return R("tenants_recent", "Nobody checked in during the last %d days." % days)
        return R("tenants_recent", "%s checked in during the last %d days." % (_plural(len(rows), "tenant"), days),
                 [_table(["Check-in", "Tenant", "Room", "Bed"], [[pretty(a), b, c, d] for a, b, c, d in rows])])
    if has(t, r"\bcontract (information|details|info)\b", r"\bcontract of\b", r"\b(his|her)\b.*\bcontract\b"):
        hits = smart.people_hits(t, [(b["tenant"], (r, i, b)) for r, i, b, info in occ])
        if not hits:
            return R("clarify", "Whose contract? Say the name, for example: contract of Ana Reyes.")
        return R("tenant_contract", " ".join("%s: Room %s, %s, from %s until %s." % (n, r["room"], bed_label(b, i), pretty(parse_iso(b.get("start"))) if b.get("start") else "?",
                                                                                   pretty(parse_iso(b.get("end"))) if b.get("end") else "no end date") for n, (r, i, b) in hits[:3]))
    # how many tenants / male-female
    if has(t, r"\bhow many\b.*\b(tenants?|residents?|people|boarders?|occupants?|registered)\b", r"\b(total|number of) (tenants|residents)\b",
           r"\bmale and female\b.*\b(tenants|registered)\b", r"\bgender breakdown\b") and \
            not has(t, r"\b(additional|more|accommodate|predict|will|may|might|renew\w*|check ?out|checked out|leav\w*|in room|room \S*\d)\b"):
        g = Counter(b.get("residentGender") or (r.get("gender") if r.get("gender") in ("Male", "Female") else "Not set") for r, i, b, info in occ)
        grp = Counter(b.get("residentType") or "Not set" for r, i, b, info in occ)
        if not occ:
            return R("tenants_count", "You have no tenants checked in right now.")
        return R("tenants_count", "%s staying now: %s." % (_plural(len(occ), "tenant"), ", ".join("%d %s" % (v, k.lower()) for k, v in g.most_common())),
                 [_list(["%s: %d" % (k, v) for k, v in g.most_common()] + ["%s: %d" % (k, v) for k, v in grp.most_common()])])
    # checked out / former tenants
    if has(t, r"\b(already |have )?(checked out|moved out)\b", r"\b(tenants?|who)\b.*\b(already |have )?left\b", r"\bformer tenants\b", r"\bpast tenants\b") and not has(t, r"\bwill\b|\btomorrow\b|\btoday\b|\bnext\b"):
        h = sorted(D.hist, key=lambda x: str(x.get("end") or ""), reverse=True)
        win = _window_from(t.replace("this month", "past month"), today) if False else None
        if has(t, r"\bthis (week|month|year)\b", r"\blast (week|month)\b"):
            unit = re.search(r"\b(this|last) (week|month|year)\b", t)
            if unit.group(2) == "week":
                a = today - timedelta(days=today.weekday() + (7 if unit.group(1) == "last" else 0))
                b = a + timedelta(days=6)
            elif unit.group(2) == "month":
                y, mo = today.year, today.month - (1 if unit.group(1) == "last" else 0)
                if mo == 0:
                    y, mo = y - 1, 12
                a, b = date(y, mo, 1), date(y, mo, monthrange(y, mo)[1])
            else:
                a, b = date(today.year, 1, 1), today
            h = [x for x in h if parse_iso(x.get("end")) and a <= parse_iso(x.get("end")) <= b]
            if not h:
                return R("tenants_left", "Nobody was checked out %s %s." % unit.groups())
            return R("tenants_left", "%s checked out %s %s." % (_plural(len(h), "tenant"), unit.group(1), unit.group(2)),
                     [_table(["Tenant", "Room", "Left", "Reason"], [[x.get("tenant"), x.get("room"), pretty(parse_iso(x.get("end"))), x.get("reason") or ""] for x in h[:25]])])
        if not h:
            return R("tenants_left", "Tenant History is empty: nobody has been checked out yet.")
        return R("tenants_left", "%s in Tenant History (most recent first)." % _plural(len(h), "former tenant"),
                 [_table(["Tenant", "Room", "Stayed", "Reason"], [[x.get("tenant"), x.get("room"), "%s – %s" % (pretty(parse_iso(x.get("start"))) if x.get("start") else "?", pretty(parse_iso(x.get("end"))) if x.get("end") else "?"), x.get("reason") or ""] for x in h[:25]])])
    # list / grouped by room / same room / active
    if has(t, r"\b(grouped|group|sorted|organi[sz]ed) by room\b", r"\bsame room\b", r"\b(all|list|show)\b.*\b(active |current )?(tenants|residents)\b",
           r"\b(active|current) (tenants|residents)\b", r"\bwho (is|are) (staying|living)\b(?!.*\broom\b)"):
        byroom = {}
        for r, i, b, info in occ:
            byroom.setdefault(r["room"], []).append(b["tenant"])
        rows = [[k, len(v), ", ".join(v)] for k, v in byroom.items()]
        if has(t, r"\bsame room\b"):
            rows = [x for x in rows if x[1] > 1]
            return R("tenants_list", "%s share a room with someone: %s rooms have 2 or more tenants." % (_plural(sum(x[1] for x in rows), "tenant"), len(rows)),
                     [_table(["Room", "Tenants", "Names"], rows)])
        return R("tenants_list", "%s staying now in %s." % (_plural(len(occ), "tenant"), _plural(len(byroom), "room")), [_table(["Room", "Tenants", "Names"], rows)])
    if has(t, r"\bfind (a )?tenant by name\b", r"\bsearch (for )?(a )?tenant\b") and not smart.people_hits(t, [(b["tenant"], b) for r, i, b, info in occ]):
        return R("clarify", "Tell me the name, for example: where is Ana Reyes? I'll show the room, bed and dates.")
    return None


# ---------------------------------------------------------------------------------- contracts
def _window_from(t, today):
    m = re.search(r"\bwithin\s+(?:the\s+)?(?:next\s+)?" + NUMW + r"\s+(day|week|month)s?\b", t) or re.search(r"\b(?:next|in)\s+" + NUMW + r"\s+(day|week|month)s?\b", t)
    if m:
        n = n_of(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)]
        return today, today + timedelta(days=n), "within %d days" % n
    if has(t, r"\btoday\b"):
        return today, today, "today"
    if has(t, r"\btomorrow\b"):
        d = today + timedelta(days=1)
        return d, d, "tomorrow"
    if has(t, r"\bthis weekend\b"):
        s = today + timedelta(days=(5 - today.weekday()) % 7)
        return s, s + timedelta(days=1), "this weekend"
    if has(t, r"\bnext week\b"):
        s = today + timedelta(days=7 - today.weekday())
        return s, s + timedelta(days=6), "next week"
    if has(t, r"\bthis week\b"):
        return today, today + timedelta(days=7), "this week"
    if has(t, r"\bnext month\b"):
        y, mo = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        return date(y, mo, 1), date(y, mo, monthrange(y, mo)[1]), "next month"
    if has(t, r"\bthis month\b"):
        return today, date(today.year, today.month, monthrange(today.year, today.month)[1]), "this month"
    m = re.search(r"\bbefore (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b", t)
    if m:
        mo = smart.MONTHS[m.group(1)]
        y = today.year + (1 if mo <= today.month else 0)
        return today, date(y, mo, 1) - timedelta(days=1), "before %s" % date(y, mo, 1).strftime("%B")
    if has(t, r"\b(soon|upcoming|coming|near|nearly|expiring soon)\b"):
        return today, today + timedelta(days=7), "in the next 7 days"
    return None


def admin_contracts(D, W, t, today, ctx):
    occ = list(_tenant_rows(D))
    leaving = re.search(r"\b(check ?outs?|checking out|leav\w*|move out|moving out|expir\w*|contracts? (end|ending|ends)|ending|"
                        r"become (vacant|available|free)|free up|opening up|open up|vacate)\b", t)
    if has(t, r"\b(exceeded|passed|past|overstay\w*|beyond)\b.*\b(contract|check ?out|date)s?\b", r"\boverdue\b", r"\bfail(ed|s)? to check out\b(?!.*what)",
           r"\bstill (here|staying) after\b", r"\bexpired contracts?\b", r"\blate check ?outs?\b") and not has(t, r"\bwhat happens\b"):
        rows = sorted([(parse_iso(b.get("end")), b["tenant"], r["room"], bed_label(b, i)) for r, i, b, info in occ
                       if parse_iso(b.get("end")) and parse_iso(b.get("end")) < today], key=lambda x: x[0])
        if not rows:
            return R("contracts_overdue", "Nobody is past their check-out date.")
        return R("contracts_overdue", "%s past the check-out date (overdue, still counted as occupied)." % _plural(len(rows), "tenant is", "tenants are"),
                 [_table(["Tenant", "Room", "Bed", "Check-out was", "Days over"], [[b, c, d, pretty(a), (today - a).days] for a, b, c, d in rows]),
                  _note("Check them out or extend their stay on Room Canvas.")])
    if has(t, r"\blongest (remaining )?(contract|stay)\b", r"\bcontract.*\blongest\b"):
        rows = sorted([(parse_iso(b.get("end")), b["tenant"], r["room"]) for r, i, b, info in occ if parse_iso(b.get("end"))], key=lambda x: x[0], reverse=True)
        if not rows:
            return R("contracts_longest", "No current contract has a check-out date.")
        a, n, rm = rows[0]
        return R("contracts_longest", "%s has the longest remaining contract: until %s (%d days left), Room %s." % (n, pretty(a), (a - today).days, rm),
                 [_table(["Tenant", "Room", "Until", "Days left"], [[x[1], x[2], pretty(x[0]), (x[0] - today).days] for x in rows[:10]])])
    if has(t, r"\baverage (contract|stay|length)\b", r"\bcontract duration\b", r"\bhow long (do )?(tenants|people) stay\b"):
        ds = [(parse_iso(b.get("end")) - parse_iso(b.get("start"))).days for r, i, b, info in occ if parse_iso(b.get("start")) and parse_iso(b.get("end"))]
        ds += [(parse_iso(h.get("end")) - parse_iso(h.get("start"))).days for h in D.hist if parse_iso(h.get("start")) and parse_iso(h.get("end"))]
        ds = [d for d in ds if d >= 0]
        if not ds:
            return R("contracts_average", "There are not enough start and end dates to work out an average stay.")
        avg = sum(ds) / len(ds)
        return R("contracts_average", "The average stay is %d days (about %.1f months), from %s with both dates." % (round(avg), avg / 30.4, _plural(len(ds), "contract")))
    if has(t, r"\brenew\w*\b"):
        if has(t, r"\bhow many\b.*\brenewed\b", r"\bhave renewed\b", r"\balready renewed\b"):
            return R("contracts_renewed", "Renewals aren't recorded separately: when you extend a stay, the check-out date simply moves. "
                     "I can list who needs renewal soon — ask: which tenants need contract renewal?")
        rows = sorted([(parse_iso(b.get("end")), b["tenant"], r["room"]) for r, i, b, info in occ if parse_iso(b.get("end")) and parse_iso(b.get("end")) <= today + timedelta(days=30)], key=lambda x: x[0])
        if not rows:
            return R("contracts_renew", "No contract ends within the next 30 days.")
        return R("contracts_renew", "%s within 30 days (or already overdue) — candidates for renewal." % _plural(len(rows), "contract ends", "contracts end"),
                 [_table(["Tenant", "Room", "Ends", "Days"], [[x[1], x[2], pretty(x[0]), (x[0] - today).days] for x in rows]),
                  _note("To renew, say: extend <name> until <date>. I'll prepare it and you confirm.")])
    if has(t, r"\bhow many\b.*\b(active )?contracts?\b", r"\bactive contracts\b") and not leaving:
        with_end = [b for r, i, b, info in occ if b.get("end")]
        return R("contracts_count", "%s active: %d with a check-out date and %d open-ended." % (_plural(len(occ), "contract is", "contracts are"), len(with_end), len(occ) - len(with_end)))
    if re.search(r"\b(checked out|moved out|already left|have left)\b", t):
        return None
    if leaving or has(t, r"\b(who|which tenants?)\b.*\b(going|moving|leaving)\b"):
        if has(t, r"\b(predict|after all|if all|remain|will (we|there) have|left after)\b") and has(t, r"\bvacan\w*\b"):
            return None                               # forecast below
        win = _window_from(t, today) or (today, today + timedelta(days=30), "in the next 30 days")
        a, b, label = win
        rows = smart.departures(D.rec, today, a, b)
        rooms_only = has(t, r"\b(which )?rooms?\b.*\b(vacant|available|free)\b", r"\bbeds?\b.*\b(available|vacant|free)\b")
        if not rows:
            return R("departures", "No check-out is scheduled %s." % label)
        if rooms_only:
            byroom = Counter(re.search(r"\(Room ([^,]+),", x).group(1) for x in rows)
            return R("departures", "%s free up %s: %s." % (_plural(len(rows), "bed will", "beds will"), label, ", ".join("Room %s (%d)" % kv for kv in byroom.items())),
                     [_list(rows[:30])])
        return R("departures", "%s %s: %s." % (_plural(len(rows), "check-out", "check-outs"), label, "; ".join(rows[:12]) + (" …" if len(rows) > 12 else "")),
                 [_list(rows[:40])])
    return None


# ---------------------------------------------------------------------------------- reservations
def admin_reservations(D, W, t, today, ctx):
    if not re.search(r"\b(reserv\w*|bookings?|booked|check ?ins?|checkin|arriv\w*|incoming|waiting list)\b", t):
        return None
    ps = D.rec.prospects
    waiting = [p for p in ps if not p.get("checkedIn") and not p.get("checkedOut")]
    def ci(p):
        return parse_iso(p.get("checkIn"))
    if has(t, r"\b(overlap\w*|conflict\w*|double[- ]booked|same bed)\b") and not has(t, r"\bwhat (happens|should)\b"):
        seen, rows = {}, []
        for p in waiting:
            rb = p.get("reservedBed") or {}
            k = (rb.get("roomId"), rb.get("slot"))
            if k[0]:
                if k in seen:
                    rows.append([p.get("name"), seen[k].get("name"), "same bed"])
                seen[k] = p
        for r in D.rec.rooms:
            for i, b in enumerate(r["beds"]):
                if b.get("tenant") and b.get("reservedFor"):
                    p = next((x for x in ps if x.get("id") == b["reservedFor"]), None)
                    e = parse_iso(b.get("end"))
                    if p and (not e or (ci(p) and e >= ci(p))):
                        rows.append([p.get("name"), b["tenant"], "Room %s %s: tenant stays until %s, check-in %s" % (r["room"], bed_label(b, i), pretty(e) if e else "no end date", pretty(ci(p)))])
        if not rows:
            return R("reservations_overlap", "No overlapping reservations: every held bed is free on its check-in date.")
        return R("reservations_overlap", "%s to review." % _plural(len(rows), "overlap"), [_table(["Reservation", "Conflicts with", "Where / why"], rows)])
    if has(t, r"\b(without|no|not) (an )?(assigned|held|reserved) beds?\b", r"\bno beds? (assigned|yet)\b"):
        rows = [[p.get("name"), pretty(ci(p))] for p in waiting if not (p.get("reservedBed") or {}).get("roomId")]
        return R("reservations_nobed", ("%s without a held bed: %s." % (_plural(len(rows), "reservation"), ", ".join(x[0] for x in rows))) if rows else "Every reservation has a bed held.")
    if has(t, r"\bexpired\b", r"\bno[- ]show\b", r"\bdid not (arrive|come)\b"):
        rows = [[p.get("name"), pretty(ci(p))] for p in waiting if ci(p) and ci(p) < today]
        return R("reservations_expired", ("%s past the check-in date without checking in: %s." % (_plural(len(rows), "reservation is", "reservations are"), "; ".join("%s (was %s)" % tuple(x) for x in rows)))
                 if rows else "No reservation is past its check-in date.")
    if has(t, r"\b(cause|make|become)\b.*\bfull\w*\b", r"\bfully occupied\b.*\breserv"):
        out = []
        for r in D.rec.rooms:
            c = D.counts(r)
            if c["reserved"] and c["vacant"] == 0:
                out.append("Room %s (%d reserved)" % (r["room"], c["reserved"]))
        return R("reservations_full", ("When the reservations arrive these rooms will be full: %s." % ", ".join(out)) if out else "No room becomes full from its reservations alone.")
    if has(t, r"\bwhat happens\b|\bwhat should happen\b|\b(already occupied|occupied bed)\b|\bpossible\b|\bearlier than\b") or \
            re.search(r"\b(can (i|we|a \w+)|is it possible to) (reserve|book)\b", t):
        return None                                   # policy questions: the help topics answer them
    win = _window_from(t, today)
    if re.search(r"\b(check ?in|checkin|arriv\w*|incoming)\b", t) or win or has(t, r"\bhow many\b", r"\bpending\b", r"\bscheduled\b"):
        a, b, label = win or (today - timedelta(days=3650), today + timedelta(days=3650), "")
        rows = sorted([p for p in waiting if not win or (ci(p) and a <= ci(p) <= b)], key=lambda p: str(p.get("checkIn") or ""))
        temps = [c for c in D.rec.temps if c.get("status") != "Checked out" and win and parse_iso(c.get("start")) and a <= parse_iso(c.get("start")) <= b]
        lead = "Pending reservations" if has(t, r"\bpending\b") else "Check-ins" if re.search(r"check ?in|arriv|incoming", t) else "Reservations"
        if not rows and not temps:
            return R("reservations", "%s%s: none." % (lead, (" " + label) if label else ""))
        table = [[p.get("name"), pretty(ci(p)) if ci(p) else "no date", "%s %s" % (p.get("gender") or "", (p.get("demographic") or "").lower()),
                  ("Room %s %s" % (next((r["room"] for r in D.rec.rooms if r["id"] == (p.get("reservedBed") or {}).get("roomId")), "?"), (p.get("reservedBed") or {}).get("slot") or "")) if (p.get("reservedBed") or {}).get("roomId") else "no bed held"] for p in rows]
        table += [[c.get("name"), pretty(parse_iso(c.get("start"))), "temporary guest", "Room %s %s" % (c.get("room"), c.get("slot") or "")] for c in temps]
        return R("reservations", "%s%s: %d." % (lead, (" " + label) if label else "", len(table)), [_table(["Name", "Check-in", "For", "Bed"], table[:40])])
    return None


# ---------------------------------------------------------------------------------- records check
def admin_checks(D, W, t, today, ctx):
    if not re.search(r"\b(duplicate\w*|without assigned|no room|missing dates?|invalid|inconsisten\w*|exceed\w* (their )?capacity|more beds than|"
                     r"marked vacant|verification|verify|incorrect gender|wrong gender|gender mismatch|multiple (active )?reservations|"
                     r"bed count|records? (check|problems|errors|issues)|data (check|problems|errors|issues)|errors?|not been updated|updated recently|"
                     r"overlapping active contracts|no corresponding tenant|integrity|mismatch)\b", t):
        return None
    issues = {}
    names = Counter(b["tenant"].strip().lower() for _r, _i, b in D.rec.occupied())
    issues["Duplicate tenant names"] = ["%s appears %d times" % (n.title(), c) for n, c in names.items() if c > 1]
    used_ids = {b.get("tenantId") for _r, _i, b in D.rec.occupied()}
    issues["Tenant Information without a bed"] = [d.get("name") or i for i, d in D.tenants.items() if i not in used_ids]
    issues["Dates in the wrong order (check-out before check-in)"] = ["%s, Room %s" % (b["tenant"], r["room"]) for r, i, b in D.rec.occupied()
                                                                       if parse_iso(b.get("start")) and parse_iso(b.get("end")) and parse_iso(b.get("end")) < parse_iso(b.get("start"))]
    issues["Tenants without a check-out date"] = ["%s, Room %s" % (b["tenant"], r["room"]) for r, i, b in D.rec.occupied() if not b.get("end")]
    issues["Reservations with a missing date"] = [p.get("name") for p in D.rec.prospects if not p.get("checkedIn") and not p.get("checkIn")]
    issues["Rooms with more beds than their capacity"] = ["Room %s: %d beds, capacity %s" % (r["room"], len(r["beds"]), r.get("capacity")) for r in D.rec.rooms
                                                          if isinstance(r.get("capacity"), int) and len(r["beds"]) > r["capacity"]]
    issues["Beds both occupied and reserved"] = ["Room %s, %s" % (r["room"], bed_label(b, i)) for r in D.rec.rooms for i, b in enumerate(r["beds"]) if b.get("tenant") and b.get("reservedFor")]
    issues["Tenant gender different from the room"] = ["%s (%s) in Room %s (%s)" % (b["tenant"], b.get("residentGender"), r["room"], r.get("gender"))
                                                       for r, i, b in D.rec.occupied() if r.get("gender") in ("Male", "Female") and b.get("residentGender") and b["residentGender"] != r["gender"]]
    pn = Counter((p.get("name") or "").strip().lower() for p in D.rec.prospects if not p.get("checkedIn") and not p.get("checkedOut"))
    issues["People with more than one reservation"] = [n.title() for n, c in pn.items() if n and c > 1]
    held = {(p.get("reservedBed") or {}).get("roomId") and p.get("id") for p in D.rec.prospects}
    issues["Held beds whose reservation is missing"] = ["Room %s, %s" % (r["room"], bed_label(b, i)) for r in D.rec.rooms for i, b in enumerate(r["beds"])
                                                        if b.get("reservedFor") and b["reservedFor"] not in {p.get("id") for p in D.rec.prospects}]
    focus = None
    for key, pat in [("Duplicate tenant names", r"duplicate"), ("Tenant Information without a bed", r"without assigned|no room|without (a )?room"),
                     ("Reservations with a missing date", r"missing dates?"), ("Dates in the wrong order (check-out before check-in)", r"invalid"),
                     ("Rooms with more beds than their capacity", r"exceed|more beds than|bed count"), ("Beds both occupied and reserved", r"marked vacant"),
                     ("Tenant gender different from the room", r"gender"), ("People with more than one reservation", r"multiple"),
                     ("Held beds whose reservation is missing", r"no corresponding")]:
        if re.search(pat, t):
            focus = key
            break
    if re.search(r"not been updated|updated recently", t):
        return R("records_age", "The app doesn't keep a last-changed date for each record, so I can't say which were not updated recently. "
                 "I can check the records for mistakes instead — ask: show records that need verification.")
    if re.search(r"overlapping active contracts", t):
        dup = issues["Duplicate tenant names"]
        return R("records_check", ("Possible overlapping contracts (same name in two beds): " + "; ".join(dup) + ".") if dup else
                 "No tenant has two active contracts: every name appears in only one bed.")
    if focus:
        items = issues[focus]
        return R("records_check", ("%s: %s." % (focus, "; ".join(map(str, items[:20])))) if items else "No problem found: %s — none." % focus.lower())
    found = {k: v for k, v in issues.items() if v}
    if not found:
        return R("records_check", "I checked the rooms, tenants and reservations: no mistakes found.")
    return R("records_check", "I found %s to check." % _plural(sum(len(v) for v in found.values()), "item"),
             [b for k, v in found.items() for b in ({"type": "subheading", "text": "%s (%d)" % (k, len(v))}, _list([str(x) for x in v[:12]]))])


# ---------------------------------------------------------------------------------- operations
NOT_TRACKED_OPS = r"\b(maintenance|repairs?|cleaning|clean|inspect\w*|housekeeping|broken|under repair|temporarily unavailable|out of order|rooms? (with |has |have |is there )?(a )?problems?|problems? (in|with) (the )?rooms?)\b"


def admin_operations(D, W, t, today, ctx):
    if re.search(NOT_TRACKED_OPS, t):
        return R("not_tracked_ops", "Maintenance, cleaning and inspections aren't recorded in the Vacancy Tracker, so I can't list them or mark a room "
                 "as under maintenance. What I can do: show beds that need preparing for incoming tenants, today's check-ins and check-outs, "
                 "and records that need checking.", suggestions=["Which beds need to be prepared?", "Who checks out today?", "What needs attention?"])
    if has(t, r"\b(prepare|prepared|get ready|ready for)\b.*\b(beds?|rooms?|incoming|arriv\w*)", r"\bincoming tenants\b"):
        rows = []
        for p in D.rec.prospects:
            rb, c = p.get("reservedBed") or {}, parse_iso(p.get("checkIn"))
            if not p.get("checkedIn") and c and c <= today + timedelta(days=7):
                rows.append([next((r["room"] for r in D.rec.rooms if r["id"] == rb.get("roomId")), "no bed held"), rb.get("slot") or "", p.get("name"), pretty(c)])
        for r, i, b in D.rec.occupied():
            e = parse_iso(b.get("end"))
            if e and today <= e <= today + timedelta(days=2) and b.get("reservedFor"):
                rows.append([r["room"], bed_label(b, i), "next tenant after %s" % b["tenant"], pretty(e + timedelta(days=1))])
        if not rows:
            return R("prepare_beds", "No one arrives in the next 7 days, so no bed needs preparing.")
        return R("prepare_beds", "%s to prepare for arrivals in the next 7 days." % _plural(len(rows), "bed"), [_table(["Room", "Bed", "For", "Arrives"], rows)])
    if has(t, r"\bready for occupancy\b", r"\bready to (use|occupy)\b"):
        n = len(D.rec.vacant_beds())
        return R("ready_beds", "%s ready now (vacant and not reserved)." % _plural(n, "bed is", "beds are"))
    if has(t, r"\b(transfers?|room changes?|moved rooms?|changed rooms?)\b") and has(t, r"\b(pending|recent\w*|show|list|history|all|who)\b") and \
            not has(t, r"\b(accommodate|which rooms can|wants? to)\b"):
        rows = sorted(D.transfers, key=lambda x: str(x.get("at") or x.get("createdAt") or ""), reverse=True)
        if has(t, r"\bpending\b"):
            return R("transfers", "Transfers happen at once when you confirm them, so nothing is pending. "
                     + ("Recent transfers: " + "; ".join("%s" % (x.get("tenant")) for x in rows[:5]) + "." if rows else "There are no recent transfers."))
        if not rows:
            return R("transfers", "No room changes recorded yet.")
        def where(v):
            return "Room %s %s" % (v.get("room"), v.get("slot") or "") if isinstance(v, dict) else "?"
        return R("transfers", "%s recorded." % _plural(len(rows), "room change"), [_table(["Tenant", "From", "To"], [[x.get("tenant"), where(x.get("from")), where(x.get("to"))] for x in rows[:20]])])
    if has(t, r"\b(needs? attention|pending (administrative )?tasks?|to ?do|follow up|what should (i|we) do|what needs doing|most important action)\b",
           r"\bwhat needs\b"):
        items = []
        od = [b["tenant"] for r, i, b in D.rec.occupied() if parse_iso(b.get("end")) and parse_iso(b.get("end")) < today]
        if od:
            items.append("%s past check-out: %s — check out or extend." % (_plural(len(od), "tenant is", "tenants are"), ", ".join(od[:6])))
        lv = smart.departures(D.rec, today, today, today + timedelta(days=2))
        if lv:
            items.append("%s in the next 2 days: %s." % (_plural(len(lv), "check-out"), "; ".join(lv[:5])))
        ar = [p.get("name") for p in D.rec.prospects if not p.get("checkedIn") and parse_iso(p.get("checkIn")) and today <= parse_iso(p.get("checkIn")) <= today + timedelta(days=3)]
        if ar:
            items.append("%s arriving within 3 days: %s — prepare their beds." % (_plural(len(ar), "reservation"), ", ".join(ar)))
        miss = [b["tenant"] for r, i, b in D.rec.occupied() if not D.info(b).get("contact") or not (D.info(b).get("ec1") or D.info(b).get("ec2"))]
        if miss:
            items.append("%s missing a contact number or emergency contact." % _plural(len(miss), "tenant"))
        exp = [p.get("name") for p in D.rec.prospects if not p.get("checkedIn") and parse_iso(p.get("checkIn")) and parse_iso(p.get("checkIn")) < today]
        if exp:
            items.append("%s past the check-in date: %s — check them in or cancel." % (_plural(len(exp), "reservation"), ", ".join(exp)))
        if not items:
            return R("attention", "Nothing urgent: no overdue tenants, no check-outs or arrivals in the next days, and the tenant details are complete.")
        return R("attention", "%s need%s attention:" % (_plural(len(items), "thing"), "s" if len(items) == 1 else ""), [_list(items)])
    return None


# ---------------------------------------------------------------------------------- simple what-if arithmetic
def admin_scenarios(D, W, t, today, ctx):
    m = re.search(r"\b" + NUMW + r" beds?\b.*?\b" + NUMW + r" (?:are )?occupied\b(?:.*?\b" + NUMW + r" (?:is |are )?reserved\b)?", t)
    if m and re.search(r"\b(how many|available|actually|left)\b", t):
        tot, occ, res = n_of(m.group(1)), n_of(m.group(2)), n_of(m.group(3)) if m.group(3) else 0
        free = max(0, tot - occ - res)
        return R("scenario", "%d of %d beds are actually available: %d occupied%s. Reserved beds are held, so they are not available." %
                 (free, tot, occ, (" and %d reserved" % res) if res else ""))
    m = re.search(r"\b" + NUMW + r" beds?\b.*\bonly " + NUMW + r" (?:are )?(?:usable|working|available for use)\b", t)
    if m:
        tot, usable = n_of(m.group(1)), n_of(m.group(2))
        return R("scenario", "Count the occupancy rate against the usable beds: occupied ÷ %d (not ÷ %d). For example 2 occupied = %s. "
                 "In the app, remove or don't add the unusable beds so the statistics use the right capacity." % (usable, tot, agent._p(agent._pct(2, usable))))
    m = re.search(r"\b" + NUMW + r" tenants? (?:check ?out|leave)\b.*\b" + NUMW + r" (?:tenants? )?(?:check ?in|arrive)\b", t)
    if m:
        out_n, in_n = n_of(m.group(1)), n_of(m.group(2))
        total = sum(len(r["beds"]) for r in D.rec.rooms)
        occ = sum(1 for _ in D.rec.occupied())
        new = occ - out_n + in_n
        return R("scenario", "Occupied beds go from %d to %d of %d: occupancy %s → %s." % (occ, new, total, agent._p(agent._pct(occ, total)), agent._p(agent._pct(new, total))))
    m = re.search(r"\broom\s*([a-z]?-?\d[\w-]*)\s+capacity from\s+" + NUMW + r"\s+to\s+" + NUMW, t) or re.search(r"\bincrease\b.*\broom\s*([a-z]?-?\d[\w-]*)\b.*?\bfrom\s+" + NUMW + r"\s+to\s+" + NUMW, t)
    if m:
        add = n_of(m.group(3)) - n_of(m.group(2))
        total = sum(len(r["beds"]) for r in D.rec.rooms)
        occ = sum(1 for _ in D.rec.occupied())
        return R("scenario", "With %s more bed%s, total beds go from %d to %d. If nobody new moves in, occupancy drops from %s to %s; "
                 "filling the new beds would raise it to %s." % (add, "" if add == 1 else "s", total, total + add, agent._p(agent._pct(occ, total)),
                                                                agent._p(agent._pct(occ, total + add)), agent._p(agent._pct(occ + add, total + add))))
    if has(t, r"\bif all (upcoming )?reservations\b", r"\breservations (are )?confirmed\b.*\bvacant\b"):
        vac = len(D.rec.vacant_beds())
        res = sum(1 for p in D.rec.prospects if not p.get("checkedIn") and not p.get("checkedOut"))
        return R("scenario", "Reserved beds are already not counted as vacant, so when all %s arrive, vacant beds stay at %d (unless someone "
                 "reserved without a held bed)." % (_plural(res, "reservation"), vac))
    if has(t, r"\b(all )?(currently )?occupied beds\b.*\bmaintenance\b"):
        return R("scenario", "You could still offer the %s that are vacant now." % _plural(len(D.rec.vacant_beds()), "bed"))
    return None


# ---------------------------------------------------------------------------------- forecasts and history
def admin_forecast(D, W, t, today, ctx):
    if not re.search(r"\b(predict\w*|forecast\w*|likely|expect\w*|projection|projected|will (we|there|it)|by the end of|end of (the )?year|"
                     r"trend|increasing|decreasing|going up|going down|historical|history|demand|seasonal|pattern|most likely|"
                     r"usually|highest number|fully occupied\b.*\bwhen|when (was|did)|additional tenants|run out|enough (vacancies|beds)|"
                     r"accommodate next|consistently|every month|monthly|this year|per month|after all|if all)\b", t):
        return None
    total = sum(len(r["beds"]) for r in D.rec.rooms)
    hist = D.hist
    if has(t, r"\b(which months?|when)\b.*\b(demand|busy|busiest|most (reservations|check ?ins)|high occupancy|more reservations)\b", r"\bseasonal\b", r"\bpattern\b",
           r"\busually\b"):
        months = Counter()
        for r, i, b in D.rec.occupied():
            s = parse_iso(b.get("start"))
            if s:
                months[s.strftime("%B")] += 1
        for h in hist:
            s = parse_iso(h.get("start"))
            if s:
                months[s.strftime("%B")] += 1
        if sum(months.values()) < 6:
            return R("demand", "There isn't enough history yet to see a seasonal pattern. It gets clearer after a few months of check-ins.")
        top = months.most_common(3)
        return R("demand", "Most check-ins started in %s, based on %s." % (", ".join("%s (%d)" % kv for kv in top), _plural(sum(months.values()), "stay")),
                 [_table(["Month", "Check-ins"], [[k, v] for k, v in sorted(months.items(), key=lambda kv: datetime.strptime(kv[0], "%B").month)]),
                  _note("Counted from current tenants' check-in dates and Tenant History. Promote before these months.")])
    if has(t, r"\b(monthly|month by month|per month|each month)\b", r"\btrend\b", r"\bincreasing or decreasing\b", r"\bgoing (up|down)\b",
           r"\bhighest number of vacanc\w*\b", r"\bwhen (was|were) (we|the dorm\w*) (fully occupied|full)\b", r"\bfully occupied\b.*\bwhen\b",
           r"\bconsistently\b", r"\bthis year\b", r"\bbecame vacant\b"):
        rows = []
        for k in range(5, -1, -1):
            y, mo = today.year, today.month - k
            while mo <= 0:
                mo += 12
                y -= 1
            end = date(y, mo, monthrange(y, mo)[1]) if k else today
            occ = agent.occupancy_on(D.rec, hist, end)
            rows.append([end.strftime("%b %Y"), occ, max(0, total - occ), agent._p(agent._pct(occ, total))])
        if has(t, r"\bconsistently\b"):
            vr = [[r["room"], D.counts(r)["vacant"], len(r["beds"])] for r in D.rec.rooms if D.counts(r)["vacant"] * 2 >= len(r["beds"]) and r["beds"]]
            return R("rooms_high_vacancy", ("Rooms with half or more of their beds vacant now: %s. Room-by-room history isn't stored, so this uses today's numbers." %
                                            ", ".join(str(x[0]) for x in vr)) if vr else "No room has half or more of its beds vacant right now.",
                     [_table(["Room", "Vacant", "Beds"], vr)] if vr else [])
        hi = max(rows, key=lambda x: x[2])
        full = [x[0] for x in rows if x[2] == 0]
        direction = "decreasing" if rows[-1][2] < rows[-2][2] else "increasing" if rows[-1][2] > rows[-2][2] else "steady"
        text = "Vacant beds over the last 6 months: highest in %s (%d). Vacancies are %s compared with last month." % (hi[0], hi[2], direction)
        if re.search(r"fully occupied|full\b", t):
            text = ("The dormitory was fully occupied at the end of: %s." % ", ".join(full)) if full else "The dormitory wasn't fully occupied at any month-end in the last 6 months."
        if re.search(r"became vacant|this year", t):
            left = [h for h in hist if parse_iso(h.get("end")) and parse_iso(h.get("end")).year == today.year]
            text = "%s became vacant this year when tenants left (from Tenant History)." % _plural(len(left), "bed")
        return R("trend_monthly", text, [_table(["Month end", "Occupied", "Vacant", "Occupancy"], rows),
                                          _note("Rebuilt from check-in dates and Tenant History. Today's bed count is used for every month.")])
    # forward-looking: scheduled dates
    def occ_at(d):
        n = 0
        for r, i, b in D.rec.occupied():
            e = parse_iso(b.get("end"))
            if e is None or e >= d or e < today:
                n += 1
        for p in D.rec.prospects:
            c = parse_iso(p.get("checkIn"))
            if not p.get("checkedIn") and c and today < c <= d:
                n += 1
        return n
    horizon = 7 if has(t, r"\bnext week|week\b") else 90 if has(t, r"\bthree months|3 months|quarter\b") else \
        (date(today.year, 12, 31) - today).days if has(t, r"\bend of (the )?year\b") else 150 if has(t, r"\bsemester\b") else 30
    rows = []
    for d in sorted({0, 7, 14, 30, 60, 90, horizon}):
        if d <= max(horizon, 30):
            o = occ_at(today + timedelta(days=d))
            rows.append(["Today" if d == 0 else pretty(today + timedelta(days=d)), o, total - o, agent._p(agent._pct(o, total))])
    o = occ_at(today + timedelta(days=horizon))
    base_vac = total - occ_at(today)
    if has(t, r"\b(likely|how many)\b.*\bvacant\b", r"\bbecome vacant\b", r"\bafter all\b", r"\bif all\b", r"\bvacan\w* (situation|by)\b"):
        text = "If everyone leaves on their scheduled date and every reservation arrives, %s will be vacant by %s (today: %d)." % (
            _plural(total - o, "bed"), pretty(today + timedelta(days=horizon)), base_vac)
    elif has(t, r"\b(additional tenants|accommodate|room for more|how many more)\b"):
        text = "You could take about %s more by %s (beds free on that date after scheduled check-outs and reservations)." % (
            _plural(total - o, "tenant"), pretty(today + timedelta(days=horizon)))
    elif has(t, r"\brun out\b|\benough\b"):
        text = ("Yes, there should be room: about %s free by %s." % (_plural(total - o, "bed"), pretty(today + timedelta(days=horizon)))) if total - o > 2 else \
            "You may run short: only %s free by %s from the schedule." % (_plural(total - o, "bed"), pretty(today + timedelta(days=horizon)))
    else:
        text = "Expected occupancy on %s: %s (%d of %d beds), from the scheduled check-outs and reservations." % (
            pretty(today + timedelta(days=horizon)), agent._p(agent._pct(o, total)), o, total)
    return R("forecast", text, [_table(["Date", "Occupied", "Free", "Occupancy"], rows),
                                _note("Based only on dates already in the records. Renewals, early check-outs and new bookings will change it.")])


# ============================================================================== Super Admin
def superadmin(conn, uid, t, today):
    cur = conn.cursor()
    if not agent.is_super(cur, uid):
        return None
    data = agent.super_branches(cur, uid)
    if (has(t, r"\bhow many\b.*\b(dormitor\w*|dorms?|branch\w*)\b", r"\b(number|count|total) of (dorms|branches|dormitories)\b") and
            not has(t, r"\b(vacan\w*|occup\w*|tenants?|beds?|rooms?|check ?outs?)\b")):
        allb = [d for _i, d, _v in list_docs(cur, KINDS["branches"], [], limit=500) if d.get("requestedBy") == uid]
        ok = [d for d in allb if d.get("analyticsStatus") == "approved" or d.get("dirStatus") == "approved"]
        return R("branches_count", "%s connected to you: %d approved sharing, %d waiting or declined." % (_plural(len(allb), "dormitory is", "dormitories are"), len(ok), len(allb) - len(ok)),
                 [_table(["Dormitory", "Location", "Directory", "Analytics"], [[d.get("dormName"), d.get("location") or "", d.get("dirStatus") or "—", d.get("analyticsStatus") or "—"] for d in allb])])
    if has(t, r"\b(pending|waiting)\b.*\b(request|permission|approv)\w*", r"\b(request\w*|permission)\b.*\b(pending|access|approve)\b", r"\bwho requested\b", r"\bneed (to|i) approve\b"):
        rows = []
        for bid, doc, _s in data or []:
            for _cid, ch, _v in list_docs(cur, KINDS["branch_changes"], [bid], limit=200):
                if ch.get("status") == "pending":
                    rows.append([doc.get("dormName") or bid, ch.get("kind") or "change", ch.get("reason") or ""])
        mine = [d for _i, d, _v in list_docs(cur, KINDS["branches"], [], limit=500) if d.get("requestedBy") == uid and "pending" in (d.get("dirStatus"), d.get("analyticsStatus"))]
        text = ("%s waiting for your decision in the Inbox." % _plural(len(rows), "request")) if rows else "No branch request is waiting for you in the Inbox."
        if mine:
            text += " %s still to approve your own sharing request." % _plural(len(mine), "dormitory has", "dormitories have")
        return R("super_requests", text, [_table(["Dormitory", "Request", "Reason"], rows)] if rows else [], nav={"tab": "inbox"})
    if has(t, r"\b(not (yet )?updated|outdated|old data|stale|have(n't| not) updated|latest data|updated (their|the) data|up to date|updated)\b"):
        rows = []
        now = agent._now()
        for bid, doc, snaps in data:
            last = snaps[-1]["_t"] if snaps else None
            age = (now - last).days if last else None
            rows.append([doc.get("dormName") or bid, last.strftime("%b %d, %H:%M") if last else "never", "%d days" % age if age is not None else "—"])
        stale = [r for r in rows if r[1] == "never" or (r[2] != "—" and int(r[2].split()[0]) >= 2)]
        return R("super_freshness", ("%s not sent new data for 2 days or more: %s." % (_plural(len(stale), "dormitory has", "dormitories have"), ", ".join(x[0] for x in stale)))
                 if stale else "Every dormitory sent data within the last 2 days.", [_table(["Dormitory", "Latest data", "Age"], rows)])
    if has(t, r"\b(suspicious|security|unusual|who changed|changed the branch|recent (changes|activity)|activity log|audit)\b", r"\bchanged\b.*\b(branch|information|settings|details)\b"):
        logs = sorted([d for _i, d, _v in list_docs(cur, KINDS["audit"], [], limit=200) if d.get("actorUid") == uid or d.get("targetAdmin") == uid],
                      key=lambda d: agent._ts(d.get("at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        if not logs:
            return R("super_audit", "There is no recorded activity on your account. Sign-ins and changes made by others are listed on the Security tab when they happen.", nav={"tab": "security"})
        rows = [[(agent._ts(d.get("at")) or datetime.now(timezone.utc)).strftime("%b %d %H:%M"), d.get("actorEmail") or "", d.get("action") or "", d.get("branch") or ""] for d in logs[:15]]
        return R("super_audit", "Recent recorded activity (%d). Look for actions you don't recognise." % len(logs), [_table(["When", "Who", "What", "Branch"], rows)], nav={"tab": "security"})
    if has(t, r"\bsubmit\w*\b", r"\bmonthly reports?\b.*\b(admin|branch)\w*"):
        return R("super_reports", "Branch Admins don't submit monthly reports in the Vacancy Tracker: each dormitory's numbers are sent automatically while "
                 "its Branch Admin uses the app. Ask “which branches have not updated?” to see whose data is old.")
    if has(t, r"\b(admins?|branch admins?)\b.*\b(who|list|names?)\b", r"\bwho\b.*\badmins?\b", r"\bpermission\b.*\bmanage\b", r"\bmanage\b.*\bbranch\b"):
        rows = [[d.get("dormName") or bid, d.get("location") or ""] for bid, d, _s in data]
        return R("super_admins", "Each connected dormitory is managed by its own Branch Admin account. Their names and emails stay private; "
                 "you see the dormitories they approved:", [_table(["Dormitory", "Location"], rows)] if rows else [])
    if not data:
        if re.search(r"\b(branch|dorm|dormitor)\w*\b", t):
            return R("report_super", "No dormitory has approved analytics sharing with you yet, so there is no branch data. Connect one on the Dormitories tab.")
        return None
    rows = []
    for bid, doc, snaps in data:
        if not snaps:
            continue
        last = snaps[-1]
        prev = [x for x in snaps if x["_t"] <= last["_t"] - timedelta(days=30)]
        tot, vac = last.get("total") or 0, last.get("vacant") or 0
        occ = last.get("occupied") if isinstance(last.get("occupied"), int) else tot - vac
        rate = agent._pct(occ, tot)
        ch = rate - agent._pct((prev[-1].get("occupied") if isinstance(prev[-1].get("occupied"), int) else (prev[-1].get("total") or 0) - (prev[-1].get("vacant") or 0)), prev[-1].get("total") or 0) if prev else None
        rk = agent.risk_of(snaps)
        rows.append({"name": doc.get("dormName") or bid, "total": tot, "vac": vac, "occ": occ, "rate": rate, "ch": ch, "risk": rk["level"] if rk else "safe"})
    if not rows:
        return R("report_super", "The approved dormitories haven't sent any data yet.")
    table = _table(["Dormitory", "Beds", "Occupied", "Vacant", "Occupancy", "30-day change", "Risk"],
                   [[x["name"], x["total"], x["occ"], x["vac"], agent._p(x["rate"]), ("%+.1f pts" % x["ch"]) if x["ch"] is not None else "n/a", x["risk"].title()] for x in sorted(rows, key=lambda x: -x["rate"])])
    m = re.search(r"\btop\s+(\d|three|five|two)\b", t)
    if m:
        n = n_of(m.group(1)) or 3
        key = "vac" if re.search(r"vacan", t) else "rate"
        top = sorted(rows, key=lambda x: -x[key])[:n]
        return R("super_top", "Top %d by %s: %s." % (len(top), "vacant beds" if key == "vac" else "occupancy",
                 "; ".join("%d. %s (%s)" % (k + 1, x["name"], (str(x["vac"]) + " vacant") if key == "vac" else agent._p(x["rate"])) for k, x in enumerate(top))), [table])
    if has(t, r"\bwhy\b", r"\breasons?\b", r"\bwhat happened\b"):
        x = min(rows, key=lambda x: x["rate"])
        dn = [y for y in rows if y["ch"] is not None and y["ch"] < 0]
        x = min(dn, key=lambda y: y["ch"]) if dn and re.search(r"declin|drop|fell|decreas|low", t) else x
        snaps = next((sn for _b, d, sn in data if (d.get("dormName") or _b) == x["name"]), [])
        rk = agent.risk_of(snaps) if snaps else None
        why = (rk or {}).get("why") or []
        return R("super_why", "%s: occupancy %s%s. What the numbers show: %s. The exact reasons (who left and why) are in that dormitory's "
                 "Tenant History, which only its Branch Admin sees — ask them, and compare with the move-out reasons." % (
                     x["name"], agent._p(x["rate"]), (", %+.1f pts in 30 days" % x["ch"]) if x["ch"] is not None else "",
                     "; ".join(why) if why else "%d vacant of %d beds" % (x["vac"], x["total"])), [table])
    if has(t, r"\b(total|all|across)\b.*\b(tenants|occupied|residents)\b", r"\bhow many\b.*\b(occupied|tenants)\b"):
        return R("super_totals", "Across %s: %d occupied beds (tenants) of %d, %d vacant." % (_plural(len(rows), "dormitory", "dormitories"), sum(x["occ"] for x in rows),
                 sum(x["total"] for x in rows), sum(x["vac"] for x in rows)), [table])
    if has(t, r"\b(most|highest|many)\b.*\bvacant beds?\b", r"\bvacant beds?\b.*\b(most|highest)\b", r"\b(total )?vacant beds?\b.*\b(all|across|every)\b", r"\bhow many vacant\b"):
        top = max(rows, key=lambda x: x["vac"])
        if re.search(r"\b(total|all|across|how many)\b", t) and not re.search(r"\b(which|most)\b", t):
            return R("super_vacant", "%d vacant beds across %s." % (sum(x["vac"] for x in rows), _plural(len(rows), "dormitory", "dormitories")), [table])
        return R("super_vacant", "%s has the most vacant beds: %d of %d." % (top["name"], top["vac"], top["total"]), [table])
    if has(t, r"\bbelow\s+(\d+)\s*(%|percent)"):
        lim = float(re.search(r"\bbelow\s+(\d+)", t).group(1))
        low = [x for x in rows if x["rate"] < lim]
        return R("super_below", ("%s below %d%% occupancy: %s." % (_plural(len(low), "dormitory is", "dormitories are"), lim, ", ".join("%s (%s)" % (x["name"], agent._p(x["rate"])) for x in low)))
                 if low else "No dormitory is below %d%% occupancy." % lim, [table])
    if has(t, r"\b(declin\w*|dropping|falling|decreas\w*|getting worse|went down|niubos)\b"):
        dn = [x for x in rows if x["ch"] is not None and x["ch"] < 0]
        return R("super_declining", ("Occupancy fell in the last 30 days at: %s." % ", ".join("%s (%+.1f pts)" % (x["name"], x["ch"]) for x in sorted(dn, key=lambda x: x["ch"])))
                 if dn else "No dormitory's occupancy fell in the last 30 days.", [table])
    if has(t, r"\b(lowest|least|worst|poorest|weakest)\b", r"\blow\w* (occupancy|performance)\b"):
        x = min(rows, key=lambda x: x["rate"])
        return R("super_lowest", "%s has the lowest occupancy: %s (%d of %d beds)." % (x["name"], agent._p(x["rate"]), x["occ"], x["total"]), [table])
    if has(t, r"\b(highest|best|top|strongest|doing better|most occupied)\b") and not has(t, r"\bvacan"):
        x = max(rows, key=lambda x: x["rate"])
        return R("super_highest", "%s has the highest occupancy: %s (%d of %d beds)." % (x["name"], agent._p(x["rate"]), x["occ"], x["total"]), [table])
    if has(t, r"\b(strategy|recommend\w*|suggest\w*|target|type of tenants|retention|best time|when (should|to) (we )?promote|reduce|what can we do|"
           r"biggest|problems?|need to do|next steps?|how can we increase|advertis\w*|promotional|remained vacant|longest)\b"):
        worst = sorted(rows, key=lambda x: -x["vac"])
        recs = []
        for x in worst[:2]:
            if x["vac"]:
                recs.append("Promote %s first: %d vacant beds (%s occupancy)." % (x["name"], x["vac"], agent._p(x["rate"])))
        dn = [x for x in rows if x["ch"] is not None and x["ch"] < -3]
        if dn:
            recs.append("Ask %s's Branch Admin why occupancy fell (%s in 30 days) — Tenant History shows the move-out reasons." % (dn[0]["name"], "%+.1f pts" % dn[0]["ch"]))
        recs += ["Target the groups each branch has room for (students or reviewees, male or female) — the directory shows these counts per dormitory.",
                 "Promote 3–4 weeks before each semester and review season starts, when most people look for a bed.",
                 "Keep tenants: contact them a month before their check-out to offer renewal; it is cheaper than finding a new tenant."]
        if has(t, r"\b(rooms?|longest)\b"):
            recs.insert(0, "Room-by-room vacancy and how long beds stay empty are with each Branch Admin; at branch level the numbers are below.")
        return R("super_advice", "Based on the branches' latest numbers:", [_list(recs), table])
    if has(t, r"\b(attention|prioriti[sz]e|focus|improv\w*|needs? (help|work)|first)\b", r"\bmarketing\b", r"\bpromot\w*\b", r"\bgrowth|expan\w*|potential\b"):
        worst = sorted(rows, key=lambda x: ({"high": 0, "moderate": 1, "safe": 2}[x["risk"]], x["rate"]))
        w = worst[0]
        why = ["occupancy %s" % agent._p(w["rate"]), "%d vacant beds" % w["vac"]] + (["%+.1f pts in 30 days" % w["ch"]] if w["ch"] is not None else [])
        recs = ["Promote %s's %d vacant beds in the directory and with schools near it." % (w["name"], w["vac"]),
                "Check with its Branch Admin why tenants left (Tenant History reasons) and fix the top reason.",
                "Offer a longer-stay or group discount there before the next semester starts."]
        return R("super_priority", "Focus on %s first: %s, risk %s." % (w["name"], ", ".join(why), w["risk"]), [table, {"type": "subheading", "text": "Suggested next steps"}, _list(recs)])
    if has(t, r"\b(compare|comparison|versus|vs|each branch|every branch|all branches|performance|summar\w*|overview|report|big picture)\b"):
        if has(t, r"\breport\b") and not has(t, r"\blast (month|year)\b"):
            return agent.super_report(cur, uid, t, today or datetime.now(timezone.utc).date())
        if has(t, r"\blast (month|year)\b|\bprevious month\b|\bthis year\b"):
            have = max(((snaps[-1]["_t"] - snaps[0]["_t"]).days for _b, _d, snaps in data if snaps), default=0)
            note = "Changes are against 30 days ago (the table's 30-day column)." + ("" if not has(t, r"\byear\b") else " Year-on-year needs a year of history; there are %d days so far." % have)
            ups = [x for x in rows if x["ch"] is not None]
            text = "Last 30 days: " + "; ".join("%s %s (%+.1f pts)" % (x["name"], agent._p(x["rate"]), x["ch"]) for x in ups) + "." if ups else "Not enough history yet to compare with last month."
            return R("super_compare", text, [table, _note(note)])
        best, worst = max(rows, key=lambda x: x["rate"]), min(rows, key=lambda x: x["rate"])
        return R("super_compare", "Across %s: occupancy %s overall. Best: %s (%s). Lowest: %s (%s)." % (
            _plural(len(rows), "dormitory", "dormitories"), agent._p(agent._pct(sum(x["occ"] for x in rows), sum(x["total"] for x in rows))),
            best["name"], agent._p(best["rate"]), worst["name"], agent._p(worst["rate"])), [table])
    if has(t, r"\b(female|male)\b.*\b(beds?|vacan\w*)\b"):
        g = "femaleVacant" if "female" in t else "maleVacant"
        dirs = [d for _i, d, _v in list_docs(cur, KINDS["directory"], [], limit=500)]
        dirs = sorted(dirs, key=lambda d: -int(d.get(g) or 0))
        if dirs:
            return R("super_gender", "%s lists the most vacant %s beds in the directory: %d." % (dirs[0].get("dormName"), "female" if g == "femaleVacant" else "male", int(dirs[0].get(g) or 0)),
                     [_table(["Dormitory", "Vacant " + ("female" if g == "femaleVacant" else "male")], [[d.get("dormName"), int(d.get(g) or 0)] for d in dirs[:10]])])
    if has(t, r"\b(check ?outs?|leaving)\b"):
        return R("super_checkouts", "Branch analytics share totals only, not check-out dates, so I can't rank branches by upcoming check-outs. "
                 "Each Branch Admin sees them in their Checkout Schedule.")
    return None


# ============================================================================== Marketing Directory
def marketing(conn, uid, t, today):
    cur = conn.cursor()
    items = [dict(doc, id=i) for i, doc, _v in list_docs(cur, KINDS["directory"], [], limit=500)]
    if not items:
        return None
    rows = sorted(items, key=lambda x: -int(x.get("vacant") or 0))
    table = _table(["Dormitory", "Location", "Vacant beds", "Beds", "Vacancy"],
                   [[x.get("dormName"), x.get("location") or "", int(x.get("vacant") or 0), int(x.get("total") or 0),
                     agent._p(agent._pct(int(x.get("vacant") or 0), int(x.get("total") or 0)))] for x in rows])
    g = "femaleVacant" if re.search(r"\bfemale|girls?|ladies|women\b", t) else "maleVacant" if re.search(r"\bmale|boys?|men\b", t) else None
    grp = "studentVacant" if re.search(r"\bstudents?\b", t) else "revieweeVacant" if re.search(r"\breviewees?\b", t) else None
    if g and grp:
        rs = sorted(items, key=lambda x: -(int(x.get(g) or 0) + int(x.get(grp) or 0)))
        gl, pl = ("female" if g == "femaleVacant" else "male"), ("student" if grp == "studentVacant" else "reviewee")
        return R("market_combo", "The directory counts %s beds and %s beds separately, not %s %s beds together. Most of both: %s (%d %s, %d %s). "
                 "Ask the dormitory which of those beds suit a %s %s." % (gl, pl, gl, pl, rs[0].get("dormName"), int(rs[0].get(g) or 0), gl, int(rs[0].get(grp) or 0), pl, gl, pl),
                 [_table(["Dormitory", "Vacant %s" % gl, "Vacant %s" % pl, "All vacant"], [[x.get("dormName"), int(x.get(g) or 0), int(x.get(grp) or 0), int(x.get("vacant") or 0)] for x in rs])])
    if has(t, r"\b(predict\w*|forecast|next month|next three months|trend|possible vacanc\w*|will become|pattern|seasonal|demand|potential tenants|potential customers)\b"):
        return R("market_forecast", "The directory shows each dormitory's vacancies today, not their check-out dates or booking history, so I can't predict "
                 "next month or show seasonal patterns. Today: %d vacant beds across %s, most at %s (%d)." % (
                     sum(int(x.get("vacant") or 0) for x in rows), _plural(len(rows), "dormitory", "dormitories"), rows[0].get("dormName"), int(rows[0].get("vacant") or 0)), [table])
    if has(t, r"\b(why|reason)\b"):
        return R("market_why", "The directory shows only how many beds are vacant, not why. The dormitory's Branch Admin sees the reasons tenants left "
                 "(Tenant History). Today's numbers:", [table])
    if has(t, r"\b(strategy|recommend\w*|suggest\w*|how (can|do) (we|i)|attract|increase (occupancy|bookings)|fill|what should|best action|campaign|"
           r"promot\w*|focus|invest|target|needs? marketing|help|opportunity|growth|expan\w*|improve|reduce|what can we do|problems?|retention)\b"):
        top = rows[:3]
        fem = max(items, key=lambda x: int(x.get("femaleVacant") or 0))
        stu = max(items, key=lambda x: int(x.get("studentVacant") or 0))
        recs = ["Promote %s first: %d vacant beds (%s vacancy)." % (top[0].get("dormName"), int(top[0].get("vacant") or 0), agent._p(agent._pct(int(top[0].get("vacant") or 0), int(top[0].get("total") or 0))))]
        if int(fem.get("femaleVacant") or 0):
            recs.append("Female students and workers: %s has %d vacant female beds — advertise near schools and review centres." % (fem.get("dormName"), int(fem.get("femaleVacant") or 0)))
        if int(stu.get("studentVacant") or 0):
            recs.append("Students: %s has %d student beds free — time posts 3–4 weeks before the semester starts." % (stu.get("dormName"), int(stu.get("studentVacant") or 0)))
        recs.append("Show photos of the rooms and the exact vacant count from the directory; update them weekly.")
        recs.append("Offer a group or long-stay rate where vacancy is above 25%.")
        return R("market_strategy", "Based on today's directory numbers:", [_list(recs), table])
    if has(t, r"\b(compare|comparison|all|every|each)\b"):
        return R("market_compare", "Vacancies in every listed dormitory, most first:", [table])
    if has(t, r"\b(why|reason)\b"):
        return R("market_why", "The directory shows only how many beds are vacant, not why. The dormitory's Branch Admin sees the reasons tenants left "
                 "(Tenant History). Today's numbers:", [table])
    if has(t, r"\b(performance|best|doing better|highest occupancy|lowest vacancy)\b"):
        best = min(items, key=lambda x: agent._pct(int(x.get("vacant") or 0), int(x.get("total") or 0)) if int(x.get("total") or 0) else 100)
        return R("market_best", "%s is the fullest: %d of %d beds vacant." % (best.get("dormName"), int(best.get("vacant") or 0), int(best.get("total") or 0)), [table])
    return None


# ============================================================================== privacy + things the app does not record
PERSONAL = re.compile(r"\bwho\b.*\b(tenants?|residents?|staying|living|lives|occupants?|boarders?)\b|\b(names?|who (is|are|lives|stays|staying|checks?|will)|whos|whose|tenant'?s? (name|number|phone|contact|address|info\w*|details|profile)|"
                      r"phone|contacts?|mobile|email|address|emergency|photos?|pictures?|private (tenant )?information|personal (info\w*|details|data)|"
                      r"tenant information|unpaid tenants|who (has|have|did) not paid|follow up)\b")
MONEY = re.compile(r"\b(revenue|income|earn\w*|profit\w*|sales|money|unpaid|balance|outstanding|payments?|paid|pay|rent|rental|fee|fees|price|prices|"
                   r"cost|costs|how much|monthly rate|discount\w*|financial|losing|lose|lost|kita)\b")


def privacy_guard(t, page):
    """Viewer, Marketing and Super Admin pages never share a tenant's personal details."""
    if page not in ("viewer", "marketing", "superadmin"):
        return None
    if not PERSONAL.search(t):
        return None
    who_about_people = re.search(r"\b(tenants?|residents?|boarders?|occupants?|people|person|guests?|who|whos|whose|names?|emergency|contact|phone|address|"
                                 r"admin'?s? (email|name)|private)\b", t)
    if not who_about_people:
        return None
    if page == "viewer":
        if re.search(r"\bwho\b.*\b(check(s|ed|ing)? ?outs?|leav\w*|check(s|ed|ing)? ?ins?|arriv\w*)\b", t):
            return None                               # answered without names (beds and dates only) by the viewer layer
        return R("privacy", "Viewers can't see who lives in a bed: names, contact numbers, emergency contacts, addresses and photos are "
                 "private to the dormitory's Branch Admin. I can tell you which beds are vacant, occupied or reserved and their dates.")
    if page == "marketing":
        return R("privacy", "The directory shows vacancy counts only. Tenant names, contact numbers and other personal details are private "
                 "to each dormitory's Branch Admin, so I can't share them.")
    if not re.search(r"\b(tenants?|residents?|boarders?|occupants?|guests?|emergency|private|personal|lives|living|staying)\b", t):
        return None                                   # "who are our admins?", "who requested access?" are fine here
    return R("privacy", "Tenant names, contact numbers and other personal details stay with each dormitory's Branch Admin. Branch sharing gives "
             "you counts and statistics only, so I can't show another branch's private tenant information.")


def money(t, page):
    if not MONEY.search(t):
        return None
    if re.search(r"\b(how much|how many) (beds?|rooms?|vacan\w*|tenants)\b", t) and not re.search(r"\b(rent|revenue|income|pay|price|cost)\b", t):
        return None
    if re.search(r"\bdiscount\w*\b", t):
        return R("money_discount", "Prices aren't kept in the app, so I can't calculate a discount's effect. A long-stay discount usually makes sense "
                 "where vacancy is high and stays are short. %s" % ("Ask me which rooms have been vacant the most." if page == "admin" else "Ask me which branch has the most vacant beds."))
    if page == "viewer":
        return R("money_rent", "The Dormitory Viewer doesn't list rent or prices. Ask the dormitory directly (its contact is with the person who "
                 "gave you the dorm code). I can show which beds are vacant and from when.")
    if page == "marketing":
        return R("money_rent", "The directory doesn't include rent, prices or income — only vacancy counts. Contact the dormitory for its rates.")
    lost = re.search(r"\b(losing|lose|lost|potential|could (we )?(generate|earn)|if all beds|vacant beds)\b", t)
    extra = ""
    if lost and page == "admin":
        extra = " If you tell me your monthly rate per bed, I can multiply it by the vacant beds for you."
    return R("money_not_tracked", "The Vacancy Tracker doesn't record rent, payments or revenue, so I can't tell you amounts, unpaid balances or "
             "income — and I won't guess money figures.%s I can show occupancy, vacancies and check-outs instead." % extra,
             suggestions=["What is our occupancy rate?", "How many beds are vacant?", "Who checks out this month?"])


# ---------------------------------------------------------------------------------- how the app handles situations
def admin_policy(D, W, t, today, ctx):
    rec = D.rec
    m = re.search(r"\bcheck ?out on (.+?)[.,]? can (another|a new|the next) (tenant|person|client) check ?in on (.+?)\??$", t)
    if m:
        a = smart.find_dates(m.group(1), today)
        b = smart.find_dates(m.group(4), today)
        if a and b:
            out, inn = a[0][1], b[0][1]
            if inn > out:
                return R("policy", "Yes. A bed is busy until check-out day (12:00), so it's free for a new tenant from %s. Reserve or check them in on that bed for %s." % (pretty(out), pretty(inn)))
            if inn == out:
                return R("policy", "Yes, same-day turnover works: check-out is at 12:00 and check-in at 14:00. Check the leaving tenant out first if they leave early.")
            return R("policy", "No: on %s the bed is still occupied until %s. Choose another bed or a check-in date after %s." % (pretty(inn), pretty(out), pretty(out)))
    if has(t, r"\bcheck(s|ed)? ?out today\b.*\bcheck(s|ed)? ?in today\b", r"\bsame[- ]day\b"):
        return R("policy", "Yes, same day is fine: check-out is at 12:00 and check-in at 14:00. In the app, check the leaving tenant out first (the bed turns "
                 "vacant), then check the new tenant in. A reservation for that day is allowed on the bed too.")
    if has(t, r"\b(two|2) (tenants?|people|clients?) (want|reserve|book)\w*\b.*\bsame bed\b", r"\bsame bed\b.*\boverlap\w*\b", r"\bdouble[- ]book\w*\b"):
        return R("policy", "Only one person can have a bed for any given dates. Reserve Client checks the dates: the bed is held for the first "
                 "reservation, and the second person is offered another bed or later dates. A bed holds one reservation at a time. "
                 "Ask me “are there overlapping reservations?” to check the current ones.")
    m = re.search(r"\bextend\w*\b.*?\bby\s+" + NUMW + r"\s+(day|week|month)s?\b", t)
    if has(t, r"\bextend\w*\b") and has(t, r"\b(conflict|overlap|clash)\w*\b|\breservations?\b") and not has(t, r"\bavailability\b"):
        days = (n_of(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)]) if m else 0
        rows = []
        for r in rec.rooms:
            for i, b in enumerate(r["beds"]):
                if b.get("tenant") and b.get("reservedFor"):
                    p = next((x for x in rec.prospects if x.get("id") == b["reservedFor"]), None)
                    e, c = parse_iso(b.get("end")), parse_iso((p or {}).get("checkIn"))
                    if p and e and c:
                        new_end = e + timedelta(days=days)
                        rows.append([b["tenant"], "Room %s %s" % (r["room"], bed_label(b, i)), pretty(e), pretty(new_end), p.get("name"), pretty(c),
                                     "conflict" if new_end > c else "ok"])
        bad = [x for x in rows if x[-1] == "conflict"]
        lead = ("Extending by %d days would clash with %s." % (days, _plural(len(bad), "reservation"))) if days else \
            "These tenants have a reservation waiting on their bed, so extending them can clash:"
        if not rows:
            return R("policy", "No current tenant has a reservation waiting on their bed, so extending a stay won't clash with a reservation. "
                     "Say: extend <name> until <date>, and I'll prepare it for you to confirm.")
        return R("policy", lead, [_table(["Tenant", "Bed", "Ends", "After extension", "Next reservation", "Arrives", "Result"], rows),
                                  _note("If it clashes, move the reservation to another bed in Reserved Clients first.")])
    if has(t, r"\bearlier than (their |the )?reservation\b", r"\bcheck ?in early\b", r"\barrive (early|earlier)\b"):
        return R("policy", "Yes, if their held bed is free on the earlier date. Open Reserved Clients and check them in now (or move the reservation's "
                 "check-in date). If the bed is still occupied, check them in on another vacant bed instead.")
    if has(t, r"\bfail\w* to check ?out\b", r"\b(doesnt|does not|didnt|did not) check ?out\b", r"\boverstay\w*\b", r"\bwhat happens\b.*\bcheck ?out date\b"):
        return R("policy", "After the check-out date the bed turns red (overdue). It still counts as occupied, so it never shows as vacant by "
                 "mistake, and the menu shows a reminder. Check the tenant out, or extend their stay. Ask me “who is overdue?” to see them.")
    if has(t, r"\breservation (is |gets )?cancel\w*\b", r"\bcancel\w* (a )?reservation\b.*\b(affect|statistic|vacan)\w*"):
        return R("policy", "The held bed becomes vacant again immediately: vacant beds go up by one and reserved goes down by one. Occupancy doesn't "
                 "change, because a reserved bed isn't occupied yet.")
    if has(t, r"\b(already )?occupied bed\b.*\b(future|later|reserve)\b", r"\breserve\b.*\boccupied\b"):
        return R("policy", "Yes, if the current tenant leaves before the client arrives. Reserve Client checks the dates for you: it shows that bed "
                 "as available from the tenant's check-out. Same-day is fine (check-out 12:00, check-in 14:00). A bed holds one reservation at a time.")
    if has(t, r"\bmaintenance\b.*\b(accept|reserv|book)\w*", r"\b(accept|reserv|book)\w*\b.*\bmaintenance\b"):
        return R("policy", "The app has no maintenance status yet, so it would still show that room's free beds as vacant and allow reservations. "
                 "Until that exists, don't reserve beds in a room under repair, and remember they still count in the vacancy numbers.")
    if has(t, r"\bdelete (all|every)\b.*\b(tenants?|records?|rooms?|data)\b", r"\b(wipe|erase|clear) (all|everything)\b"):
        return R("policy_refuse", "I won't delete everything at once — that can't be undone. Deleting is done one tenant or room at a time on Room Canvas, "
                 "and I always ask you to confirm. To start fresh, use Data Transfer to save a copy first.")
    if has(t, r"\b(change|update|edit|move) (this |the |a )?tenants? (contract|check ?out|end) date\b", r"\bchange (his|her|their) contract\b"):
        hits = smart.people_hits(t, [(b["tenant"], b) for _r, _i, b in rec.occupied()])
        if not hits:
            return R("clarify", "Which tenant? Say for example: extend Ana Reyes until March 31. I'll show the change and you confirm it.")
    m = re.search(r"\b(?:tenant |person |someone )?(?:named|called|name is)\s+([a-z][a-z .'-]{1,40})\??$", t)
    if m:
        name = m.group(1).strip()
        hits = [(b["tenant"], r, i, b) for r, i, b in rec.occupied() if name in b["tenant"].lower()]
        if not hits:
            return R("data_find", "No current tenant is named %s." % name.title())
        if len(hits) > 1:
            return R("data_find", "%d tenants match “%s” — which one?" % (len(hits), name.title()),
                     [_table(["Tenant", "Room", "Bed", "Until"], [[n, r["room"], bed_label(b, i), pretty(parse_iso(b.get("end"))) if b.get("end") else "no end date"] for n, r, i, b in hits])])
        n, r, i, b = hits[0]
        return R("data_find", "%s is in Room %s, %s, until %s." % (n, r["room"], bed_label(b, i), pretty(parse_iso(b.get("end"))) if b.get("end") else "no end date"))
    return None


# ---------------------------------------------------------------------------------- advice from the records
def admin_insights(D, W, t, today, ctx):
    rec = D.rec
    total = sum(len(r["beds"]) for r in rec.rooms)
    occ = sum(1 for _ in rec.occupied())
    vac = len(rec.vacant_beds())
    if has(t, r"\b(big picture|overall|how are we doing|state of)\b") and not has(t, r"\b(branch|predict|forecast|recommend\w*|suggest\w*|actions?|improve)\b"):
        return agent.vacancy_report(D.cur, D.uid, t, today)
    if has(t, r"\b(getting|more) (more )?(customers|tenants|bookings|check ?ins)\b", r"\bare we (growing|getting)\b", r"\bregistration trends?\b"):
        def started(a, b):
            n = sum(1 for _r, _i, x in rec.occupied() if parse_iso(x.get("start")) and a <= parse_iso(x.get("start")) < b)
            return n + sum(1 for h in D.hist if parse_iso(h.get("start")) and a <= parse_iso(h.get("start")) < b)
        now30, prev30 = started(today - timedelta(days=30), today + timedelta(days=1)), started(today - timedelta(days=60), today - timedelta(days=30))
        word = "more" if now30 > prev30 else "fewer" if now30 < prev30 else "the same number of"
        return R("insight_growth", "You had %s new tenants in the last 30 days: %d, against %d in the 30 days before. %d reservation%s waiting." % (
            word, now30, prev30, sum(1 for p in rec.prospects if not p.get("checkedIn")), "" if sum(1 for p in rec.prospects if not p.get("checkedIn")) == 1 else "s"))
    reasons = Counter((h.get("reason") or "Not given") for h in D.hist)
    by_cat = {}
    for g in ("Male", "Female"):
        by_cat[g] = len(rec.vacant_beds(gender=g))
    if has(t, r"\b(causes?|reasons?|why)\b.*\b(occupancy|vacanc\w*)\b.*\b(decreas\w*|drop\w*|low|fall\w*|down)\b",
           r"\boccupancy (decreas|drop|fall|go(es)? down)\w*\b.*\b(causes?|reasons?|why)\b"):
        items = ["Contracts ending without renewal — %s end in the next 30 days." % _plural(len(smart.departures(rec, today, today, today + timedelta(days=30))), "contract"),
                 "Tenants leaving early — Tenant History reasons: %s." % (", ".join("%s (%d)" % kv for kv in reasons.most_common(3)) or "none recorded yet"),
                 "Rooms that don't match demand — vacant beds now: %d in male rooms, %d in female rooms." % (by_cat["Male"], by_cat["Female"]),
                 "Season: fewer arrivals between semesters or after review season.",
                 "Price, condition or competition nearby (the app doesn't track these)."]
        return R("insight_causes", "Likely causes to check, with what your records show:", [_list(items)])
    if has(t, r"\b(three|3|biggest|main|top)\b.*\b(problems?|issues?)\b", r"\boccupancy problems?\b"):
        od = sum(1 for _r, _i, b in rec.occupied() if parse_iso(b.get("end")) and parse_iso(b.get("end")) < today)
        soon = len(smart.departures(rec, today, today, today + timedelta(days=30)))
        worst = max(rec.rooms, key=lambda r: D.counts(r)["vacant"])
        items = ["%s vacant (%s of all beds); most in Room %s (%d)." % (_plural(vac, "bed is", "beds are"), agent._p(agent._pct(vac, total)), worst["room"], D.counts(worst)["vacant"]),
                 "%s within 30 days — they become vacant unless renewed." % _plural(soon, "check-out"),
                 "%s past the check-out date: the real vacancy may be higher than shown." % _plural(od, "tenant is", "tenants are")]
        return R("insight_problems", "Your three biggest occupancy issues right now:", [_list(items)])
    m = re.search(r"\b(\d{1,3})\s*(%|percent) (increase|more)\b.*\breservations?\b", t)
    if m:
        res = sum(1 for p in rec.prospects if not p.get("checkedIn") and not p.get("checkedOut"))
        extra = max(1, round(res * int(m.group(1)) / 100)) if res else round(vac * int(m.group(1)) / 100)
        return R("insight_whatif", "Now: %d reservations and %d vacant beds (%s vacancy). %s%% more reservations is about %d more, so vacancy would fall to about %d beds (%s)." % (
            res, vac, agent._p(agent._pct(vac, total)), m.group(1), extra, max(0, vac - extra), agent._p(agent._pct(max(0, vac - extra), total))))
    if has(t, r"\b(recommend|suggest|what should we do|actions?|improve|increase|boost|raise|reduce)\b.*\b(occupancy|performance|business|vacanc\w*|retention|tenants)\b",
           r"^(what (is |are )?)?(your |any )?(recommendations?|suggestions?|advice)\??$",
           r"\bimprove (tenant )?retention\b"):
        soon = smart.departures(rec, today, today, today + timedelta(days=30))
        g = max(by_cat, key=by_cat.get)
        recs = ["Ask the %s tenants whose contracts end within 30 days to renew now (say: which tenants need contract renewal?)." % len(soon),
                "Advertise the %s vacant beds, especially the %d in %s rooms — post the exact count and photos." % (vac, by_cat[g], g.lower()),
                "Fix the top move-out reason in Tenant History: %s." % (reasons.most_common(1)[0][0] if reasons else "none recorded yet — start writing reasons when checking out")]
        if has(t, r"\bretention\b"):
            recs = ["Contact tenants 30 days before check-out to offer renewal (%s due now)." % len(soon),
                    "Keep Tenant Information complete so you can reach people quickly.",
                    "Read the reasons in Tenant History (%s) and fix the most common one." % (", ".join(k for k, _v in reasons.most_common(2)) or "none recorded yet")]
        return R("insight_actions", "Three things to do, based on your records:", [_list(recs)])
    if has(t, r"\b(highest )?risk of (remaining|staying) vacant\b", r"\b(remained|stayed|been) vacant (for )?(the )?long\w*\b", r"\bprioriti[sz]e (for )?advertis\w*\b",
           r"\bwhich rooms should (we )?(advertise|promote|receive promotional)\b", r"\bpromotional offers?\b"):
        rows = []
        for r in rec.rooms:
            c = D.counts(r)
            if c["vacant"]:
                rows.append([r["room"], c["vacant"], len(r["beds"]), r.get("gender") or "Mixed", r.get("demographic") or "Mixed", c["reserved"]])
        rows.sort(key=lambda x: (-x[1] / max(1, x[2]), -x[1]))
        return R("insight_rooms", "Rooms with the most empty space and no reservation to fill it should be promoted first: %s." % ", ".join(str(x[0]) for x in rows[:5]),
                 [_table(["Room", "Vacant", "Beds", "Gender", "Group", "Reserved"], rows[:15]),
                  _note("How long each bed has been empty isn't recorded, so this uses today's vacancy.")])
    if has(t, r"\brenovat\w*\b"):
        return R("insight_renovation", "Room condition isn't recorded, so I can't tell which rooms need renovation. A practical choice: rooms with the most vacant "
                 "beds, since fixing them is most likely to bring tenants — ask me which rooms have the highest vacancy.")
    if has(t, r"\b(increase|add|more) (room )?capacity\b.*\b(open|new) (another |a )?branch\b", r"\bopen another branch\b", r"\bexpand\w*\b"):
        rate = agent._pct(occ, total)
        advice = ("You're nearly full (%s occupied), so adding beds or another branch makes sense." % agent._p(rate)) if rate >= 90 else \
            ("You're at %s occupancy with %d vacant beds, so fill the current beds before adding capacity or a branch." % (agent._p(rate), vac))
        return R("insight_expand", advice)
    if has(t, r"\bshort[- ]term\b"):
        rows = []
        for r in rec.rooms:
            for i, b in enumerate(r["beds"]):
                if smart.bed_vacant(b):
                    rows.append([r["room"], bed_label(b, i)])
        return R("insight_shortterm", "Good candidates for short stays are beds that are vacant now with no reservation: %s. Use Temporary Dorm Clients "
                 "for stays of a few days, so the bed frees up automatically." % _plural(len(rows), "bed"), [_table(["Room", "Bed"], rows[:20])] if rows else [])
    if has(t, r"\bextend\w* (tenant )?contracts?\b.*\b(affect|future|availability)\b"):
        soon = smart.departures(rec, today, today, today + timedelta(days=30))
        return R("insight_extend", "Every extension keeps a bed occupied longer, so it won't free up on the date shown in the Checkout Schedule. "
                 "Right now %s are due to free up in 30 days; each one you extend lowers that number and can clash with a reservation on the bed." % _plural(len(soon), "bed"))
    if has(t, r"\bactual\b.*\bprojected\b", r"\bprojected occupancy\b"):
        return None
    return None
