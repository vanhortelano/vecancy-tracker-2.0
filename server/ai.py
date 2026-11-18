"""Dorm Assistant on SQL. Same answers as before; the data it reads and the history, insights
and settings it produces now live in PostgreSQL (ai_* tables). The trained intent model
(brain.py + intents.json) is unchanged."""
from datetime import datetime, timezone

from dbcompat import Jsonb

import logging

import re

import agent
import answers
import expert
import lang
import pages
import precise
import smart
import understand
from store import new_id

log = logging.getLogger("vacancy")

LIVE_TAGS = {"live_vacant", "live_overdue", "live_occupancy"}


def parse_date(value):
    if not value:
        return None
    text = str(value)
    try:
        dt = datetime.fromisoformat(text + "T23:59:59") if len(text) == 10 else datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def snapshot(conn, uid):
    cur = conn.cursor()
    cur.execute("""SELECT r.id, r.room, r.tenancy_mode, b.slot, b.tenant, b.bed_end, b.reserved_for, b.temporary_client_id
                   FROM rooms r LEFT JOIN beds b ON b.owner_uid=r.owner_uid AND b.room_id=r.id
                   WHERE r.owner_uid=%s ORDER BY r.room, b.position""", (uid,))
    now = datetime.now(timezone.utc)
    stats = {"rooms": 0, "beds": 0, "vacant": 0, "reserved": 0, "occupied": 0, "overdue": [], "vacant_rooms": {}}
    rooms = {}
    for row in cur.fetchall():
        rooms.setdefault(row["id"], {"name": str(row["room"] or "?"), "whole": row["tenancy_mode"] == "Whole Room", "beds": []})
        if row["slot"] is not None or row["tenant"] is not None:
            rooms[row["id"]]["beds"].append(row)
    for room in rooms.values():
        taken = any(b["tenant"] for b in room["beds"])
        stats["rooms"] += 1
        for bed in room["beds"]:
            stats["beds"] += 1
            if bed["tenant"]:
                end = parse_date(bed["bed_end"])
                if end and end < now:
                    stats["overdue"].append((room["name"], bed["slot"] or "", bed["tenant"], end))
                stats["occupied"] += 1
            elif bed["reserved_for"] or bed["temporary_client_id"]:
                stats["reserved"] += 1
            elif room["whole"] and taken:
                stats["occupied"] += 1
            else:
                stats["vacant"] += 1
                stats["vacant_rooms"][room["name"]] = stats["vacant_rooms"].get(room["name"], 0) + 1
    return stats


def live_answer(tag, stats):
    s = stats
    if s["beds"] == 0:
        return "You don't have any rooms yet. Press + Add room on Room Canvas to create your first one."
    if tag == "live_vacant":
        if not s["vacant"]:
            return f"There are no vacant beds right now. All {s['beds']} beds are occupied or reserved."
        rooms = sorted(s["vacant_rooms"].items(), key=lambda kv: (-kv[1], kv[0]))
        shown = ", ".join(f"Room {n} ({c})" for n, c in rooms[:8])
        more = f" and {len(rooms) - 8} more" if len(rooms) > 8 else ""
        return (f"You have {s['vacant']} vacant bed{'s' if s['vacant'] != 1 else ''} across {len(rooms)} room"
                f"{'s' if len(rooms) != 1 else ''} (out of {s['beds']} beds): {shown}{more}. "
                f"{s['reserved']} more are reserved (counted as occupied).")
    if tag == "live_overdue":
        if not s["overdue"]:
            return "No one is past their checkout date right now."
        s["overdue"].sort(key=lambda x: x[3])
        lines = "; ".join(f"{t} (Room {r}, {b})" for r, b, t, _ in s["overdue"][:6])
        more = f" and {len(s['overdue']) - 6} more" if len(s["overdue"]) > 6 else ""
        return (f"{len(s['overdue'])} tenant{'s are' if len(s['overdue']) != 1 else ' is'} past checkout: {lines}{more}. "
                "Open the Checkout Reminders tab to extend their stay or check them out.")
    used = s["occupied"] + s["reserved"]                 # a reserved or temporary bed counts as occupied
    pct = round(used / s["beds"] * 100)
    return (f"You have {s['rooms']} rooms and {s['beds']} beds. {used} are occupied ({pct}%) and {s['vacant']} are vacant. "
            f"The occupied beds include {s['reserved']} reserved or held for temporary guests.")


def _conversation(conn, uid, conversation_id, first_text):
    cur = conn.cursor()
    if conversation_id:
        cur.execute("SELECT id FROM ai_conversations WHERE id=%s AND owner_uid=%s", (conversation_id, uid))
        if cur.fetchone():           # only ever the caller's own conversation
            return conversation_id
    cid = new_id()
    cur.execute("INSERT INTO ai_conversations (id, owner_uid, title) VALUES (%s,%s,%s)", (cid, uid, first_text[:60]))
    prune_conversations(cur, uid, keep=KEEP_CHATS, protect=cid)
    return cid


