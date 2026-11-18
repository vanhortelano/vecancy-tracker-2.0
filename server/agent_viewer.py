"""Assistant for the Dormitory Viewer (viewer.html) and the dormitory directory (marketing.html), plus the
category answers shared with the Branch Admin page.

Permissions
  * Viewer: only the published, name-free copy of ONE dormitory (dorm_vacancy), and only while the server's
    viewer rule says this account may see it (same check as the page itself). Read-only: no changes, no names,
    photos, contact numbers or emergency contacts (they are not in the published copy at all).
  * Directory: the dormitory cards every signed-in viewer of the directory can already see.
All counts use vacancy_core (the Python copy of vacancy-core.js), so the assistant and the pages agree.
"""
import re
import time

import agent_nlu
import vacancy_core as vc
from rules import Ctx, _viewer_visible
from store import KINDS, list_docs

GENDERS = {"male": "Male", "female": "Female", "mixed": "Mixed"}
GROUPS = {"students": "Students", "student": "Students", "reviewees": "Reviewees", "reviewee": "Reviewees"}
VIEWS = {"hallway": "Hallway layout", "analytics": "Analytics", "vacancies": "Vacancies"}
VIEWER_INTENTS = ["vacancy_summary", "occupancy_summary", "upcoming", "checkins", "compare", "report", "explain", "trend",
                  "room_status", "highest", "nav_hallway", "nav_analytics", "nav_vacancies", "memory_show", "help", "admin_only"]


def _reply(intent, text, blocks=None, nav=None, suggestions=None):
    return {"intent": intent, "response": text, "blocks": blocks or [], "nav": nav, "action": {"type": "none"},
            "suggestions": suggestions or [], "log": True}


def clock(ctx):
    """The browser's clock and time zone (sanity-checked against the server clock)."""
    server = int(time.time() * 1000)
    try:
        now = int(ctx.get("now"))
        if abs(now - server) > 2 * vc.DAY_MS:
            now = server
    except (TypeError, ValueError):
        now = server
    try:
        tz = int(ctx.get("tzOffset"))
        if not -840 <= tz <= 840:
            tz = 0
    except (TypeError, ValueError):
        tz = 0
    return now, tz


def clean_filters(f):
    f = f if isinstance(f, dict) else {}
    out = {}
    for k in ("status", "gender", "demographic", "room", "search"):
        v = f.get(k)
        if isinstance(v, str) and len(v) <= 60:
            out[k] = v
    return out


def scope_from_text(tn, base):
    """'for male', 'female students', 'reviewees' in the question narrow (or replace) the page's filters."""
    f = dict(base)
    g = [GENDERS[w] for w in ("male", "female", "mixed") if re.search(r"\b%s\b" % w, tn)]
    if len(g) == 1:
        f["gender"] = g[0]
    grp = [v for k, v in GROUPS.items() if re.search(r"\b%s\b" % k, tn)]
    if len(set(grp)) == 1:
        f["demographic"] = grp[0]
    if re.search(r"\b(all|overall|whole|entire|every)\b", tn) and not g and not grp:
        f = {}
    return f


def _p(x):
    return ("%.1f" % x).rstrip("0").rstrip(".") + "%"


def stat_lines(st):
    items = ["Total beds: %d" % st["total"], "Occupied: %d" % st["occupied"], "Vacant: %d" % st["vacant"],
             "Upcoming vacancies (check-out within %d days, still occupied): %d" % (vc.UPCOMING_DAYS, st["upcoming"])]
    if st["reserved"]:
        items.append("Reserved: %d" % st["reserved"])
    if st["overdue"]:
        items.append("Past check-out (overdue, still occupied): %d" % st["overdue"])
    items.append("Occupancy rate: %s · Vacancy rate: %s" % (_p(st["occupancyRate"]), _p(st["vacancyRate"])))
    return items


def room_ref(tn, rooms, ctx_room):
    m = re.search(r"\broom\b\s*(?:no\.?|number|#)?\s*([a-z0-9-]+)\b", tn)
    if m and m.group(1) not in ("status", "information", "info", "card", "cards"):
        hits = [r for r in rooms if str(r.get("room") or "").lower() == m.group(1).lower()] or \
            [r for r in rooms if re.search(r"\d", m.group(1)) and str(r.get("room") or "").lower().endswith("-" + m.group(1).lower())]
        if hits or re.search(r"\d", m.group(1)):
            return (hits[0] if hits else None), m.group(1)
    if ctx_room and re.search(r"\b(this|selected|current|that|the) room\b|\bhere\b|\boccupancy status\b|\bthis one\b", tn):
        return next((r for r in rooms if r.get("id") == ctx_room), None), None
    return None, None


