"""Project-aware assistant layer (runs before smart.py in ai.answer).

It adds, for the SIGNED-IN account only:
  * account memory (ai_memory): preferences such as the report format, a preferred name and short
    notes. Every read/write is filtered by owner_uid on the server; nothing is shared between
    accounts and there is no global memory. Passwords, PINs and similar secrets are refused.
  * navigation: "take me to the server", "open the Room Canvas", "navigate to Room 205",
    "open the Super Admin analytics". The reply carries a `nav` object the page carries out.
    Room ids are looked up in the caller's own rooms; Super Admin pages only for super admins.
  * reports built from the caller's real records (table / bullet / detailed / comparison /
    explanation). Facts come from the database; anything not proven by the records is labelled
    "possible" and never presented as a confirmed cause.
  * Super Admin reports from the snapshots of branches this super admin was approved for.
  * one extra confirm-first action: update a tenant's contact number.

Nothing here writes tracker records. Changes are only PROPOSED (action) and the browser applies
them after the person confirms, through the app's normal validated workflow.
"""
import re
from datetime import date, datetime, timedelta, timezone

from store import KINDS, fetch, list_docs
import agent_nlu
import agent_viewer
import smart

DAY = timedelta(days=1)
SECRET = re.compile(r"\b(pass\s*word|passwd|passcode|pin\b|pin code|otp|one[- ]time|cvv|credit card|card number|"
                     r"bank account|account number|secret|token|api key)\b")
FORMATS = {"table": r"\btables?\b|\btabular\b", "bullet": r"\bbullets?\b|\bbullet points?\b|\blist\b",
           "detailed": r"\bdetailed\b|\bdetail\b|\bin depth\b|\bfull\b", "brief": r"\bbrief\b|\bshort\b|\bsummary only\b"}
FORMAT_LABEL = {"table": "tables", "bullet": "bullet points", "detailed": "detailed reports", "brief": "short summaries"}
MAX_NOTES = 10

ADMIN_TABS = [  # (tab id, label, patterns) - checked in order
    ("viewers", "Viewer Access (your viewer server)", r"\bserver\b|\bviewer access\b|\bviewers?\b"),
    ("central", "Central Link", r"\bcentral\b"),
    ("transfer", "Data Transfer", r"\bdata transfer\b|\btransfer (data|account)\b"),
    ("reminders", "Checkout Reminders", r"\breminders?\b|\boverdue\b"),
    ("calendar", "Checkout Schedule", r"\bcalendar\b|\bschedule\b"),
    ("matrix", "Bed Matrix", r"\bmatrix\b"),
    ("hallway", "Hallway Layout", r"\bhallway\b|\blayout\b"),
    ("reserve", "Reserved Clients", r"\breserv\w*\b"),
    ("temporary", "Temporary Dorm Clients", r"\btemporary\b|\btemp\b|\bguests?\b"),
    ("history", "Tenant History", r"\bhistory\b"),
    ("tenants", "Tenant Information", r"\btenant info\w*\b|\btenants?\b|\bemergency\b"),
    ("analytics", "Analytics", r"\banalytics?\b|\bcharts?\b|\bstats?\b|\bstatistics\b"),
    ("dashboard", "Room Canvas", r"\broom canvas\b|\bcanvas\b|\bdashboard\b|\brooms\b|\bhome\b"),
]
SUPER_TABS = [
    ("server", "Server Details", r"\bserver\b"),
    ("trading", "Analytics", r"\banalytics?\b|\bcharts?\b|\btrading\b|\bcandles?\b|\bforecast\b"),
    ("inbox", "Inbox", r"\binbox\b|\brequests?\b"),
    ("accounts", "Accounts", r"\baccounts?\b"),
    ("security", "Security", r"\bsecurity\b"),
    ("dorms", "Dormitories", r"\bdorm\w*\b|\bbranch\w*\b"),
    ("overview", "Overview", r"\boverview\b|\bdashboard\b|\bhome\b"),
]
NAV_VERB = re.compile(r"^(?:please |pls |can you |could you |kindly )*(?:take me to|bring me to|go to|go back to|open|open up|"
                      r"show me|navigate to|switch to|jump to|move to|head to|i want to see|let me see)\s+(?:the\s+|my\s+)?(.+?)[.!?]*$")


# --------------------------------------------------------------------------- helpers
def _now():
    return datetime.now(timezone.utc)


def _ts(v):
    if isinstance(v, dict) and "__ts" in v:
        return datetime.fromtimestamp(int(v["__ts"]) / 1000, tz=timezone.utc)
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _d(s):
    """'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM' -> date or None."""
    return smart.parse_iso(s) if s else None


def _pct(a, b):
    return (a / b * 100) if b else 0.0


def _p(x):
    return ("%.1f" % x).rstrip("0").rstrip(".") + "%"


def reply(intent, text, blocks=None, nav=None, action=None, suggestions=None, log=True):
    return {"intent": intent, "response": text, "blocks": blocks or [], "nav": nav,
            "action": action or {"type": "none"}, "suggestions": suggestions or [], "log": log}


def is_super(cur, uid):
    doc, _v = fetch(cur, KINDS["superAdmins"], (uid,))
    return bool(doc)


# --------------------------------------------------------------------------- memory (per account)
def mem_all(cur, uid):
    cur.execute("SELECT key, value, updated_at FROM ai_memory WHERE owner_uid=%s ORDER BY key", (uid,))
    return {r["key"]: r["value"] for r in cur.fetchall()}