KEEP_CHATS = 7          # only the newest 7 chats are kept; older ones are deleted with their messages


def prune_conversations(cur, uid, keep=KEEP_CHATS, protect=None):
    """Delete the caller's chats beyond the newest `keep` (owner-filtered, so nobody else's chats are touched).
    Messages, their tables/extras and insight links go with them (done by hand: SQLite may not enforce the cascade)."""
    cur.execute("SELECT id FROM ai_conversations WHERE owner_uid=%s ORDER BY updated_at DESC, created_at DESC", (uid,))
    ids = [r["id"] for r in cur.fetchall()]
    if protect in ids:                                   # the chat being started right now is always kept
        ids.remove(protect)
        ids.insert(0, protect)
    old = ids[keep:]
    for cid in old:
        cur.execute("DELETE FROM ai_message_extras WHERE owner_uid=%s AND message_id IN "
                    "(SELECT id FROM ai_messages WHERE conversation_id=%s AND owner_uid=%s)", (uid, cid, uid))
        cur.execute("DELETE FROM ai_messages WHERE conversation_id=%s AND owner_uid=%s", (cid, uid))
        cur.execute("UPDATE ai_insights SET conversation_id=NULL WHERE conversation_id=%s AND owner_uid=%s", (cid, uid))
        cur.execute("DELETE FROM ai_conversations WHERE id=%s AND owner_uid=%s", (cid, uid))
    return len(old)


def answer(conn, brain, uid, question, conversation_id=None, context=None, unread=""):
    """-> dict in the same shape the browser already expects, plus conversationId.
    The whole message is read first (understand.py): a message with several separate requests is answered part by
    part through the same rules, and `unread` (text past the length limit) is reported instead of silently dropped."""
    page = (context or {}).get("page") if isinstance(context, dict) else None
    cut = _cut_note(question, unread)
    said, greet, parts = question, None, []
    try:                                                  # "hey, which rooms …": answer the request, not just the "hey"
        greet, question = understand.greeting(question)
    except Exception:
        log.exception("could not read the greeting; continuing")
    try:
        if not (page in (None, "", "admin") and _draft_waiting(conn, uid, lang.to_english(question) or "")):
            parts = understand.split(question)            # a half-finished request (smart.py asked something) is never split
    except Exception:
        log.exception("could not split the message; answering it as one request")
    if len(parts) < 2:
        extra = [cut] if cut else []
        try:                                              # "check out Ana and transfer Ben": one change at a time, the rest is named
            changes = understand.commands(question) if len(question) >= 25 else []
            if len(changes) > 1:
                extra.insert(0, {"type": "note", "text": "Your message asks for %d changes. I prepare one change at a time so you can check each "
                                 "before it happens, so I started with the first. After you confirm or cancel it, send the next: %s." % (
                                     len(changes), "; ".join("“%s”" % c for c in changes[1:]))})
        except Exception:
            log.exception("could not list the changes; continuing")
        return _answer_one(conn, brain, uid, question, conversation_id, context, extra_blocks=extra, said=said, greet=greet)
    return _answer_many(conn, brain, uid, said, parts, conversation_id, context, cut, greet)


def _cut_note(question, unread):
    if not unread:
        return None
    tail = " ".join(str(question).split()[-6:])
    return {"type": "note", "text": "Your message was longer than %d characters, so I only read up to “…%s”. The remaining %d characters were not "
                                    "read — send them as another message." % (understand.MAX_CHARS, tail, len(unread))}