# --------------------------------------------------------------------------- shared answers (viewer + admin)
def answer_scope(intent, tn, rooms, base_filters, now, tz, who="viewer", ctx_room=None):
    """Answers computed from a list of rooms in vacancy_core form. Never includes names."""
    f = scope_from_text(tn, base_filters)
    label = vc.scope_label(f, rooms)
    st = vc.stats(rooms, f, now, tz)
    scoped = [r for r in rooms if vc.room_matches(r, f)]
    if not rooms:
        return _reply("empty", "There are no published rooms yet, so there is nothing to count.")

    if intent == "room_status":
        room, asked = room_ref(tn, rooms, ctx_room)
        if not room:
            if asked:
                return _reply("room_missing", "I couldn't find Room %s here. Rooms: %s." % (asked.upper(), ", ".join(str(r.get("room")) for r in rooms[:15])))
            return _reply("clarify", "Which room? Click a room on the hallway map, or ask e.g. \"show room 201\".")
        states = vc.bed_states(room, now, tz)
        s = vc.summarize(states)
        rows = []
        for b in states:
            dates = []
            if b["status"] == "reserved" and b["reservedFrom"]:
                dates.append("reserved from " + vc.fmt(b["reservedFrom"], tz))
            if b["start"]:
                dates.append("check-in " + vc.fmt(b["start"], tz))
            if b["end"]:
                dates.append(("current check-out " if b["upcoming"] else "check-out ") + vc.fmt(b["end"], tz))
            rows.append([b["slot"], vc.LABEL[b["status"]] + (" · upcoming vacancy" if b["upcoming"] else ""), "; ".join(dates) or "—"])
        text = ("Room %s: %d beds — %d occupied, %d vacant%s%s." % (room.get("room"), s["total"], s["occupied"], s["vacant"],
                ", %d upcoming vacanc%s" % (s["upcoming"], "y" if s["upcoming"] == 1 else "ies") if s["upcoming"] else "",
                ", %d reserved" % s["reserved"] if s["reserved"] else ""))
        extra = {k: sum(1 for b in states if b["status"] == k) for k in ("overdue", "temporary", "reserved")}
        if extra["overdue"] or extra["temporary"]:
            text = text[:-1] + " (occupied includes %s)." % ", ".join("%d %s" % (extra[k], k) for k in ("overdue", "temporary") if extra[k])
        asked_st = [k for k, p in (("vacant", r"\b(vacan\w*|available|free|empty)\b"), ("overdue", r"\boverdue\b"), ("reserved", r"\breserv\w*\b"),
                                   ("temporary", r"\btemporar\w*\b")) if re.search(p, tn)]
        if asked_st and re.search(r"\b(how many|count|number|any|is there|are there|what|which|report)\b", tn):
            def _n(k):
                n = s["vacant"] if k == "vacant" else extra[k]
                beds = [b["slot"] for b in states if b["status"] == k]
                return "%d %s bed%s%s" % (n, k, "" if n == 1 else "s", (" (" + ", ".join(beds[:8]) + ")") if 0 < n <= 8 else "")
            text = "Room %s has %s. All together: %s" % (room.get("room"), " and ".join(_n(k) for k in asked_st), text.split(": ", 1)[1])
        return _reply("room_status", text, [{"type": "heading", "text": "Room %s" % room.get("room")},
                                            {"type": "table", "columns": ["Bed", "Status", "Dates"], "rows": rows}],
                      nav={"roomId": room.get("id"), "view": "hallway"} if who == "viewer" else None)

    if intent in ("vacancy_summary", "occupancy_summary"):
        if intent == "occupancy_summary":
            text = "Scope %s: %d of %d beds are occupied (%s occupancy)." % (label, st["occupied"], st["total"], _p(st["occupancyRate"]))
        else:
            text = "Scope %s: %d of %d beds are vacant right now." % (label, st["vacant"], st["total"])
        if st["upcoming"]:
            text += " %d more will free up within %d days (still occupied today)." % (st["upcoming"], vc.UPCOMING_DAYS)
        rooms_free = [r for r in scoped if vc.summarize(vc.bed_states(r, now, tz))["vacant"]]
        blocks = [{"type": "list", "items": stat_lines(st)}]
        if rooms_free and intent == "vacancy_summary":
            blocks.append({"type": "table", "columns": ["Room", "Vacant beds", "Gender", "Group"],
                           "rows": [[r.get("room"), vc.summarize(vc.bed_states(r, now, tz))["vacant"], r.get("gender") or "Mixed", r.get("demographic") or "Mixed"] for r in rooms_free[:25]]})
        return _reply(intent, text, blocks)

    if intent in ("upcoming", "checkins"):
        items = []
        for r in scoped:
            for b in vc.bed_states(r, now, tz):
                if intent == "upcoming" and b["status"] in ("occupied", "soon", "temporary") and b["end"]:
                    e = vc.parse_ms(b["end"], True, tz)
                    if e and e > now:
                        items.append((e, ["Room %s" % r.get("room"), b["slot"], vc.fmt(b["end"], tz), "yes" if b["upcoming"] else ""]))
                if intent == "checkins" and b["status"] == "reserved" and (b["reservedFrom"] or b["start"]):
                    v = b["reservedFrom"] or b["start"]
                    items.append((vc.parse_ms(v, False, tz) or 0, ["Room %s" % r.get("room"), b["slot"], vc.fmt(v, tz)]))
        items.sort(key=lambda x: x[0])
        if intent == "upcoming":
            soon = [x for x in items if x[1][3]]
            text = ("Scope %s: %d bed%s will become vacant within %d days.%s" % (label, len(soon), "" if len(soon) == 1 else "s", vc.UPCOMING_DAYS,
                    (" The next check-out is %s, %s on %s." % (items[0][1][0], items[0][1][1], items[0][1][2])) if items else "")
                    if items else "Scope %s: no scheduled check-outs." % label)
            cols = ["Room", "Bed", "Expected check-out", "Within %d days" % vc.UPCOMING_DAYS]
        else:
            text = "Scope %s: %d reserved check-in%s scheduled." % (label, len(items), "" if len(items) == 1 else "s")
            cols = ["Room", "Bed", "Check-in"]
        blocks = [{"type": "table", "columns": cols, "rows": [x[1] for x in items[:30]]}] if items else []
        blocks.append({"type": "note", "text": "Dates come from the dormitory's records. Upcoming vacancies stay occupied until the tenant actually checks out."})
        return _reply(intent, text, blocks)

    if intent == "compare":
        dim = "demographic" if re.search(r"\b(students?|reviewees?|group)\b", tn) and not re.search(r"\b(male|female)\b", tn) else "gender"
        cats = ["Male", "Female", "Mixed"] if dim == "gender" else ["Students", "Reviewees", "Mixed"]
        rows = []
        for c in cats:
            fc = dict({k: v for k, v in base_filters.items() if k != dim}, **{dim: c})
            s = vc.stats(rooms, fc, now, tz)
            if s["total"]:
                rows.append([c, s["total"], s["occupied"], s["vacant"], s["upcoming"], _p(s["occupancyRate"])])
        if not rows:
            return _reply("compare", "There are no beds in those categories.")
        most = max(rows, key=lambda r: r[3])
        text = "By %s: %s has the most vacant beds (%d)." % ("gender" if dim == "gender" else "resident group", most[0], most[3])
        return _reply("compare", text, [{"type": "table", "columns": ["Category", "Beds", "Occupied", "Vacant", "Upcoming", "Occupancy"], "rows": rows},
                                        {"type": "note", "text": "Each category uses only its own beds, so the percentages use the right capacity."}])

    if intent == "highest":
        rows = sorted(([r.get("room"), vc.summarize(vc.bed_states(r, now, tz))] for r in scoped), key=lambda x: (-x[1]["vacant"], str(x[0])))
        rows = [x for x in rows if x[1]["total"]]
        if not rows or not rows[0][1]["vacant"]:
            return _reply("highest", "Scope %s: no room has a vacant bed right now." % label)
        top = rows[0]
        return _reply("highest", "Room %s has the most vacant beds (%d of %d), scope %s." % (top[0], top[1]["vacant"], top[1]["total"], label),
                      [{"type": "table", "columns": ["Room", "Vacant", "Beds", "Upcoming"], "rows": [[r[0], r[1]["vacant"], r[1]["total"], r[1]["upcoming"]] for r in rows[:15]]}])

    if intent == "report":
        rows = []
        for r in scoped:
            s = vc.summarize(vc.bed_states(r, now, tz))
            rows.append([r.get("room"), s["total"], s["occupied"], s["vacant"], s["upcoming"], s["reserved"]])
        rows.sort(key=lambda x: (-x[3], str(x[0])))
        findings = []
        full = [str(x[0]) for x in rows if x[1] and not x[3]]
        if full:
            findings.append("Full rooms: " + ", ".join(full[:10]))
        if st["upcoming"]:
            findings.append("%d bed%s will free up within %d days." % (st["upcoming"], "" if st["upcoming"] == 1 else "s", vc.UPCOMING_DAYS))
        if st["overdue"]:
            findings.append("%d bed%s past the check-out date (still counted as occupied)." % (st["overdue"], " is" if st["overdue"] == 1 else "s are"))
        text = "Vacancy report (%s): %d of %d beds vacant, %s occupancy." % (label, st["vacant"], st["total"], _p(st["occupancyRate"]))
        return _reply("report", text, [{"type": "heading", "text": "Vacancy report · " + label},
                                       {"type": "list", "items": stat_lines(st)},
                                       {"type": "table", "columns": ["Room", "Beds", "Occupied", "Vacant", "Upcoming", "Reserved"], "rows": rows[:40]}]
                      + ([{"type": "subheading", "text": "Findings"}, {"type": "list", "items": findings}] if findings else []))

    if intent == "trend":
        days = []
        for d in (0, 7, 14, 30):
            t = now + d * vc.DAY_MS
            occ = sum(1 for r in scoped for b in (r.get("bedInfo") or r.get("beds") or []) if isinstance(b, dict) and _occupied_at(b, t, now, tz))
            days.append(["Today" if d == 0 else "In %d days" % d, occ, st["total"] - occ])
        text = ("From the scheduled dates (scope %s): occupied beds go from %d today to %d in 30 days, as contracts end and "
                "reservations start." % (label, days[0][1], days[-1][1]))
        return _reply("trend", text, [{"type": "table", "columns": ["When", "Occupied (scheduled)", "Free"], "rows": days},
                                      {"type": "note", "text": ("Confirmed by the records: check-out and reservation dates. Not known: renewals, "
                                                                "late check-outs or new bookings, so the real numbers may differ."
                                                                + (" Past history is not shared with viewers." if who == "viewer" else ""))}])

    if intent == "explain":
        return _reply("explain", "How the numbers work (scope %s):" % label, [{"type": "list", "items": [
            "Vacant (green): nobody is in the bed and it is not reserved.",
            "Occupied (blue): a tenant is in the bed. Checkout ≤48h (amber) and Temporary occupied (brown) are occupied too.",
            "Overdue (red): the check-out date has passed but the tenant has not been checked out yet — still occupied.",
            "Reserved (purple): held for a client who has not arrived.",
            "Upcoming vacancy (dashed green outline): an occupied bed whose check-out is within %d days. It is NOT counted as vacant." % vc.UPCOMING_DAYS,
            "Occupancy rate = occupied ÷ total beds in the selected scope; vacancy rate = vacant ÷ total beds.",
        ] + stat_lines(st)}])
    return None