def mem_set(cur, uid, key, value):
    cur.execute("INSERT INTO ai_memory (owner_uid, key, value, updated_at) VALUES (%s,%s,%s,now()) "
                "ON CONFLICT (owner_uid, key) DO UPDATE SET value=excluded.value, updated_at=now()", (uid, key, value))


def mem_del(cur, uid, key=None):
    if key:
        cur.execute("DELETE FROM ai_memory WHERE owner_uid=%s AND key=%s", (uid, key))
    else:
        cur.execute("DELETE FROM ai_memory WHERE owner_uid=%s", (uid,))


def memory_list(conn, uid):
    cur = conn.cursor()
    cur.execute("SELECT key, value, updated_at FROM ai_memory WHERE owner_uid=%s ORDER BY key", (uid,))
    return [{"key": r["key"], "value": r["value"], "label": _mem_label(r["key"], r["value"])} for r in cur.fetchall()]


def _mem_label(key, value):
    if key == "report_format":
        return "Report format: " + FORMAT_LABEL.get(value, value)
    if key == "name":
        return "Call you: " + value
    if key.startswith("note:"):
        return "Note: " + value
    return key + ": " + value


def _memory(conn, uid, t, raw):
    """Memory commands. -> reply or None."""
    asks_secret = SECRET.search(t)
    if re.search(r"\b(what do you (remember|know) about me|what do you remember|show (me )?(my|your) memory|"
                 r"what('s| is) in (your|my) memory|my memor(y|ies))\b", t) and not re.search(r"\b(clear|forget|delete|erase)\b", t):
        with conn.transaction():
            items = memory_list(conn, uid)
        if not items:
            return reply("memory_show", "I don't have anything saved for your account yet. You can say, for example, "
                         "\"Remember that I prefer table format for reports.\"")
        return reply("memory_show", "Here is what I remember for your account only (other accounts can't see it):",
                     [{"type": "list", "items": [i["label"] for i in items]},
                      {"type": "note", "text": "Say \"forget my memory\" to clear all of it, or \"forget my report format\" for one item."}])
    if re.search(r"\b(clear|delete|erase|wipe|reset)\b.*\b(chat|conversation|message)s?\b.*\bhistory\b|"
                 r"\b(clear|delete|erase)\b (the |my |our )?(chat|conversation)s?\b", t):
        with conn.transaction():
            cur = conn.cursor()
            cur.execute("DELETE FROM ai_conversations WHERE owner_uid=%s", (uid,))
        return reply("history_cleared", "Done. I deleted your saved conversation history. Your memory (preferences) "
                     "was kept; say \"forget my memory\" to clear that too.", log=False)
    if re.search(r"\b(forget|clear|delete|erase|wipe|reset)\b", t) and re.search(r"\bmemor(y|ies)\b|\beverything\b|\ball (that|you know)\b|\babout me\b", t):
        with conn.transaction():
            mem_del(conn.cursor(), uid)
        return reply("memory_cleared", "I cleared everything I remembered for your account. Your conversation history "
                     "and your tracker records were not touched.")
    if re.search(r"\bforget\b", t) and re.search(r"\b(report )?format\b", t):
        with conn.transaction():
            mem_del(conn.cursor(), uid, "report_format")
        return reply("memory_cleared", "Okay, I forgot your report format preference. Reports will use the standard layout.")
    if re.search(r"\bforget\b", t) and re.search(r"\bmy name\b", t):
        with conn.transaction():
            mem_del(conn.cursor(), uid, "name")
        return reply("memory_cleared", "Okay, I forgot the name you asked me to use.")

    wants_save = re.search(r"\b(remember|save|keep in mind|note that|from now on|always|i prefer|i like|i want)\b", t)
    if not wants_save:
        return None
    if asks_secret:
        return reply("memory_refused", "I won't store passwords, PINs, codes or other secrets in memory. "
                     "Nothing was saved. Keep those private.")
    fmt = next((k for k, p in FORMATS.items() if re.search(p, t)), None)
    if fmt and re.search(r"\b(report|reports|format|answers?|summar(y|ies))\b", t):
        with conn.transaction():
            mem_set(conn.cursor(), uid, "report_format", fmt)
        return reply("memory_saved", "Got it. I'll remember that you prefer %s for reports. This is saved to your "
                     "account only. Ask \"what do you remember\" anytime." % FORMAT_LABEL[fmt])
    m = re.search(r"\b(?:call me|my name is|remember (?:that )?my name is)\s+([a-z][a-z .'-]{0,40})$", t)
    if m and re.search(r"\b(remember|call me|my name is)\b", t):
        name = smart.title(m.group(1).strip(" .'-"))
        with conn.transaction():
            mem_set(conn.cursor(), uid, "name", name)
        return reply("memory_saved", "Nice to meet you, %s. I'll remember that for your account." % name)
    m = re.search(r"\b(?:remember|keep in mind|note)\s+(?:that\s+)?(.{3,200})$", raw.strip(), re.I)
    if m and re.search(r"\b(remember|keep in mind)\b", t):
        note = m.group(1).strip().rstrip(".")
        with conn.transaction():
            cur = conn.cursor()
            notes = [k for k in mem_all(cur, uid) if k.startswith("note:")]
            if len(notes) >= MAX_NOTES:
                return reply("memory_full", "I already keep %d notes for you. Say \"what do you remember\" and then "
                             "\"forget my memory\" to start fresh." % MAX_NOTES)
            mem_set(cur, uid, "note:%d" % (int(_now().timestamp() * 1000)), note[:200])
        return reply("memory_saved", "Saved to your account's memory: \"%s\"." % note[:200])
    return None