def _answer_many(conn, brain, uid, question, parts, conversation_id, context, cut, greet=None):
    """Several requests in one message: each one goes through the normal rules, and the answers come back together."""
    extra = parts[understand.MAX_PARTS:]
    parts = parts[:understand.MAX_PARTS]
    results = []
    for i, p in enumerate(parts):
        results.append(_answer_one(conn, brain, uid, p, conversation_id, context, sub=True, allow_follow=(i == 0)))
    acting = [i for i, r in enumerate(results) if (r.get("action") or {}).get("type", "none") != "none" or r.get("intent") == "clarify"]
    if len(acting) > 1:
        # more than one change or open question: handle the message as one request, as before
        return _answer_one(conn, brain, uid, question, conversation_id, context, extra_blocks=[cut] if cut else [])
    words = {2: "two", 3: "three", 4: "four"}
    blocks, action = [], {"type": "none"}
    if acting:                                            # one change (Confirm button) + questions: the change leads, answers follow
        main = results[acting[0]]
        lead = ((greet + " ") if greet else "") + main["response"]
        action = main.get("action") or {"type": "none"}
        blocks.extend(main.get("blocks") or [])
        blocks.append({"type": "heading", "text": "And the rest of what you asked"})
    else:
        lead = ((greet + " ") if greet else "") + "You asked %s things, so here's each one." % words.get(len(parts), str(len(parts)))
    for i, (p, r) in enumerate(zip(parts, results)):
        if acting and i == acting[0]:
            continue
        blocks.append({"type": "subheading", "text": p[:1].upper() + p[1:].rstrip(" ,.")})
        blocks.append({"type": "text", "text": r["response"]})
        blocks.extend(r.get("blocks") or [])
    later = understand.plural_note(len(parts), extra)
    if later:
        blocks.append({"type": "note", "text": later})
    if cut:
        blocks.append(cut)
    navs = [r.get("nav") for r in results if r.get("nav")]
    nav = navs[0] if len(navs) == 1 else None
    suggestions = results[-1].get("suggestions") or []
    text = lead
    with conn.transaction():
        cid = _conversation(conn, uid, conversation_id, question)
        if acting:                                        # the change's half-finished request belongs to this chat
            try:
                pending = smart.get_draft(conn.cursor(), uid, datetime.now(timezone.utc))
                if pending and pending.get("cid") != cid:
                    smart.set_draft(conn.cursor(), uid, dict(pending, cid=cid), datetime.now(timezone.utc))
            except Exception:
                log.exception("could not tag the draft")
        cur = conn.cursor()
        cur.execute("INSERT INTO ai_messages (conversation_id, owner_uid, role, content) VALUES (%s,%s,'user',%s)", (cid, uid, question))
        cur.execute("INSERT INTO ai_messages (conversation_id, owner_uid, role, content, intent, confidence, scope) "
                    "VALUES (%s,%s,'assistant',%s,%s,%s,%s)", (cid, uid, text, "multi", 1.0, "tracker"))
        cur.execute("SELECT id FROM ai_messages WHERE conversation_id=%s AND owner_uid=%s AND role='assistant' ORDER BY id DESC LIMIT 1", (cid, uid))
        mid = cur.fetchone()["id"]
        cur.execute("INSERT INTO ai_message_extras (message_id, owner_uid, blocks) VALUES (%s,%s,%s)", (mid, uid, Jsonb({"blocks": blocks, "nav": nav})))
        cur.execute("UPDATE ai_conversations SET updated_at=now() WHERE id=%s", (cid,))
    page = (context or {}).get("page") if isinstance(context, dict) else None
    last = next((r for r in reversed(results) if r.get("scope") == "tracker" and r.get("english")), None)
    if last:                                              # "what about the female rooms?" then continues the last data question
        _remember(conn, uid, last["english"], page, cid)
    intro = INTRO if not isinstance(conversation_id, str) else None
    return {"response": text, "scope": "tracker", "action": action, "intent": "multi", "intro": intro, "confidence": 1.0,
            "conversationId": cid, "suggestions": suggestions, "blocks": blocks, "nav": nav,
            "parts": [{"text": p, "intent": r.get("intent")} for p, r in zip(parts, results)]}


