"""Python copy of vacancy-core.js, so the assistant gives exactly the numbers the pages show.

Statuses: vacant, occupied, reserved, temporary, overdue, soon (checkout within 48 h).
Upcoming vacancy = an occupied bed (occupied / soon / temporary) whose expected check-out is within the next
UPCOMING_DAYS days. It is still counted as occupied, never as vacant.

Times: dates written without a time ("2026-11-20") are read in the BROWSER's time zone, like the pages do.
The browser sends its offset (Date.getTimezoneOffset(), minutes) and its clock with every question.
"""
import re
from datetime import datetime, timedelta, timezone

DAY_MS = 86400000
UPCOMING_DAYS = 7
LABEL = {"vacant": "Vacant", "occupied": "Occupied", "reserved": "Reserved", "temporary": "Temporary occupied",
         "overdue": "Overdue", "soon": "Checkout ≤48h"}
OCCUPIED = ("occupied", "soon", "temporary", "overdue")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_ms(value, is_end=False, tz_min=0):
    """Same rules as parseScheduleDate(): a bare date is local midnight (or 23:59:59 for an end date)."""
    if not value:
        return None
    text = str(value).strip()
    try:
        if _DATE.match(text):
            naive = datetime.fromisoformat(text + ("T23:59:59" if is_end else "T00:00:00"))
        else:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo:
                return int(dt.timestamp() * 1000)
            naive = dt
    except ValueError:
        return None
    return int(naive.replace(tzinfo=timezone.utc).timestamp() * 1000) + int(tz_min) * 60000


def fmt(value, tz_min=0):
    ms = parse_ms(value, False, tz_min)
    if ms is None:
        return ""
    local = datetime.fromtimestamp((ms - int(tz_min) * 60000) / 1000, tz=timezone.utc)
    day = local.strftime("%B %d, %Y").replace(" 0", " ")
    if _DATE.match(str(value)):
        return day
    return day + " at " + local.strftime("%I:%M %p").lstrip("0")


def bed_status(bed, room, now, tz_min=0):
    start, end = parse_ms(bed.get("start"), False, tz_min), parse_ms(bed.get("end"), True, tz_min)
    if room and room.get("tenancyMode") == "Whole Room" and not bed.get("tenant"):
        beds = room.get("beds") or []
        if any(b.get("tenant") and bed_status(b, None, now, tz_min) != "reserved" for b in beds):
            return "occupied"
        if any(b.get("reservedFor") or (b.get("tenant") and bed_status(b, None, now, tz_min) == "reserved") for b in beds):
            return "reserved"
    if not bed.get("tenant"):
        return "reserved" if bed.get("reservedFor") else "vacant"
    if end is not None and end < now:
        return "overdue"
    if start is not None and start > now:
        return "reserved"
    if bed.get("residentType") == "Temporary":
        return "temporary"
    if end is not None and end - now <= 48 * 3600000:
        return "soon"
    return "occupied"


def is_upcoming(bed, room, now, tz_min=0, days=UPCOMING_DAYS):
    if bed_status(bed, room, now, tz_min) not in ("occupied", "soon", "temporary"):
        return False
    end = parse_ms(bed.get("end"), True, tz_min)
    return end is not None and now < end <= now + days * DAY_MS


def bed_states(room, now, tz_min=0):
    """room = a published (name-free) viewer room, or an admin room (beds with names; names are dropped)."""
    info = room.get("bedInfo")
    if not (isinstance(info, list) and info):
        info = None
    beds = info if info is not None else (room.get("beds") if isinstance(room.get("beds"), list) and room.get("beds")
                                           and isinstance(room["beds"][0], dict) else None)
    if beds is None:                                   # oldest published copies: a status string per bed
        return [{"slot": "Bed %d" % (i + 1), "status": st if st in LABEL else "vacant", "start": None, "end": None,
                 "reservedFrom": None, "upcoming": False} for i, st in enumerate(room.get("beds") or [])]
    r = {"tenancyMode": room.get("tenancyMode"), "beds": beds}
    out = []
    for i, b in enumerate(beds):
        st = bed_status(b, r, now, tz_min)
        out.append({"slot": b.get("slot") or "Bed %d" % (i + 1), "status": st,
                    "start": b.get("start") if b.get("tenant") else None, "end": b.get("end") if b.get("tenant") else None,
                    "reservedFrom": b.get("reservedFrom"), "upcoming": is_upcoming(b, r, now, tz_min)})
    return out


def summarize(states):
    c = {"total": 0, "occupied": 0, "vacant": 0, "reserved": 0, "upcoming": 0, "overdue": 0, "temporary": 0, "soon": 0}
    for b in states:
        c["total"] += 1
        if b["status"] == "vacant":
            c["vacant"] += 1
        elif b["status"] == "reserved":
            c["reserved"] += 1
        else:
            c["occupied"] += 1
        for k in ("overdue", "temporary", "soon"):
            if b["status"] == k:
                c[k] += 1
        if b["upcoming"]:
            c["upcoming"] += 1
    return c


def room_matches(room, f):
    f = f or {}
    g = f.get("gender") or "all"
    if g != "all" and (room.get("gender") or "Mixed") != g:
        return False
    d = f.get("demographic") or "all"
    if d != "all":
        rd = room.get("demographic") or "Mixed"
        if d == "Mixed" and rd in ("Students", "Reviewees"):
            return False
        if d != "Mixed" and rd != d:
            return False
    if (f.get("room") or "all") != "all" and room.get("id") != f.get("room"):
        return False
    if f.get("search") and str(f["search"]).lower() not in str(room.get("room") or "").lower():
        return False
    return True


def stats(rooms, f, now, tz_min=0):
    c = {"total": 0, "occupied": 0, "vacant": 0, "reserved": 0, "upcoming": 0, "overdue": 0, "temporary": 0, "soon": 0}
    n = with_space = 0
    for room in rooms:
        if not room_matches(room, f):
            continue
        s = summarize(bed_states(room, now, tz_min))
        st = (f or {}).get("status") or "all"
        if (st == "vacant" and not s["vacant"]) or (st == "full" and s["vacant"]) or (st == "upcoming" and not s["upcoming"]):
            continue
        n += 1
        with_space += 1 if s["vacant"] else 0
        for k in c:
            c[k] += s[k]
    c.update(rooms=n, roomsWithSpace=with_space,
             occupancyRate=(c["occupied"] / c["total"] * 100) if c["total"] else 0.0,
             vacancyRate=(c["vacant"] / c["total"] * 100) if c["total"] else 0.0)
    return c


def scope_label(f, rooms=()):
    f = f or {}
    parts = []
    if (f.get("gender") or "all") != "all":
        parts.append({"Male": "Male", "Female": "Female", "Mixed": "Mixed gender"}.get(f["gender"], f["gender"]))
    if (f.get("demographic") or "all") != "all":
        parts.append("Mixed groups" if f["demographic"] == "Mixed" else f["demographic"])
    if (f.get("room") or "all") != "all":
        r = next((x for x in rooms if x.get("id") == f["room"]), None)
        parts.append("Room %s" % (r.get("room") if r else f["room"]))
    if (f.get("status") or "all") != "all":
        parts.append({"vacant": "Rooms with vacancy", "full": "Full rooms", "upcoming": "Rooms with upcoming vacancy"}.get(f["status"], f["status"]))
    if f.get("search"):
        parts.append('"%s"' % f["search"])
    return " · ".join(parts) if parts else "All"