# --------------------------------------------------------------------------- navigation
DATA_ASK = re.compile(r"\b(vacan\w*|available|free|full|occupied|who|which|how many|for (today|tomorrow|next|this)|girls?|boys?|female|male|"
                      r"students?|reviewees?|private|another branch|other branch|its|that|those|there|lowest|highest|most|least|named|of [a-z]+ [a-z]+)\b")


def _nav(conn, uid, t, page):
    m = NAV_VERB.match(t)
    if m and re.match(r"^(?:please |pls |can you |could you |kindly )*(show me|i want to see|let me see)\b", t) and DATA_ASK.search(m.group(1)) \
            and not re.search(r"\b(tab|page|screen)\b", t):
        m = None                                     # "show me the vacant rooms" is a question, not "open the Room Canvas"
    target = m.group(1) if m else None
    if not target:
        m2 = re.search(r"^where (?:is|are|can i find) (?:the |my )?(.+?) ?(?:tab|page|screen)?\??$", t)
        target = m2.group(1) if m2 else None
    if not target:
        return None
    target = re.sub(r"\b(tab|page|screen|section|view|please|pls|now)\b", " ", target).strip()
    cur = conn.cursor()
    rm = re.search(r"\broom\b\s*(?:no\.?|number|#)?\s*([a-z0-9-]+)\b", target)
    if rm and rm.group(1) not in ("canvas", "info", "information", "management"):
        rec = smart.Records(cur, uid)
        room = rec.room_by_name(rm.group(1))
        if not room:
            names = ", ".join(str(r.get("room")) for r in rec.rooms[:12]) or "none yet"
            return reply("nav_room_missing", "I couldn't find Room %s in your dormitory, so I didn't move. "
                         "Your rooms: %s." % (rm.group(1).upper(), names))
        nav = {"tab": "dashboard", "roomId": room["id"], "room": str(room.get("room"))}
        if page == "superadmin":
            nav["url"] = "admin.html"
        occ = sum(1 for b in room["beds"] if b.get("tenant"))
        return reply("nav_room", "Opening Room %s on the Room Canvas (%d of %d beds occupied)." % (room.get("room"), occ, len(room["beds"])), nav=nav)
    if re.search(r"\bsuper ?admin\b|\bcentral (platform|analytics|dashboard)\b", target):
        if not is_super(cur, uid):
            return reply("nav_denied", "Your account isn't a Super Admin, so I can't open the Super Admin pages for you. "
                         "I didn't change anything.")
        tab = next((tid for tid, _l, p in SUPER_TABS if re.search(p, target.replace("super admin", ""))), "trading" if "analytic" in target else "overview")
        label = dict((a, b) for a, b, _p in SUPER_TABS)[tab]
        return reply("nav_super", "Opening Super Admin → %s." % label, nav={"url": "superadmin.html", "tab": tab})
    if page == "superadmin":
        for tid, label, p in SUPER_TABS:
            if re.search(p, target):
                return reply("nav_tab", "Opening %s." % label, nav={"tab": tid})
        for tid, label, p in ADMIN_TABS:
            if re.search(p, target):
                return reply("nav_tab", "That's on your Branch Admin page. Opening %s there." % label,
                             nav={"url": "admin.html", "tab": tid})
        return None
    for tid, label, p in ADMIN_TABS:
        if re.search(p, target):
            return reply("nav_tab", "Opening %s." % label, nav={"tab": tid})
    return None


# --------------------------------------------------------------------------- reports (branch admin)
def _bed_status(room, bed):
    if bed.get("tenant"):
        return "temporary" if bed.get("temporaryClientId") else "occupied"
    if bed.get("reservedFor"):
        return "reserved"
    if room.get("tenancyMode") == "Whole Room" and any(b.get("tenant") for b in room["beds"]):
        return "occupied"
    return "vacant"


def _history(cur, uid):
    return [dict(doc, id=i) for i, doc, _v in list_docs(cur, KINDS["tenant_history"], [uid], limit=5000)]


def occupancy_on(rec, hist, day):
    """Beds occupied at the end of `day`, rebuilt from contract start dates of current tenants and the
    stays recorded in Tenant History. Beds without a start date count as occupied since always."""
    n = 0
    for r, _i, b in rec.occupied():
        s = _d(b.get("start"))
        if s is None or s <= day:
            n += 1
    for h in hist:
        s, left = _d(h.get("start")), _ts(h.get("leftAt"))
        left_d = left.date() if left else _d(h.get("end"))
        if left_d is None:
            continue
        if (s is None or s <= day) and left_d > day:
            n += 1
    return n


def _fmt_pref(cur, uid, t):
    asked = next((k for k, p in FORMATS.items() if re.search(p, t)), None)
    if asked:
        return asked, False
    return mem_all(cur, uid).get("report_format") or "standard", True