def _answer_one(conn, brain, uid, question, conversation_id=None, context=None, sub=False, allow_follow=True, extra_blocks=None,
                said=None, greet=None):
    """One request. The smarter layer (smart.py: records, screen context, proposed changes) answers first; anything
    it does not recognise goes to the trained intent model exactly as before. sub=True: part of a longer message,
    so nothing is saved here (_answer_many saves the combined answer). said: the user's exact words (saved in the history)."""
    action, suggestions, smart_reply = {"type": "none"}, [], None
    blocks, nav, keep_log = [], None, True
    original = said or question
    page = (context or {}).get("page") if isinstance(context, dict) else None
    # 1. how people really type: misspellings, Cebuano / Tagalog / Taglish -> simple English
    q = lang.to_english(question) or str(question or "")
    q = expert.name_rooms(expert.command_form(q))        # "can you add …" -> "add …"; "in s-105" -> "in room s-105"
    try:                                                 # wordings the older rules misread ("checking out", "can we see …", "count the …")
        q = precise.reword(q) or q
    except Exception:
        log.exception("could not reword the question; continuing")
    read_notes = []
    try:                                                 # "except the female rooms", "don't include rooms with someone coming in"
        q, read_notes = understand.exclusions(q)
    except Exception:
        log.exception("could not read the exclusions; continuing")
    raw_low = expert.command_form(re.sub(r"\s+", " ", str(question or "").lower()).strip())
    today_ = smart.parse_iso((context or {}).get("today") if isinstance(context, dict) else None) or datetime.now(timezone.utc).date()
    is_admin = page in (None, "", "admin")
    precise.set_tz(context)                              # local dates for this question (never a previous request's)
    named = False                                        # True when "she / his / that tenant" was replaced by the person's name
    if is_admin:
        try:                                             # "when does she check out?" -> the person talked about last in this chat
            filled = precise.fill_pronouns(conn, uid, q, conversation_id) or q
            if filled != q:
                named = True
                q = re.sub(r"^(?:and|also|then|so|ok|okay)\s+", "", filled)   # "and what is her address" is a new question about her
                q = precise.reword(q) or q               # "what is ana rivera's room" -> "where is ana rivera"
                raw_low = q                              # the older layers read raw_low too: give them the name, not "her"
        except Exception:
            log.exception("could not fill in the pronoun; continuing")
        try:                                             # "extend X by 1 month", "move X to bed 4", "add 2 beds to S-110" (needs the records)
            q = precise.resolve(conn, uid, q, today_) or q
        except Exception:
            log.exception("could not resolve the request; continuing")
    if is_admin:
        try:                                             # a new chat never continues a half-finished request from another chat
            with conn.transaction():
                old = smart.get_draft(conn.cursor(), uid, datetime.now(timezone.utc))
                if old and old.get("cid") and old.get("cid") != conversation_id:
                    smart.set_draft(conn.cursor(), uid, None, datetime.now(timezone.utc))
        except Exception:
            log.exception("could not clear the old draft")
    waiting = is_admin and _draft_waiting(conn, uid, q)   # smart.py asked something and this looks like the answer
    if waiting and ((answers.ACTION_START.match(q) or expert.SHOW.match(q)) and len(q.split()) >= 4):
        waiting = False                                   # a whole new command, not an answer to the pending question
    early = None
    try:                                                 # "what is this tab for?", "how do I log out?" — about the page the person is on
        q = pages.rewrite(q, page)
        if not waiting:
            early = pages.first(q, page, (context or {}).get("tab") if isinstance(context, dict) else None,
                                context if isinstance(context, dict) else {})
    except Exception:
        log.exception("page answers failed; continuing")
    if is_admin and not waiting and not early:           # "change cr color to blue" is a hallway shape, not the page theme
        try:
            early = precise.shape_first(conn, uid, q, today_)
        except Exception:
            log.exception("shape command failed; continuing")
    try:                                                 # "cancel", "what?", "ok": never merged with the previous question
        early = early or expert.control(conn, uid, q, page)
        if not early and not waiting:                    # "who are you", "who created this website", "my name is …", "scroll down"
            early = (understand.honesty(q, page) or expert.about_me(conn, uid, q, raw_low, page, context if isinstance(context, dict) else {}) or expert.screen_move(q, raw_low, page) or
                     expert.ui_command(q, raw_low, page) or expert.small_talk(conn, uid, q, raw_low, page))
    except Exception:
        log.exception("control words failed; continuing")
    if not early and not waiting:                        # one person's dates, a room's settings, bad records, how-to … (precise.py)
        try:
            early = precise.answer(conn, uid, q, today_, context if isinstance(context, dict) else {}, page)
        except Exception:
            log.exception("precise answers failed; continuing")
    # 2. short follow-ups ("what about next month?", "those for females?") reuse the previous question
    followed = False
    if allow_follow and not named and not early and not waiting and not expert.PERSON_ASK.search(q) and not (expert.PERSON_TRIG.search(q) and re.search(r"\b(present|history|named|called|staying)\b", q)) and not expert.definitions(q, page) and not expert.limits(q, page):
        q, followed = _follow_up(conn, uid, q, page, conversation_id)
    question = q
    command = bool(answers.ACTION_START.match(q))
    try:
        if not early and not waiting:
            early = expert.definitions(q, page) or expert.limits(q, page) or expert.curiosity(q, page, today_)
        if not early and is_admin and not waiting:       # Branch Admin only: the caller's OWN records, names included
            early = (expert.transfer_reason(q, raw_low) or (None if command else expert.room_report(conn, uid, q, today_)) or
                     (None if command else expert.admin_screen(conn, uid, q, today_, context if isinstance(context, dict) else {})) or
                     (None if command else expert.person_lookup(conn, uid, q, raw_low, today_)))
        if not early:
            early = expert.readonly_pages(conn, uid, q, page)
        if not early and page == "superadmin":
            early = expert.super_find(conn, uid, q) or expert.super_show(conn, uid, q)
        if not early and page == "marketing":
            early = expert.market_find(conn, uid, q)
    except Exception:
        log.exception("expert answers failed; continuing")
    try:
        early = early or (_recap(conn, uid, conversation_id, q) or answers.privacy_guard(q, page) or (None if (command and is_admin) else answers.money(q, page)) or
                 (answers.marketing(conn, uid, q, None) if page == "marketing" else None) or
                 (answers.superadmin(conn, uid, q, None) if page == "superadmin" and not (agent.NAV_VERB.match(q) and not agent.DATA_ASK.search(q)) else None))
    except Exception:
        log.exception("extra answers failed; continuing")
    if early:
        smart_reply = early
        blocks, nav, keep_log = early.get("blocks") or [], early.get("nav"), early.get("log", True)
    try:
        smart_reply = smart_reply or agent.handle(conn, uid, question, context)      # memory, navigation, reports
        if smart_reply:
            blocks, nav, keep_log = smart_reply.get("blocks") or [], smart_reply.get("nav"), smart_reply.get("log", True)
    except Exception:
        log.exception("agent layer failed; trying the smart layer")
        smart_reply = None
    try:                                                 # Dormitory Viewer: "show me what is vacant" also clicks the page filter
        if smart_reply and page == "viewer" and smart_reply.get("intent") not in ("privacy", "read_only", "denied", "clarify", "definition", "limitations",
                                                                                    "capabilities", "smalltalk", "cancelled", "ack", "unknown"):
            vnav, vlabel = expert.viewer_nav(q)
            had = (nav or {}).get("filters")
            if vnav and vlabel != "cleared" and not (nav or {}).get("roomId"):
                nav = dict(nav or {}, filters=dict(vnav["filters"], **(had or {})))
                smart_reply = dict(smart_reply, nav=nav)
                smart_reply["response"] = ("Done: the page now shows only %s. " % vlabel) + \
                    (("Report: " + smart_reply["response"]) if not had else "Every statistic now uses those beds.") + \
                    " Say “clear the filters” to see every room again."
    except Exception:
        log.exception("viewer filter failed; continuing")
    try:
        if not smart_reply and page in (None, "", "admin") and not _draft_waiting(conn, uid, q):
            today = smart.parse_iso((context or {}).get("today") if isinstance(context, dict) else None) or datetime.now(timezone.utc).date()
            extra = answers.admin(conn, uid, q, context or {}, today)  # data answers from the Branch Admin's OWN records
            if extra:
                smart_reply = extra
                blocks, nav = extra.get("blocks") or [], extra.get("nav")
    except Exception:
        log.exception("admin data answers failed; continuing")
    try:
        if not smart_reply and page in (None, "", "admin"):   # smart.py works on the caller's OWN rooms, Branch Admin page only
            smart_reply = smart.handle(conn, uid, question, context)
    except Exception:                                    # never lose the assistant over the extra layer
        log.exception("smart assistant layer failed; using the intent model")

    if smart_reply:
        tag, conf, text = smart_reply["intent"], 1.0, smart_reply["response"]
        action, suggestions = smart_reply["action"], smart_reply["suggestions"]
    if not smart_reply and page not in ("viewer", "marketing"):
        try:                                    # trained classifier, clear matches only (reports, comparisons, trends…)
            smart_reply = agent.fallback(conn, uid, question, context, strong_only=True)
        except Exception:
            log.exception("assistant fallback failed")
        if smart_reply:
            tag, conf, text = smart_reply["intent"], 1.0, smart_reply["response"]
            action, suggestions = smart_reply["action"], smart_reply["suggestions"]
            blocks, nav = smart_reply.get("blocks") or [], smart_reply.get("nav")
    if smart_reply:
        pass
    else:
        model = brain() if callable(brain) and not hasattr(brain, "answer") else brain
        tag, conf, text = model.answer(question)
        if tag in ("unknown", "offtopic") and page not in ("viewer", "marketing"):
            try:                                # trained classifier: other wordings and misspellings of known requests
                extra = agent.fallback(conn, uid, question, context)
            except Exception:
                log.exception("assistant fallback failed")
                extra = None
            if extra:
                smart_reply = extra
                tag, conf, text = extra["intent"], 1.0, extra["response"]
                action, suggestions = extra["action"], extra["suggestions"]
                blocks, nav = extra.get("blocks") or [], extra.get("nav")
    scope, stats = "tracker", None
    if smart_reply:
        if smart_reply.get("intent") == "offtopic":       # weather, news …: outside the tracker
            scope = "unrelated"
    elif tag == "unknown":
        scope = "uncertain"
        suggestions = smart.suggestions_for(context if isinstance(context, dict) else {})
    elif tag == "offtopic":
        scope = "unrelated"
    elif tag in LIVE_TAGS and page == "superadmin":
        text = ("That question is about one dormitory's rooms. On the Super Admin page I answer for the connected branches — try "
                "“how many vacant beds across all branches?” or “which branch has the most vacant beds?”.")
        scope = "uncertain"
    elif tag in LIVE_TAGS:
        try:
            stats = snapshot(conn, uid)
            text = live_answer(tag, stats)
        except Exception as error:
            print("live lookup failed:", error)
            text = "I couldn't read your live records just now. Open Room Canvas and use the status filter to see vacant beds."
            stats = None
    try:                                                 # Branch Admin: "show me the vacant rooms" also sets the screen filter
        if is_admin and not nav and action.get("type", "none") == "none" and tag in ("vacancy", "live_vacant", "contracts_overdue", "rooms_full", "reservations",
                                                                                     "data_temps", "data_overdue", "data_vacant", "live_overdue"):
            anav, alabel = expert.admin_nav(q, context if isinstance(context, dict) else {})
            if anav:
                nav = anav
                text += " I also set the screen filter to %s, so you can see them. Say “clear the filters” to see everything again." % alabel
    except Exception:
        log.exception("admin filter failed; continuing")
    # introduction: on "hi" / "who are you", and at the start of every new chat
    if smart_reply and smart_reply.get("intent") in ("limitations", "capabilities", "definition", "smalltalk", "cancelled", "ack", "name_saved", "name_recall",
                                                    "creator", "screen_move", "ui_command", "greeting", "identity", "person_search", "person_record", "person_contact", "room_report",
                                                    "screen_filter", "transfer_reason", "action_proposal", "clarify", "privacy", "read_only"):
        pass
    elif tag in ("greeting", "identity") or re.search(r"^(hi|hello|hey|good (morning|afternoon|evening)|who are you|what are you|who (made|created|built) you)\b", q):
        text, scope, tag = INTRO, "tracker", tag if tag in ("greeting", "identity") else "identity"
        action, blocks, nav = {"type": "none"}, [], None
    if greet and tag not in ("greeting", "identity"):      # "Good morning! …" gets a "Good morning!" back, then the answer
        text = greet + " " + text
    if read_notes and scope == "tracker" and tag not in ("unknown", "clarify", "limitations", "capabilities", "smalltalk", "privacy", "denied"):
        blocks = list(blocks) + [{"type": "note", "text": n} for n in read_notes]   # say how "except …" / "don't include …" was read
    if extra_blocks:
        blocks = list(blocks) + list(extra_blocks)
    if sub:                                              # part of a longer message: _answer_many saves the combined answer
        return {"response": text, "scope": scope, "action": action, "intent": tag, "confidence": round(conf, 3),
                "suggestions": suggestions, "blocks": blocks, "nav": nav, "english": q, "keep": keep_log}
    # first reply of a new chat: the browser shows the introduction as its own message before the answer
    intro = INTRO if (not isinstance(conversation_id, str) and keep_log and not text.startswith("Hello, I am") and
                      tag not in ("greeting", "identity", "creator", "name_saved", "name_recall")) else None
    if not keep_log:                                     # e.g. "clear my chat history": nothing to keep
        return {"response": text, "scope": scope, "action": action, "intent": tag, "confidence": round(conf, 3),
                "conversationId": None, "suggestions": suggestions, "blocks": blocks, "nav": nav}
    with conn.transaction():
        cid = _conversation(conn, uid, conversation_id, original)
        if is_admin:                                     # remember which chat a half-finished request belongs to
            try:
                pending = smart.get_draft(conn.cursor(), uid, datetime.now(timezone.utc))
                if pending and pending.get("cid") != cid:
                    smart.set_draft(conn.cursor(), uid, dict(pending, cid=cid), datetime.now(timezone.utc))
            except Exception:
                log.exception("could not tag the draft")
        cur = conn.cursor()
        cur.execute("INSERT INTO ai_messages (conversation_id, owner_uid, role, content) VALUES (%s,%s,'user',%s)", (cid, uid, original))
        cur.execute("INSERT INTO ai_messages (conversation_id, owner_uid, role, content, intent, confidence, scope) "
                    "VALUES (%s,%s,'assistant',%s,%s,%s,%s)", (cid, uid, text, tag, round(conf, 3), scope))
        if blocks or nav:
            cur.execute("SELECT id FROM ai_messages WHERE conversation_id=%s AND owner_uid=%s AND role='assistant' "
                        "ORDER BY id DESC LIMIT 1", (cid, uid))
            mid = cur.fetchone()["id"]
            cur.execute("INSERT INTO ai_message_extras (message_id, owner_uid, blocks) VALUES (%s,%s,%s)",
                        (mid, uid, Jsonb({"blocks": blocks, "nav": nav})))
        cur.execute("UPDATE ai_conversations SET updated_at=now() WHERE id=%s", (cid,))
        if stats is not None:
            data = {"rooms": stats["rooms"], "beds": stats["beds"], "vacant": stats["vacant"], "reserved": stats["reserved"],
                    "occupied": stats["occupied"], "overdue": len(stats["overdue"])}
            cur.execute("INSERT INTO ai_insights (owner_uid, kind, summary, data, conversation_id) VALUES (%s,%s,%s,%s,%s)",
                        (uid, tag, text, Jsonb(data), cid))
    if is_admin and scope == "tracker":                  # remember who this was about, for "when does she leave?" next
        precise.remember_person(conn, uid, q, text, cid)
    if scope == "tracker" and tag not in ("privacy", "clarify", "help", "greeting", "thanks", "goodbye", "cancelled", "ack", "smalltalk", "definition",
                                          "limitations", "capabilities", "identity", "clarify_cancelled", "transfer_reason", "creator", "name_saved", "name_recall",
                                          "screen_move", "ui_command", "person_search", "person_record", "person_contact"):
        _remember(conn, uid, q, page, cid)
    return {"response": text, "scope": scope, "action": action, "intent": tag, "intro": intro,
            "confidence": round(conf, 3), "conversationId": cid, "suggestions": suggestions, "blocks": blocks, "nav": nav}