def _occupied_at(b, t, now, tz):
    if b.get("tenant"):
        start, end = vc.parse_ms(b.get("start"), False, tz), vc.parse_ms(b.get("end"), True, tz)
        if end is not None and end < now:
            return True
        return (start is None or start <= t) and (end is None or end > t)
    if b.get("reservedFor"):
        f = vc.parse_ms(b.get("reservedFrom"), False, tz)
        return f is not None and f <= t
    return False


# --------------------------------------------------------------------------- viewer page
NAV = re.compile(r"\b(open|go to|goto|take me|show|switch to|navigate|jump to|bring up|view)\b")
PRIVATE = re.compile(r"\b(name|names|who (is|are|lives|stays)|tenant'?s? (name|number|phone|contact)|phone|contact|email|address|emergency|photo|picture)\b")
CHANGES = re.compile(r"\b(check ?out|checkout|check in|checkin|add|delete|remove|update|edit|change|move|transfer|reserve|book|cancel|assign)\b.*\b(tenant|room|bed|reservation|contact|number|client|guest)\b")


def handle_viewer(conn, uid, raw, tn, ctx, mem_format=None):
    code = ctx.get("code")
    if not isinstance(code, str) or not re.match(r"^[a-z0-9-]{4,30}$", code):
        return _reply("clarify", "Open a dormitory first (enter its code and password), then ask me about its vacancy.")
    now, tz = clock(ctx)
    cur = conn.cursor()
    from datetime import datetime, timezone
    rc = Ctx(cur, uid, datetime.now(timezone.utc))
    if not _viewer_visible(rc, code):                       # same permission check as the page itself
        return _reply("denied", "You don't have viewer access to this dormitory (any more), so I can't read it.")
    rooms = sorted([dict(doc, id=i) for i, doc, _v in list_docs(cur, KINDS["dorm_vacancy"], [code], limit=2000)],
                   key=lambda r: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", str(r.get("room") or ""))])
    base = clean_filters(ctx.get("filters"))
    ctx_room = ctx.get("roomId") if isinstance(ctx.get("roomId"), str) else None

    # read-only and private: refuse clearly, never guess
    if PRIVATE.search(tn) and re.search(r"\b(tenant|resident|who|person|people|occupant|guest|client|name)\b", tn):
        return _reply("privacy", "Viewers never see who lives in a bed: names, photos, contact numbers and emergency contacts are "
                      "not shared with this page at all. I can tell you each bed's status and its check-in / check-out dates.")
    if CHANGES.search(tn) or re.search(r"\b(can i|how (do|can) i|want to|i would like to|pwede)\b.*\b(reserve|book|rent|apply)\b", tn):
        if re.search(r"\b(reserve|book|rent|apply)\b", tn):
            return _reply("read_only", "Viewers can't reserve here: this page is read-only. Contact the dormitory (whoever gave you the dorm "
                          "code) to reserve. I can show which beds are vacant now and which free up soon, so you know what to ask for.",
                          suggestions=["Which beds are vacant?", "Show upcoming vacancies"])
        return _reply("read_only", "This is a read-only Dormitory Viewer account, so I can't change rooms, beds, tenants or "
                      "reservations. The dormitory's Branch Admin can do that.")
    # several filters at once: bedspace / whole room and floor narrow the rooms (gender and group are handled below)
    note = []
    mode = "Whole Room" if re.search(r"\bwhole[- ]?room|\bentire room|\bprivate room\b", tn) else "Bedspace" if re.search(r"\bbed ?spac\w*", tn) else None
    fm = re.search(r"\b(ground|first|second|third|fourth|fifth|1st|2nd|3rd|4th)\s+floor\b|\bfloor\s*(\d)\b", tn)
    if mode:
        rooms = [r for r in rooms if (r.get("tenancyMode") or "Bedspace") == mode]
        note.append(mode.lower() + " rooms")
    if fm:
        word = fm.group(1) or fm.group(2)
        num = {"ground": "0", "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "1st": "1", "2nd": "2", "3rd": "3", "4th": "4"}.get(word, word)
        alias = {"0": "ground", "1": "first", "2": "second", "3": "third", "4": "fourth", "5": "fifth"}.get(num, num)
        named = [r for r in rooms if r.get("floor")]
        if not named:
            return _reply("floors_none", "This dormitory hasn't set up floors, so I can't tell which rooms are on the %s floor." % alias)
        rooms = [r for r in rooms if re.search(r"\b(%s|%s)\b|\b%s(st|nd|rd|th)?\b" % (alias, word, num), str(r.get("floor")).lower())]
        note.append("%s floor" % alias)
    if note and not rooms:
        return _reply("vacancy_summary", "There are no %s in this dormitory." % " on the ".join(note))
    # who / which beds check out on a day (beds and dates only, never names)
    if re.search(r"\b(check(s|ed|ing)? ?outs?|leav\w*|move out|vacate)\b", tn) and re.search(r"\b(today|tomorrow|this week|next week|this weekend)\b", tn):
        day0 = vc.parse_ms(time.strftime("%Y-%m-%d", time.gmtime((now - tz * 60000) / 1000)), False, tz) or now
        span = {"today": (0, 1), "tomorrow": (1, 2), "this week": (0, 7), "next week": (7, 14), "this weekend": (0, 7)}
        key = next(k for k in span if re.search(r"\b%s\b" % k, tn))
        a, b = day0 + span[key][0] * vc.DAY_MS, day0 + span[key][1] * vc.DAY_MS
        rows = []
        for r in rooms:
            for bd in vc.bed_states(r, now, tz):
                e = vc.parse_ms(bd["end"], True, tz) if bd.get("end") else None
                if e and a <= e < b and bd["status"] in ("occupied", "soon", "temporary", "overdue"):
                    rows.append(["Room %s" % r.get("room"), bd["slot"], vc.fmt(bd["end"], tz)])
        text = ("%d bed%s check%s out %s: %s." % (len(rows), "" if len(rows) == 1 else "s", "s" if len(rows) == 1 else "", key, ", ".join("%s %s" % (x[0], x[1]) for x in rows[:10]))
                if rows else "No bed is scheduled to check out %s." % key)
        return _reply("upcoming", text + " (Who the tenants are stays private.)", [{"type": "table", "columns": ["Room", "Bed", "Check-out"], "rows": rows}] if rows else [])
    if re.search(r"\b(fully (occupied|booked)|full rooms?|rooms? (are |that are )?(already )?full|no vacan\w*)\b", tn):
        full = [r for r in rooms if vc.summarize(vc.bed_states(r, now, tz))["vacant"] == 0 and vc.summarize(vc.bed_states(r, now, tz))["total"]]
        return _reply("rooms_full", ("%d room%s fully occupied: %s." % (len(full), " is" if len(full) == 1 else "s are", ", ".join(str(r.get("room")) for r in full)))
                      if full else "No room is fully occupied right now.")
    if re.search(r"\b(when|next)\b.*\b(available|vacant|free)\b|\bnext (available|vacant|free) bed\b", tn) and not re.search(r"\bnext (week|month)\b", tn):
        soon = sorted([(vc.parse_ms(bd["end"], True, tz), r.get("room"), bd["slot"], bd["end"]) for r in rooms for bd in vc.bed_states(r, now, tz)
                       if bd.get("end") and bd["status"] in ("occupied", "soon", "temporary") and (vc.parse_ms(bd["end"], True, tz) or 0) > now], key=lambda x: x[0])
        vac_now = sum(vc.summarize(vc.bed_states(r, now, tz))["vacant"] for r in rooms)
        if vac_now and not re.search(r"\bnext\b", tn):
            return _reply("vacancy_summary", "%d bed%s vacant right now, so you don't need to wait." % (vac_now, " is" if vac_now == 1 else "s are"))
        if not soon:
            return _reply("upcoming", "No check-out dates are scheduled, so I can't say when the next bed frees up.")
        return _reply("upcoming", "The next bed should free up after %s (Room %s, %s)%s." % (vc.fmt(soon[0][3], tz), soon[0][1], soon[0][2],
                      ("; %d bed%s vacant now" % (vac_now, " is" if vac_now == 1 else "s are")) if vac_now else ""))
    # navigation
    room, asked = room_ref(tn, rooms, None)
    if asked and not room and not re.search(r"\b(status|information|info|card|cards|for)\b", asked):
        return _reply("room_missing", "I couldn't find Room %s in this dormitory. Rooms: %s." % (asked.upper(), ", ".join(str(r.get("room")) for r in rooms[:15])))
    # vacancy on a later date ("next month", "for December", "from Dec 1")
    if re.search(r"\b(vacan\w*|available|free|open)\b", tn) and re.search(r"\b(next (week|month)|from|starting|on|by|for) ?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d|next|tomorrow)\w*", tn):
        import smart
        from datetime import datetime as _dt, timedelta as _td
        local_today = _dt.utcfromtimestamp((now - tz * 60000) / 1000).date()
        start = None
        if re.search(r"\bnext week\b", tn):
            start = local_today + _td(days=7 - local_today.weekday())
        elif re.search(r"\bnext month\b", tn):
            y, mo = (local_today.year + 1, 1) if local_today.month == 12 else (local_today.year, local_today.month + 1)
            start = local_today.replace(year=y, month=mo, day=1)
        else:
            mm = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b(?!\s*\d)", tn)
            ds = smart.find_dates(tn, local_today)
            if ds:
                start = ds[0][1]
            elif mm:
                mo = smart.MONTHS[mm.group(1)]
                start = local_today.replace(year=local_today.year + (1 if mo < local_today.month else 0), month=mo, day=1)
        if start and start > local_today:
            st_ms = vc.parse_ms(start.isoformat(), False, tz)
            rows = []
            f = scope_from_text(tn, base)
            for r in rooms:
                if not vc.room_matches(r, f):
                    continue
                free = []
                for bd in vc.bed_states(r, now, tz):
                    e = vc.parse_ms(bd["end"], True, tz) if bd.get("end") else None
                    if bd["status"] == "vacant" or (bd["status"] in ("occupied", "soon", "temporary", "overdue") and e and e <= st_ms + 14 * 3600000 and e > now):
                        free.append(bd["slot"])
                if free:
                    rows.append(["Room %s" % r.get("room"), len(free), ", ".join(free), r.get("gender") or "Mixed", r.get("demographic") or "Mixed"])
            n = sum(x[1] for x in rows)
            label = vc.scope_label(f, rooms)
            when = start.strftime("%B %d, %Y").replace(" 0", " ")
            if not rows:
                return _reply("vacancy_summary", "Scope %s: no bed is expected to be free by %s." % (label, when))
            return _reply("vacancy_summary", "Scope %s: about %d bed%s should be free by %s, in %d room%s." % (label, n, "" if n == 1 else "s", when, len(rows), "" if len(rows) == 1 else "s"),
                          [{"type": "table", "columns": ["Room", "Free beds", "Beds", "Gender", "Group"], "rows": rows[:30]},
                           {"type": "note", "text": "Counts beds that are vacant now plus beds whose tenant checks out before then. Reserved beds and new bookings are not included; ask the dormitory to confirm."}])
    if NAV.search(tn) or re.match(r"^(hallway|analytics|vacancies)\b", tn):
        if room:
            return _reply("nav_room", "Showing Room %s on the hallway map." % room.get("room"), nav={"view": "hallway", "roomId": room.get("id")})
        if asked:
            return _reply("room_missing", "I couldn't find Room %s here. Rooms: %s." % (asked.upper(), ", ".join(str(r.get("room")) for r in rooms[:15])))
        for v in ("hallway", "analytics", "vacancies"):
            if re.search(r"\b%s\b" % ("vacancies|vacancy list|room cards|cards|list" if v == "vacancies" else v), tn):
                return _reply("nav_view", "Opening %s." % VIEWS[v], nav={"view": v})
        g = [GENDERS[w] for w in ("male", "female", "mixed") if re.search(r"\b%s\b" % w, tn)]
        if g and re.search(r"\b(rooms?|beds?|only)\b", tn):
            return _reply("nav_filter", "Showing %s rooms only. Every statistic now uses those beds." % g[0], nav={"filters": {"gender": g[0]}})
    # rooms, not beds: "how many male rooms", "how many rooms are there", "what is the biggest room"
    if re.search(r"\bhow many\b.*\brooms?\b|\bnumber of rooms\b", tn) and not re.search(r"\b(vacan\w*|free|available|empty|full|occupied|beds?)\b", tn):
        f = scope_from_text(tn, base)
        pick = [r for r in rooms if vc.room_matches(r, f)]
        label = vc.scope_label(f, rooms)
        text = "Scope %s: %d room%s: %s." % (label, len(pick), "" if len(pick) == 1 else "s", ", ".join(str(r.get("room")) for r in pick[:25]))
        return _reply("rooms_count", text, [{"type": "table", "columns": ["Room", "Beds", "Gender", "Group"],
                                             "rows": [[r.get("room"), vc.summarize(vc.bed_states(r, now, tz))["total"], r.get("gender") or "Mixed",
                                                       r.get("demographic") or "Mixed"] for r in pick[:40]]}])
    big = re.search(r"\b(biggest|largest|most beds)\b", tn)
    small = re.search(r"\b(smallest|fewest beds|least beds)\b", tn)
    if (big or small) and re.search(r"\brooms?\b", tn) and not re.search(r"\b(vacan\w*|free|occupied)\b", tn) and rooms:
        sized = sorted(rooms, key=lambda r: vc.summarize(vc.bed_states(r, now, tz))["total"], reverse=bool(big))
        n = vc.summarize(vc.bed_states(sized[0], now, tz))["total"]
        top = [r for r in sized if vc.summarize(vc.bed_states(r, now, tz))["total"] == n]
        word = "biggest" if big else "smallest"
        names = ", ".join("Room %s" % r.get("room") for r in top[:12])
        return _reply("room_size", ("%s is the %s room, with %d beds." % (names, word, n)) if len(top) == 1 else
                      "%d rooms are the %s, with %d beds each: %s." % (len(top), word, n, names))
    # intents: rules first, then the trained classifier
    intent = None
    if re.search(r"\bwhy\b|\btrend\b|\bforecast\b|\bwill (it|vacancy|occupancy)\b|\bnext month\b", tn):
        intent = "trend"
    elif re.search(r"\bcompare\b|\bvs\b|\bversus\b|\bdifference\b", tn):
        intent = "compare"
    elif re.search(r"\breport\b|\bsummary\b|\boverview\b", tn):
        intent = "report"
    elif re.search(r"\breserv\w*\b", tn) and not re.search(r"\b(vacant|available|free)\b", tn):
        intent = "checkins"
    elif re.search(r"\bcompare\b.*\blast (month|year|week)\b|\b(history|last month|previous month)\b", tn):
        return _reply("trend", "Past history isn't shared with viewers, so I can't compare with last month. I can show what the scheduled "
                      "dates say about the coming weeks — ask: how will vacancy change?")
    elif re.search(r"^how many( all| total)?\??$|\bhow many (in )?total\b", tn):
        intent = "vacancy_summary"
    elif re.search(r"\bupcoming\b|\bcheck ?outs?\b|\bbecome vacant\b|\bfree up\b|\bleaving\b|\bexpir\w*\b", tn):
        intent = "upcoming"
    elif re.search(r"\bcheckin\b|\breservations?\b|\breserved\b", tn) and not re.search(r"\b(vacant|available|free)\b", tn):
        intent = "checkins"
    elif room or (ctx_room and re.search(r"\b(this|selected) room\b|\boccupancy status\b", tn)):
        intent = "room_status"
    elif re.search(r"\b(explain|mean|meaning|legend|colou?rs?|calculated)\b", tn):
        intent = "explain"
    elif re.search(r"\b(most|highest|best|emptiest)\b", tn):
        intent = "highest"
    elif re.search(r"\bvacant\b|\bvacancy\b|\bspace\b|\bavailable\b|\bleft\b", tn):
        intent = "vacancy_summary"
    elif re.search(r"\boccupied\b|\boccupancy\b|\bfull\b|\bhow many (tenants?|people|residents?|boarders?)\b", tn):
        intent = "occupancy_summary"
    if not intent:
        intent, _score = agent_nlu.classify(raw, VIEWER_INTENTS)
    if intent == "admin_only":
        return _reply("read_only", "That's an administrator task (or private information). As a viewer I can show bed statuses, "
                      "dates and statistics, but not change anything or show who lives there.")
    if intent in ("nav_hallway", "nav_analytics", "nav_vacancies"):
        v = intent[4:]
        return _reply("nav_view", "Opening %s." % VIEWS[v], nav={"view": v})
    if intent == "help" or intent is None:
        return _reply("help" if intent else "unknown",
                      ("I'm not sure what you mean. " if intent is None else "") +
                      "On this page I can: count vacant/occupied beds (also for male, female, students…), list upcoming "
                      "vacancies and reserved check-ins, show a room's beds, compare categories, make a vacancy report, "
                      "explain the colours, and open the Hallway, Vacancies or Analytics view.",
                      suggestions=["How many beds are vacant?", "Show upcoming vacancies", "Compare male and female rooms"])
    if intent == "memory_show":
        return None
    out = answer_scope(intent, tn, rooms, base, now, tz, "viewer", ctx_room)
    if out and note:
        out["response"] = out["response"].replace("Scope ", "Scope %s, " % " on the ".join(note), 1) if "Scope " in out["response"] else \
            "%s: %s" % (" on the ".join(note).capitalize(), out["response"])
    return out or _reply("help", "I can count vacant beds, list upcoming vacancies, show a room or make a report.")


# --------------------------------------------------------------------------- directory page
DIR_KEYS = {"male": "maleVacant", "female": "femaleVacant", "mixed": "mixedVacant", "students": "studentVacant",
            "student": "studentVacant", "reviewees": "revieweeVacant", "reviewee": "revieweeVacant", "aircon": "acVacant", "ac": "acVacant"}
DIR_FILTER = {"maleVacant": "male", "femaleVacant": "female", "mixedVacant": "mixed", "studentVacant": "student",
              "revieweeVacant": "reviewee", "acVacant": "ac", "vacant": "vac"}


def handle_directory(conn, uid, raw, tn, ctx):
    cur = conn.cursor()
    items = [dict(doc, id=i) for i, doc, _v in list_docs(cur, KINDS["directory"], [], limit=500)]
    if not items:
        return _reply("empty", "No dormitory is listed in the directory yet.")
    want = [v for k, v in DIR_KEYS.items() if re.search(r"\b%s\b" % k, tn)]
    key = want[0] if len(set(want)) == 1 else "vacant"
    cat = {"vacant": "", "maleVacant": " for male residents", "femaleVacant": " for female residents", "mixedVacant": " in mixed rooms",
           "studentVacant": " for students", "revieweeVacant": " for reviewees", "acVacant": " in air-conditioned rooms"}[key]
    if CHANGES.search(tn) or (PRIVATE.search(tn) and re.search(r"\b(tenant|resident|who|name)\b", tn)):
        return _reply("read_only", "The directory is read-only and shows vacancy counts only — no resident details.")
    m = re.search(r"\b(?:in|near|at|around)\s+([a-z][a-z .-]{2,40})$", tn)
    if NAV.search(tn) or re.search(r"\b(find|search|filter|look for)\b", tn):
        nav = {"filter": DIR_FILTER.get(key, "all") if key != "vacant" else ("vac" if re.search(r"\bvacan", tn) else "all")}
        if m:
            nav["search"] = m.group(1).strip()
        if re.search(r"\b(vacan\w*|available|free)\b", tn) and nav["filter"] == "all":
            nav["filter"] = "vac"
        hit = sorted([x for x in items if int(x.get(key) or 0) > 0 and (not m or m.group(1).strip() in ((x.get("dormName") or "") + " " + (x.get("location") or "")).lower())],
                     key=lambda x: -int(x.get(key) or 0))
        if nav["filter"] == "all" and not m:
            return _reply("nav_filter", "Showing every dormitory in the directory (%d)." % len(items), nav=nav)
        report = ("Report: %d of %d dormitor%s vacant beds%s — %s." % (len(hit), len(items), "y has" if len(hit) == 1 else "ies have", cat,
                  "; ".join("%s (%d)" % (x.get("dormName"), int(x.get(key) or 0)) for x in hit[:8]))) if hit else "Report: no dormitory matches right now."
        return _reply("nav_filter", "Done: the list now shows only dormitories with vacant beds%s%s. %s" % (cat, (" in " + m.group(1).strip()) if m else "", report), nav=nav,
                      suggestions=["Clear the filters", "Which dorm has the most vacant beds?"])
    rows = sorted(([x.get("dormName") or "Dormitory", x.get("location") or "", int(x.get(key) or 0), int(x.get("vacant") or 0), int(x.get("total") or 0)]
                   for x in items), key=lambda r: (-r[2], r[0]))
    total_v, total_b = sum(r[3] for r in rows), sum(r[4] for r in rows)
    table = {"type": "table", "columns": ["Dormitory", "Location", "Vacant%s" % cat, "All vacant", "Beds"], "rows": rows[:30]}
    if re.search(r"\b(most|highest|best|which|where|emptiest)\b", tn):
        if not rows[0][2]:
            return _reply("highest", "No listed dormitory has vacant beds%s right now." % cat, [table])
        return _reply("highest", "%s has the most vacant beds%s: %d%s." % (rows[0][0], cat, rows[0][2], (" (" + rows[0][1] + ")") if rows[0][1] else ""), [table],
                      nav={"filter": DIR_FILTER.get(key, "vac")})
    s = sum(r[2] for r in rows)
    return _reply("vacancy_summary", "Across %d listed dormitories: %d vacant bed%s%s (%d vacant of %d beds overall)." %
                  (len(rows), s, "" if s == 1 else "s", cat, total_v, total_b), [table,
                  {"type": "note", "text": "Counts are what each dormitory last published to the directory."}])