def _render(fmt, title, summary, table, findings, recs, notes):
    """Same facts, different layout."""
    blocks = [{"type": "heading", "text": title}]
    if fmt == "brief":
        blocks.append({"type": "text", "text": summary})
        return blocks
    if fmt == "bullet":
        items = [summary] + ["%s: %s" % (row[0], ", ".join("%s %s" % (v, table["columns"][j + 1].lower()) for j, v in enumerate(row[1:])))
                             for row in table["rows"]] if table else [summary]
        blocks.append({"type": "list", "items": items})
    elif fmt == "table":
        blocks.append({"type": "text", "text": summary})
        if table:
            blocks.append(dict(table, type="table"))
    else:
        blocks.append({"type": "text", "text": summary})
        if table:
            blocks.append(dict(table, type="table"))
    if findings and fmt != "table":
        blocks += [{"type": "subheading", "text": "Findings (from your records)"}, {"type": "list", "items": findings}]
    elif findings:
        blocks.append({"type": "table", "columns": ["Finding (from your records)"], "rows": [[f] for f in findings]})
    if recs and fmt in ("detailed", "standard", "bullet"):
        blocks += [{"type": "subheading", "text": "Suggestions"}, {"type": "list", "items": recs}]
    for n in notes:
        blocks.append({"type": "note", "text": n})
    return blocks


def vacancy_report(cur, uid, t, today):
    rec = smart.Records(cur, uid)
    fmt, from_mem = _fmt_pref(cur, uid, t)
    if not rec.rooms:
        return reply("report_vacancy", "You don't have any rooms yet, so there is nothing to report. Add rooms on the Room Canvas first.")
    rows, tot = [], {"beds": 0, "occupied": 0, "vacant": 0, "reserved": 0, "temporary": 0}
    for r in rec.rooms:
        c = {"occupied": 0, "vacant": 0, "reserved": 0, "temporary": 0}
        for b in r["beds"]:
            c[_bed_status(r, b)] += 1
        beds = len(r["beds"])
        tot["beds"] += beds
        for k in c:
            tot[k] += c[k]
        rows.append([str(r.get("room")), beds, c["occupied"] + c["temporary"], c["vacant"], c["reserved"], _p(_pct(c["vacant"], beds))])
    rows.sort(key=lambda x: (-x[3], x[0]))
    rate = _pct(tot["vacant"], tot["beds"])
    week, month = today + 7 * DAY, today + 30 * DAY
    leaving = [(r, b) for r, _i, b in rec.occupied() if _d(b.get("end")) and today <= _d(b.get("end")) <= week]
    leaving30 = [(r, b) for r, _i, b in rec.occupied() if _d(b.get("end")) and today <= _d(b.get("end")) <= month]
    overdue = [(r, b) for r, _i, b in rec.occupied() if _d(b.get("end")) and _d(b.get("end")) < today]
    arriving = [p for p in rec.prospects if not p.get("checkedIn") and _d(p.get("checkIn")) and today <= _d(p.get("checkIn")) <= week]
    summary = ("%d of %d beds are vacant (%s). %d occupied, %d held for temporary guests, %d reserved."
               % (tot["vacant"], tot["beds"], _p(rate), tot["occupied"], tot["temporary"], tot["reserved"]))
    findings = []
    full = [r[0] for r in rows if r[3] == 0 and r[1]]
    empty = [r[0] for r in rows if r[1] and r[3] == r[1]]
    if empty:
        findings.append("Completely empty: Room " + ", ".join(empty[:8]) + ("…" if len(empty) > 8 else ""))
    if full:
        findings.append("No vacant beds: Room " + ", ".join(full[:8]) + ("…" if len(full) > 8 else ""))
    findings.append("%d contract%s end within 7 days%s." % (len(leaving), "" if len(leaving) == 1 else "s",
                    (": " + "; ".join("%s (Room %s, %s)" % (b.get("tenant"), r.get("room"), smart.pretty(b.get("end"))) for r, b in leaving[:5])) if leaving else ""))
    if len(leaving30) > len(leaving):
        findings.append("%d more end within 30 days." % (len(leaving30) - len(leaving)))
    if overdue:
        findings.append("%d tenant%s past the checkout date: %s." % (len(overdue), "" if len(overdue) == 1 else "s",
                        "; ".join("%s (Room %s)" % (b.get("tenant"), r.get("room")) for r, b in overdue[:5])))
    findings.append("%d reserved client%s arrive within 7 days." % (len(arriving), "" if len(arriving) == 1 else "s"))
    recs = []
    if leaving and len(arriving) < len(leaving):
        recs.append("%d bed%s will free up this week with no matching reservation yet; consider advertising them."
                    % (len(leaving) - len(arriving), "" if len(leaving) - len(arriving) == 1 else "s"))
    if overdue:
        recs.append("Follow up the overdue tenants on Checkout Reminders (extend or check out) so vacancy is accurate.")
    if rate >= 30:
        recs.append("Vacancy is high (30% or more). Review pricing or promotion for the emptiest rooms first.")
    if not recs:
        recs.append("No urgent action stands out from the records.")
    notes = ["Suggestions are recommendations, not facts. Counts are live from your rooms right now."]
    if from_mem and fmt != "standard":
        notes.append("Shown as %s because you asked me to remember that." % FORMAT_LABEL[fmt])
    table = {"columns": ["Room", "Beds", "Occupied", "Vacant", "Reserved", "Vacancy"], "rows": rows[:40]}
    return reply("report_vacancy", "Vacancy report: " + summary,
                 _render(fmt, "Vacancy report · " + smart.pretty(today), summary, table, findings, recs, notes))