def history(conn, uid, conversation_id, limit=100):
    cur = conn.cursor()
    cur.execute("SELECT m.id, m.role, m.content, m.intent, m.scope, m.created_at, x.blocks FROM ai_messages m "
                "LEFT JOIN ai_message_extras x ON x.message_id=m.id AND x.owner_uid=m.owner_uid "
                "WHERE m.owner_uid=%s AND m.conversation_id=%s ORDER BY m.id DESC LIMIT %s", (uid, conversation_id, limit))
    out = []
    for r in reversed(cur.fetchall()):
        extra = r["blocks"] if isinstance(r["blocks"], dict) else {}
        out.append({"role": r["role"], "content": r["content"], "intent": r["intent"], "scope": r["scope"],
                    "at": r["created_at"].isoformat(), "blocks": extra.get("blocks") or []})
    return out


def recent(conn, uid, limit=60):
    """The caller's most recent conversation (owner-filtered), so the chat continues across pages."""
    cur = conn.cursor()
    cur.execute("SELECT id FROM ai_conversations WHERE owner_uid=%s ORDER BY updated_at DESC LIMIT 1", (uid,))
    row = cur.fetchone()
    if not row:
        return {"conversationId": None, "messages": []}
    return {"conversationId": row["id"], "messages": history(conn, uid, row["id"], limit)}


