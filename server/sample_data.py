"""Sample rooms and tenants for the local test account "sample.one" (local test mode only).

Run automatically by run_local.py, or by hand:  python server/sample_data.py
  * Adds rooms until the account has at least 24 (named S-101, S-102 ...). Existing rooms are never changed.
  * Every bed is filled at random: tenants (with Tenant Information and a contact number), check-in / check-out
    dates around today, a few past-due, a few leaving soon, some vacant beds, a few reservations and a small
    Tenant History, so every screen (canvas, viewer, analytics, assistant) has something to show.
  * The names are invented sample data. Delete the rooms in the app if you no longer want them.
"""
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from store import KINDS, list_docs, new_id, write  # noqa: E402

FIRST_M = "Juan Mark Paolo Carlo Miguel Rafael Jose Luis Gabriel Enzo Andrei Kenneth Joshua Christian Adrian Nathan".split()
FIRST_F = "Maria Ana Liza Camille Bea Nicole Andrea Patricia Kristine Joy Angela Sofia Bianca Hannah Trisha Mae".split()
LAST = ("Santos Reyes Cruz Bautista Garcia Mendoza Torres Flores Ramos Villanueva Castillo Aquino Navarro Dela Cruz "
        "Fernandez Gonzales Lopez Morales Rivera Domingo Pascual Salazar Soriano Mercado").split()
CITIES = ["Quezon City", "Manila", "Cebu City", "Davao City", "Iloilo City", "Baguio", "Cagayan de Oro", "Bacolod"]
TARGET = 24


def _name(gender, rng, used):
    for _ in range(100):
        n = "%s %s" % (rng.choice(FIRST_M if gender == "Male" else FIRST_F), rng.choice(LAST))
        if n not in used:
            used.add(n)
            return n
    return "%s %d" % (rng.choice(LAST), len(used))


def _phone(rng):
    return "09" + "".join(str(rng.randint(0, 9)) for _ in range(9))


def seed(cur, uid, rng=None, today=None):
    rng = rng or random.Random()
    today = today or datetime.now().date()
    now = datetime.now(timezone.utc)
    existing = [doc for _i, doc, _v in list_docs(cur, KINDS["rooms"], [uid], limit=5000)]
    names = {str(d.get("room")) for d in existing}
    need = TARGET - len(existing)
    if need <= 0:
        return 0
    used, made, n = set(), 0, 100
    day = lambda k: (today + timedelta(days=k)).isoformat()
    while made < need:
        n += 1
        label = "S-%d" % n
        if label in names:
            continue
        gender = rng.choice(["Male", "Female", "Male", "Female", "Mixed"])
        demographic = rng.choice(["Students", "Students", "Reviewees", "Mixed"])
        cap = rng.choice([2, 3, 4, 4, 6])
        rid = new_id()
        beds = []
        for b in range(cap):
            slot = "Bed %d" % (b + 1)
            roll = rng.random()
            if roll < 0.22:                                   # vacant
                beds.append({"slot": slot, "tenant": None})
                continue
            g = gender if gender != "Mixed" else rng.choice(["Male", "Female"])
            who = _name(g, rng, used)
            rtype = "Reviewee" if demographic == "Reviewees" else "Student" if demographic == "Students" else rng.choice(["Student", "Reviewee"])
            if roll < 0.30:                                   # past check-out (overdue)
                start, end = day(-rng.randint(60, 150)), day(-rng.randint(1, 5))
            elif roll < 0.45:                                 # leaving within a week (upcoming vacancy), with a time
                start, end = day(-rng.randint(20, 120)), day(rng.randint(0, 7)) + "T%02d:00" % rng.choice([9, 10, 11, 12])
            else:
                start, end = day(-rng.randint(5, 200)), day(rng.randint(8, 240))
            tid = new_id()
            write(cur, KINDS["tenants"], (uid, tid), {
                "name": who, "contact": _phone(rng), "address": "%d %s St., %s" % (rng.randint(1, 999), rng.choice(LAST), rng.choice(CITIES)),
                "ec1": {"name": _name(rng.choice(["Male", "Female"]), rng, used), "phone": _phone(rng), "relation": rng.choice(["Father", "Mother", "Guardian", "Sibling"])},
                "ec2": None, "photoVersion": None}, now, lenient=True)
            beds.append({"slot": slot, "tenant": who, "tenantId": tid, "start": start, "end": end,
                         "residentType": rtype, "residentGender": g})
        # one reservation on a vacant bed in about a third of the rooms
        free = [i for i, b in enumerate(beds) if not b.get("tenant")]
        if free and rng.random() < 0.35:
            i = free[0]
            g = gender if gender != "Mixed" else rng.choice(["Male", "Female"])
            pid = new_id()
            write(cur, KINDS["prospects"], (uid, pid), {
                "name": _name(g, rng, used), "gender": g, "demographic": "Reviewee" if demographic == "Reviewees" else "Student",
                "checkIn": day(rng.randint(2, 20)) + "T14:00", "checkOut": day(rng.randint(60, 180)), "notes": "Sample reservation",
                "reservedBed": {"roomId": rid, "slot": beds[i]["slot"]}, "desiredBed": None}, now, lenient=True)
            beds[i]["reservedFor"] = pid
        col, row = made % 6, made // 6
        write(cur, KINDS["rooms"], (uid, rid), {
            "room": label, "type": "Room", "capacity": cap, "gender": gender, "demographic": demographic, "tenancyMode": "Bedspace",
            "ac": rng.random() < 0.4, "x": 30 + col * 150, "y": 30 + row * 110, "beds": beds}, now, lenient=True)
        # a little Tenant History (people who already left)
        if rng.random() < 0.5:
            g = gender if gender != "Mixed" else rng.choice(["Male", "Female"])
            left = rng.randint(3, 80)
            write(cur, KINDS["tenant_history"], (uid, new_id()), {
                "tenant": _name(g, rng, used), "roomId": rid, "room": label, "slot": "Bed 1", "start": day(-left - rng.randint(30, 200)),
                "end": day(-left), "residentType": "Student", "residentGender": g, "reason": rng.choice(["Contract ended", "Moved out early", "Graduated"]),
                "leftAt": {"__ts": int((now - timedelta(days=left)).timestamp() * 1000)},
                "expireAt": {"__ts": int((now + timedelta(days=365)).timestamp() * 1000)}}, now, lenient=True)
        names.add(label)
        made += 1
    return made


def seed_account(pool, username="sample.one"):
    with pool.connection() as conn:
        with conn.transaction():
            cur = conn.cursor()
            full = username.lower() if "@" in username else username.lower() + "@vecancy.tracker"
            cur.execute("SELECT user_id FROM accounts WHERE username_lower=%s OR username_lower=%s", (full, username.lower()))
            row = cur.fetchone()
            if not row:
                return 0
            return seed(cur, row["user_id"])


if __name__ == "__main__":
    from localdb import LocalPool
    data = Path(__file__).resolve().parent.parent / "local-data" / "vacancy.db"
    print("Added %d sample rooms to sample.one." % seed_account(LocalPool(data)))