def _month_bounds(today, back):
    y, m = today.year, today.month - back
    while m <= 0:
        y, m = y - 1, m + 12
    start = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return start, min(nxt - DAY, today)


def _period_stats(rec, hist, a, b):
    total = sum(len(r["beds"]) for r in rec.rooms)
    occ_a, occ_b = occupancy_on(rec, hist, a - DAY), occupancy_on(rec, hist, b)
    ins = [x for x in [(bd.get("tenant"), _d(bd.get("start"))) for _r, _i, bd in rec.occupied()] if x[1] and a <= x[1] <= b]
    ins += [(h.get("tenant"), _d(h.get("start"))) for h in hist if _d(h.get("start")) and a <= _d(h.get("start")) <= b]
    outs = [h for h in hist if _ts(h.get("leftAt")) and a <= _ts(h.get("leftAt")).date() <= b]
    return {"total": total, "occ_start": occ_a, "occ_end": occ_b, "vac_start": total - occ_a, "vac_end": total - occ_b,
            "ins": ins, "outs": outs}


def compare_months(cur, uid, t, today):
    rec, hist = smart.Records(cur, uid), _history(cur, uid)
    fmt, _m = _fmt_pref(cur, uid, t)
    if not rec.rooms:
        return reply("report_compare", "You don't have any rooms yet, so there is nothing to compare.")
    a1, b1 = _month_bounds(today, 0)
    a0, b0 = _month_bounds(today, 1)
    s0, s1 = _period_stats(rec, hist, a0, b0), _period_stats(rec, hist, a1, b1)
    lab0, lab1 = a0.strftime("%B %Y"), a1.strftime("%B %Y") + " (so far)"
    rows = [["Vacant beds at end", s0["vac_end"], s1["vac_end"], s1["vac_end"] - s0["vac_end"]],
            ["Vacancy rate at end", _p(_pct(s0["vac_end"], s0["total"])), _p(_pct(s1["vac_end"], s1["total"])),
             ("%+.1f pts" % (_pct(s1["vac_end"], s1["total"]) - _pct(s0["vac_end"], s0["total"])))],
            ["Check-ins", len(s0["ins"]), len(s1["ins"]), len(s1["ins"]) - len(s0["ins"])],
            ["Check-outs", len(s0["outs"]), len(s1["outs"]), len(s1["outs"]) - len(s0["outs"])]]
    diff = s1["vac_end"] - s0["vac_end"]
    summary = ("Vacancy %s from %d to %d beds between the end of %s and today."
               % ("rose" if diff > 0 else "fell" if diff < 0 else "stayed", s0["vac_end"], s1["vac_end"], a0.strftime("%B")))
    notes = ["Rebuilt from contract start dates and Tenant History check-out times. Assumes your room and bed "
             "list did not change during these months; history older than its expiry may be missing."]
    blocks = [{"type": "heading", "text": "Comparison · %s vs %s" % (a0.strftime("%b"), a1.strftime("%b %Y"))},
              {"type": "text", "text": summary},
              {"type": "table", "columns": ["Measure", lab0, lab1, "Change"], "rows": rows}]
    if fmt in ("bullet", "detailed", "standard"):
        blocks.append({"type": "list", "items": ["%s: %s → %s (%s)" % (r[0], r[1], r[2], r[3]) for r in rows]} if fmt == "bullet" else
                      {"type": "list", "items": ["Check-outs this month: " + (", ".join(sorted({str(h.get('tenant')) for h in s1['outs']})[:8]) or "none"),
                                                 "Check-ins this month: " + (", ".join(sorted({str(n) for n, _d2 in s1['ins']})[:8]) or "none")]})
    blocks += [{"type": "note", "text": n} for n in notes]
    return reply("report_compare", summary, blocks)


def explain_change(cur, uid, t, today, days=30):
    rec, hist = smart.Records(cur, uid), _history(cur, uid)
    if not rec.rooms:
        return reply("report_explain", "You don't have any rooms yet, so there is no vacancy change to explain.")
    a = today - timedelta(days=days)
    s = _period_stats(rec, hist, a + DAY, today)
    diff = s["vac_end"] - s["vac_start"]
    direction = "increased" if diff > 0 else "decreased" if diff < 0 else "did not change"
    summary = ("Over the last %d days vacancy %s: %d → %d vacant beds (%s → %s)."
               % (days, direction, s["vac_start"], s["vac_end"], _p(_pct(s["vac_start"], s["total"])), _p(_pct(s["vac_end"], s["total"]))))
    confirmed, possible = [], []
    if s["outs"]:
        reasons = {}
        for h in s["outs"]:
            reasons[(h.get("reason") or "no reason recorded").strip() or "no reason recorded"] = reasons.get((h.get("reason") or "no reason recorded").strip() or "no reason recorded", 0) + 1
        confirmed.append("%d check-out%s recorded: %s." % (len(s["outs"]), "" if len(s["outs"]) == 1 else "s",
                         "; ".join("%s (Room %s, %s)" % (h.get("tenant"), h.get("room"), _ts(h.get("leftAt")).strftime("%b %d").replace(" 0", " ")) for h in s["outs"][:6])))
        confirmed.append("Reasons written at check-out: " + ", ".join("%s ×%d" % (k, v) for k, v in reasons.items()) + ".")
    confirmed.append("%d check-in%s started in the same period." % (len(s["ins"]), "" if len(s["ins"]) == 1 else "s"))
    if diff > 0 and len(s["outs"]) > len(s["ins"]):
        confirmed.append("More tenants left (%d) than arrived (%d); that difference is the recorded cause of the increase."
                         % (len(s["outs"]), len(s["ins"])))
    upcoming = [b for _r, _i, b in rec.occupied() if _d(b.get("end")) and today <= _d(b.get("end")) <= today + 30 * DAY]
    if upcoming:
        possible.append("%d more contract%s end within 30 days, which may raise vacancy further unless renewed or replaced."
                        % (len(upcoming), "" if len(upcoming) == 1 else "s"))
    if diff > 0 and not s["outs"]:
        possible.append("No check-outs are recorded, so the change may come from beds added or edited in rooms; the records don't say.")
    if diff > 0:
        possible.append("Not confirmed by the records: seasonal demand, pricing or competition. I can't verify those from tracker data.")
    blocks = [{"type": "heading", "text": "Why vacancy %s · last %d days" % (direction, days)}, {"type": "text", "text": summary},
              {"type": "subheading", "text": "Confirmed by your records"}, {"type": "list", "items": confirmed}]
    if possible:
        blocks += [{"type": "subheading", "text": "Possible factors (not confirmed)"}, {"type": "list", "items": possible}]
    blocks.append({"type": "note", "text": "Rebuilt from contract dates and Tenant History; assumes the bed list did not change."})
    return reply("report_explain", summary, blocks)