INTRO = "Hello, I am an AI assistant created by the developer Mr. Hortelano, Terrins. I am here to help you."


# ------------------------------------------------------------------ follow-up questions and recap
FOLLOW = re.compile(r"^(what about|how about|and|also|what if|then|how bout)\b|^(those|them|that one|which of (those|them|these)|which one|the other)\b|"
                    r"\b(those rooms|these rooms|that room|that tenant|of those|of them|its|their)\b|(?<!is )(?<!are )\bthere\b(?! (is|are|any)\b)")
CARRY = [r"\broom\s*(?:no\.?|number|#)?\s*[a-z]?-?\d[\w-]*", r"\b(ground|first|second|third|fourth) floor\b", r"\b(female|male|mixed)\b",
         r"\b(students?|reviewees?)\b", r"\b(bed ?space|whole room)\b", r"\b(today|tomorrow|this week|next week|this month|next month|last month)\b"]
CORRECTION = re.compile(r"^(?:(?:no+|nope|nah|wait|sorry|oops|ay|ay mali|mali|dili|hindi|actually|hmm+|i mean)\b[\s,.!]*)+"
                        r"(?:(?:i (?:mean|meant)|make (?:it|that)|change (?:it|that) to|switch (?:it|that) to|instead|rather|should be|for)\b[\s,:]*)?"
                        r"(?:(?:not|dili|hindi) [a-z-]+[\s,]+(?:but |kundi |instead )?)?(?P<rest>.*)$|"
                        r"^(?:i (?:mean|meant)|make (?:it|that)|change (?:it|that) to|switch (?:it|that) to)\b[\s,:]*(?P<rest2>.*)$|"
                        r"^(?:not|dili|hindi) [a-z-]+[\s,]+(?:but |kundi |instead )?(?P<rest3>[a-z].*)$")