# --------------------------------------------------------------------------- reports (super admin)
RISK = {"hiRate": 30, "hiJump": 10, "modRate": 15, "modJump": 3, "modSoon": 10}


def parse_co(s):
    out = []
    for part in str(s or "").split(","):
        if ":" in part:
            d, n = part.rsplit(":", 1)
            dd = smart.parse_iso(d)
            if dd and n.strip().isdigit():
                out.append((dd, int(n)))
    return out


def risk_of(snaps):
    """Same default rules as the Super Admin chart. snaps sorted by time."""
    if not snaps:
        return None
    s = snaps[-1]
    if not s.get("total"):
        return None
    rate = _pct(s.get("vacant") or 0, s["total"])
    t = s["_t"]
    wk = [x for x in snaps if x["_t"] <= t - 7 * DAY]
    change = (rate - _pct(wk[-1].get("vacant") or 0, wk[-1]["total"])) if wk and wk[-1].get("total") else None
    soon = sum(n for d, n in parse_co(s.get("checkouts")) if t.date() < d <= t.date() + 7 * DAY)
    why, level = [], "safe"
    if rate >= RISK["hiRate"]:
        level = "high"; why.append("vacancy %s ≥ %d%%" % (_p(rate), RISK["hiRate"]))
    if change is not None and change >= RISK["hiJump"]:
        level = "high"; why.append("up %.1f pts in 7 days" % change)
    if level != "high":
        if rate >= RISK["modRate"]:
            level = "moderate"; why.append("vacancy %s ≥ %d%%" % (_p(rate), RISK["modRate"]))
        if change is not None and change >= RISK["modJump"]:
            level = "moderate"; why.append("rising +%.1f pts in 7 days" % change)
        if _pct(soon, s["total"]) >= RISK["modSoon"]:
            level = "moderate"; why.append("%d check-outs due within 7 days" % soon)
    if level == "safe":
        why.append("vacancy " + _p(rate))
    return {"level": level, "rate": rate, "change": change, "soon": soon, "why": why, "at": t}


def super_branches(cur, uid):
    """Only branches this super admin requested AND the branch approved for analytics."""
    out = []
    for bid, doc, _v in list_docs(cur, KINDS["branches"], [], limit=500):
        if doc.get("requestedBy") == uid and doc.get("analyticsStatus") == "approved":
            snaps = []
            for _sid, s, _v2 in list_docs(cur, KINDS["branch_snapshots"], [bid], limit=5000):
                t = _ts(s.get("capturedAt"))
                if t:
                    snaps.append(dict(s, _t=t))
            snaps.sort(key=lambda x: x["_t"])
            out.append((bid, doc, snaps))
    return out