SUBJECT = re.compile(r"\b(rooms?|beds?|tenants?|residents?|branch\w*|dorm\w*|vacan\w*|occup\w*|reserv\w*|check ?outs?|check ?ins?|contracts?|"
                     r"reports?|summary|compare|trend|forecast|revenue|rent)\b")


def _follow_up(conn, uid, q, page, conversation_id=None):
    """-> (question to answer, True if it was completed from the previous question)."""
    try:
        cur = conn.cursor()
        last = (smart.load_settings(cur, uid).get("lastQ") or {})
    except Exception:
        return q, False
    lq = last.get("q") if isinstance(last, dict) else None
    try:
        fresh = lq and conversation_id and last.get("cid") == conversation_id and last.get("page") == (page or "admin") and (datetime.now(timezone.utc).timestamp() - float(last.get("at") or 0)) < 1800
    except (TypeError, ValueError):
        fresh = False
    if not fresh:
        return q, False
    words = q.split()
    # a correction of the last question: "no wait, I meant female", "actually make it reviewees", "not male, female"
    m = CORRECTION.match(q)
    rest = (m.group("rest") or m.group("rest2") or m.group("rest3") or "") if m else ""
    if rest and rest != q and not understand.REQUEST_START.match(rest) and any(re.search(p, rest) for p in SLOTS + CARRY):
        rest = rest.strip(" ?.!")
        return (_swap(lq, rest) + " " + rest).strip(), True
    if FOLLOW.search(q) and (len(words) <= 9 or not SUBJECT.search(re.sub(r"^(what about|how about|and|also)\s+", "", q))):
        rest = re.sub(r"^(what about|how about|and|also|then)\s+", "", q).strip(" ?")
        return (_swap(lq, rest) + " " + rest).strip(), True
    # a very short message continues the last question only when it carries a filter, a date or a room ("female", "next month", "room 5")
    if len(words) <= 3 and not SUBJECT.search(q) and any(re.search(p, q) for p in CARRY + [r"\b(ac|aircon\w*|non-?ac)\b", r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b", r"\b(yesterday|tonight|weekend)\b"]):
        return (_swap(lq, q) + " " + q.strip(" ?")).strip(), True
    if len(words) <= 7 and re.search(r"\b(also|too|pud|din|rin|again|there|that one|same)\b", q):
        extra = [m.group(0) for p in CARRY for m in [re.search(p, lq)] if m and not re.search(p, q)]
        if extra:
            return (q.strip(" ?") + " " + " ".join(extra)).strip(), True
    return q, False


SLOTS = [r"\b(females?|males?|mixed|girls?|boys?|women|men|ladies)\b", r"\b(students?|reviewees?)\b", r"\b(bed ?spacers?|bed ?space|whole room)\b",
         r"\b(today|tomorrow|tonight|this week|next week|this month|next month|last month|this weekend)\b",
         r"\broom\s*(?:no\.?|number|#)?\s*[a-z]?-?\d[\w-]*", r"\b(ground|first|second|third|fourth) floor\b",
         r"\b(vacan\w*|overdue|reserved?|temporary|occupied)\b"]


def _swap(last_q, new):
    """'…for female students' + 'what about male' -> the old gender is dropped so the new one wins."""
    out = last_q
    for p in SLOTS:
        if re.search(p, new):
            out = re.sub(p, " ", out)
    # "how many vacant in room s-106" + "what about the male rooms": a whole group of rooms replaces the one room
    if re.search(r"\brooms\b", new) and not re.search(SLOTS[4], new):
        out = re.sub(SLOTS[4], " ", out)
    return re.sub(r"\s+", " ", out).strip()


def _remember(conn, uid, q, page, cid=None):
    try:
        with conn.transaction():
            cur = conn.cursor()
            st = smart.load_settings(cur, uid)
            st["lastQ"] = {"q": q[:300], "page": page or "admin", "cid": cid, "at": datetime.now(timezone.utc).timestamp()}
            smart.save_settings(cur, uid, st)
    except Exception:
        log.exception("could not remember the last question")


def _draft_waiting(conn, uid, q):
    """A half-finished request (smart.py asked a question) and the reply is not a new question."""
    try:
        d = smart.get_draft(conn.cursor(), uid, datetime.now(timezone.utc))
    except Exception:
        return False
    return bool(d) and not answers.QUESTIONISH.search(q)


def _recap(conn, uid, conversation_id, q):
    if not re.search(r"\b(summary|summari[sz]e|recap)\b.*\b(everything|what|all)\b.*\b(discussed|talked|asked|said|we did)\b|\brecap\b", q):
        return None
    if not isinstance(conversation_id, str):
        return agent.reply("recap", "We haven't talked about anything yet in this chat.")
    rows = history(conn, uid, conversation_id, 40)
    pairs, qtext = [], None
    for m in rows:
        if m["role"] == "user":
            qtext = m["content"]
        elif qtext:
            pairs.append("%s → %s" % (qtext, (m["content"] or "").split(". ")[0][:140]))
            qtext = None
    if not pairs:
        return agent.reply("recap", "We haven't talked about anything yet in this chat.")
    return agent.reply("recap", "Here's what we covered (%d question%s):" % (len(pairs), "" if len(pairs) == 1 else "s"),
                       [{"type": "list", "items": pairs[-15:]}], log=True)