def super_report(cur, uid, t, today):
    if not is_super(cur, uid):
        return reply("report_denied", "Branch reports across dormitories are for Super Admin accounts only. "
                     "Ask me for a vacancy report of your own dormitory instead.")
    fmt, _m = _fmt_pref(cur, uid, t)
    data = super_branches(cur, uid)
    if not data:
        return reply("report_super", "No dormitory has approved analytics sharing with you yet, so there is no data to report.")
    rows, findings = [], []
    now = _now()
    for bid, doc, snaps in data:
        name = doc.get("dormName") or bid
        if not snaps:
            rows.append([name, "—", "—", "—", "—", "No data yet"])
            continue
        last = snaps[-1]
        rate = _pct(last.get("vacant") or 0, last.get("total") or 0)
        prev = [x for x in snaps if x["_t"] <= last["_t"] - 30 * DAY]
        ch30 = (rate - _pct(prev[-1].get("vacant") or 0, prev[-1].get("total") or 0)) if prev else None
        r = risk_of(snaps)
        rows.append([name, last.get("total"), last.get("vacant"), _p(rate), ("%+.1f pts" % ch30) if ch30 is not None else "n/a",
                     {"high": "High risk", "moderate": "Moderate", "safe": "Safe"}[r["level"]] if r else "—"])
        if r and r["level"] != "safe":
            findings.append("%s: %s (%s)." % (name, {"high": "high risk", "moderate": "moderate risk"}[r["level"]], "; ".join(r["why"])))
        if now - last["_t"] > 2 * DAY:
            findings.append("%s: latest data is from %s, so it may be out of date." % (name, last["_t"].strftime("%b %d").replace(" 0", " ")))
    ranked = sorted([r for r in rows if isinstance(r[2], int)], key=lambda r: -float(r[3].rstrip("%")))
    tv = sum(r[2] for r in ranked)
    tt = sum(r[1] for r in ranked if isinstance(r[1], int))
    asks_highest = re.search(r"\b(highest|most|worst|top)\b", t)
    summary = ("Across %d dormitor%s: %d of %d beds vacant (%s)." % (len(data), "y" if len(data) == 1 else "ies", tv, tt, _p(_pct(tv, tt))))
    if ranked:
        summary += " Highest vacancy: %s at %s." % (ranked[0][0], ranked[0][3])
    if asks_highest and ranked:
        text = "%s has the highest vacancy rate: %s (%d of %d beds vacant, latest snapshot)." % (ranked[0][0], ranked[0][3], ranked[0][2], ranked[0][1])
        return reply("report_super", text, [{"type": "table", "columns": ["Dormitory", "Beds", "Vacant", "Vacancy", "30-day change", "Risk"], "rows": ranked}])
    table = {"columns": ["Dormitory", "Beds", "Vacant", "Vacancy", "30-day change", "Risk"], "rows": ranked + [r for r in rows if not isinstance(r[2], int)]}
    notes = ["From each dormitory's latest recorded snapshot. Risk uses the default rules (high: vacancy ≥ 30% or +10 pts in 7 days; "
             "moderate: ≥ 15%, +3 pts, or ≥ 10% of beds checking out within 7 days)."]
    recs = ["Look at the high-risk dormitories first on the Analytics tab."] if any("High" in str(r[5]) for r in rows) else []
    return reply("report_super", summary, _render(fmt, "Dormitory vacancy report", summary, table, findings or ["No dormitory is above the risk thresholds."], recs, notes))


# --------------------------------------------------------------------------- tenant contact update (proposed only)
PH_MOBILE = re.compile(r"^(09\d{9}|\+639\d{9})$")


def _contact_update(cur, uid, raw, t):
    m = re.search(r"(?:update|change|set|edit|replace)\s+(?:the\s+)?(?:contact|phone|mobile|cell(?:phone)?)\s*(?:number|no\.?|#)?\s+"
                  r"(?:of|for)\s+(.+?)\s+(?:to|into|as|with)\s+([+0-9][0-9 +()-]{0,24})\s*$", t) or \
        re.search(r"(?:update|change|set|edit)\s+(.+?)['’]s?\s+(?:contact|phone|mobile)\s*(?:number|no\.?)?\s+(?:to|as|into)\s+([+0-9][0-9 +()-]{0,24})\s*$", t) or \
        re.search(r"(?:update|change|set|edit)\s+(?:this|the)\s+tenant['’]?s?\s+(?:contact|phone|mobile)\s*(?:number|no\.?)?\s+(?:to|as|into)\s+([+0-9][0-9 +()-]{0,24})\s*$", t)
    if not m:
        return None
    if m.lastindex == 1:
        who, number = None, m.group(1)
    else:
        who, number = m.group(1), m.group(2)
    clean = re.sub(r"[\s()-]", "", number)
    if not PH_MOBILE.match(clean):
        return reply("clarify", "\"%s\" isn't a valid Philippine mobile number. Use 09XXXXXXXXX (11 digits) or "
                     "+639XXXXXXXXX. Nothing was changed." % number.strip())
    rec = smart.Records(cur, uid)
    hits = []
    for r, i, b in rec.occupied():
        if who and smart.norm(who) in smart.norm(b.get("tenant")):
            hits.append((r, i, b))
    if who is None:
        return reply("clarify", "Which tenant? Say for example \"update the contact number of Ana Cruz to %s\"." % clean)
    if not hits:
        return reply("clarify", "I couldn't find a current tenant named \"%s\" in your rooms. Nothing was changed." % who)
    if len(hits) > 1:
        return reply("clarify", "More than one tenant matches \"%s\": %s. Please use the full name." %
                     (who, "; ".join("%s (Room %s)" % (b.get("tenant"), r.get("room")) for r, _i, b in hits[:6])))
    r, i, b = hits[0]
    old = None
    if b.get("tenantId"):
        doc, _v = fetch(cur, KINDS["tenants"], (uid, b["tenantId"]))
        if doc and smart.norm(doc.get("name")) == smart.norm(b.get("tenant")):
            old = doc.get("contact")
    action = {"type": "update_tenant_contact", "roomId": r["id"], "slot": smart.bed_label(b, i), "tenant": b.get("tenant"), "contact": clean}
    text = ("Here's what I understood: change the contact number of %s (Room %s, %s) from %s to %s. "
            "Please confirm; nothing is saved until you do." % (b.get("tenant"), r.get("room"), smart.bed_label(b, i), old or "none on file", clean))
    return reply("action_proposal", text, action=action)


# --------------------------------------------------------------------------- entry point
PAGES = ("admin", "superadmin", "viewer", "marketing")


def handle(conn, uid, question, context):
    ctx = context if isinstance(context, dict) else {}
    page = ctx.get("page") if ctx.get("page") in PAGES else "admin"
    raw = str(question or "")
    t = smart.norm(raw)
    tn = agent_nlu.normalize(raw)              # spelling fixes + synonyms ("vacnt beds for boys" -> "vacant beds for male")
    today = smart.parse_iso(ctx.get("today")) or date.today()

    hit = _memory(conn, uid, t, raw)
    if hit:
        return hit
    if page == "viewer":                       # read-only, name-free, only the dormitory this account may view
        return agent_viewer.handle_viewer(conn, uid, raw, tn, ctx) or _memory(conn, uid, "what do you remember", raw)
    if page == "marketing":
        return agent_viewer.handle_directory(conn, uid, raw, tn, ctx)
    hit = _nav(conn, uid, tn, page) or (_nav(conn, uid, t, page) if tn != t else None)
    if hit:
        return hit
    cur = conn.cursor()
    if page == "admin":
        hit = _contact_update(cur, uid, raw, t)
        if hit:
            return hit
    vac = re.search(r"\bvacan\w*|\boccupan\w*|\bempty beds?\b|\bfree beds?\b", t)
    if page == "superadmin" and (re.search(r"\b(report|summar\w*|compare|comparison|highest|lowest|which (dorm|branch))\b", t) and
                                 (vac or re.search(r"\b(dorm\w*|branch\w*|risk)\b", t))):
        return super_report(cur, uid, t, today)
    if page != "admin":
        return None
    if re.search(r"\bwhy\b", t) and vac and re.search(r"\b(increas\w*|went up|rise|rose|higher|grow\w*|decreas\w*|went down|drop\w*|fell|lower|chang\w*)\b", t):
        m = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days?\b", t)
        return explain_change(cur, uid, t, today, int(m.group(1)) if m else 30)
    if re.search(r"\bcompare\b|\bcomparison\b|\bvs\.?\b|\bversus\b", t) and re.search(r"\bmonth\b", t):
        return compare_months(cur, uid, t, today)
    m = re.search(r"\b(?:last|past)\s+(\d{1,3})\s+days?\b", t)
    if m and (vac or re.search(r"\breport\b", t)):
        return explain_change(cur, uid, t, today, int(m.group(1)))
    if vac and re.search(r"\b(report|summar\w*|overview|status|breakdown|analy[sz]\w*)\b", t) or re.search(r"^(report|vacancy report)\b", t):
        return vacancy_report(cur, uid, t, today)
    return None


# --------------------------------------------------------------------------- trained fallback (after smart.py)
ADMIN_FALLBACK = ["vacancy_summary", "occupancy_summary", "upcoming", "checkins", "compare", "report", "explain", "trend",
                  "room_status", "highest", "help", "memory_show"]


def admin_rooms(cur, uid):
    """The Branch Admin's rooms in vacancy_core form (reservation dates added from Reserved Clients)."""
    rec = smart.Records(cur, uid)
    starts = {p["id"]: p.get("checkIn") for p in rec.prospects}
    out = []
    for r in rec.rooms:
        beds = [dict(b, reservedFrom=starts.get(b.get("reservedFor"))) for b in r["beds"]]
        out.append(dict(r, beds=beds, bedInfo=None))
    return out


def fallback(conn, uid, question, context, strong_only=False):
    """Used when neither the rules here nor smart.py understood the sentence: the trained classifier picks the
    closest known request (it understands misspellings and other wordings) and answers from real data."""
    ctx = context if isinstance(context, dict) else {}
    page = ctx.get("page") if ctx.get("page") in ("admin", "superadmin") else "admin"
    intent, score = agent_nlu.classify(question, ADMIN_FALLBACK)
    if not intent:
        return None
    # before the general intent model only clear matches it has no live answer for
    if strong_only and (score < 0.5 or intent in ("vacancy_summary", "occupancy_summary", "help", "memory_show", "explain")):
        return None
    tn = agent_nlu.normalize(question)
    today = smart.parse_iso(ctx.get("today")) or date.today()
    cur = conn.cursor()
    if intent == "memory_show":
        return _memory(conn, uid, "what do you remember", question)
    if intent == "help":
        return reply("help", "I can answer from your records, make reports and take you places. Try:",
                     [{"type": "list", "items": (["Report the vacancy (as a table / bullet points)", "Compare male and female rooms",
                                                  "Show upcoming vacancies", "Why did vacancy increase?", "Compare this month with last month",
                                                  "Navigate to Room 205", "Update the contact number of <tenant> to 09XXXXXXXXX",
                                                  "Remember that I prefer table format for reports"] if page == "admin" else
                                                 ["Which dorm has the highest vacancy?", "Report the vacancy of the dorms",
                                                  "Take me to the analytics", "Open the server details"])}])
    if page == "superadmin":
        return super_report(cur, uid, tn, today) if intent in ("report", "highest", "compare", "vacancy_summary", "occupancy_summary") else None
    if intent == "report":
        return vacancy_report(cur, uid, tn, today)
    if intent == "trend":
        return explain_change(cur, uid, tn, today)
    now, tz = agent_viewer.clock(ctx)
    rooms = admin_rooms(cur, uid)
    if not rooms:
        return None
    return agent_viewer.answer_scope(intent, tn, rooms, {}, now, tz, "admin", ctx.get("roomId") if isinstance(ctx.get("roomId"), str) else None)
