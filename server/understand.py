"""Reads the WHOLE message before the assistant's rules answer it.

The rule layers (expert.py, answers.py, smart.py, agent.py) each answer ONE request, and most of them look for the
first thing they recognise. Real messages are often longer than that:

  * several requests in one message      "how many vacant beds, who is overdue, and any reservations next week?"
  * conditions spread over the sentence  "check the vacant rooms … but don't include the ones with someone coming in … male only"
  * negations                            "vacant rooms except the female rooms"
  * questions about the assistant itself "can you read this file?", "do you see live data?", "can you email the tenants?"

This module only reads and rewrites; it never touches data. No outside service is used.

    split(text)       -> the separate requests in a message (conditions stay with the request they belong to)
    exclusions(text)  -> (english text the rules understand, notes telling the user how a negation was read)
    honesty(text, page) -> an honest answer about what the assistant can and cannot do, or None
"""
import re

import agent
import lang

MAX_CHARS = 2000          # longest message read in full (the server tells the user when a message is longer)
MAX_PARTS = 4             # requests answered from one message; the rest are named, never silently dropped

# ------------------------------------------------------------------------------------------- splitting
# what a request is about; two pieces about the same thing are one request with extra conditions
TOPICS = [
    ("vacancy", r"\b(can|could) (be |still be )?(reserv|book)\w*|\b(reservable|bookable)\b|\bavailable (to|for) (reserv|book)\w*|"
                r"\bvacan\w*|\bavailable\b|\bavailability\b|\bfree (beds?|rooms?|slots?)\b|\bempty\b|\baccommodate\b|\bspace for\b"),
    ("overdue", r"\boverdue\b|\bpast (their |the )?check ?-?outs?\b|\blate (tenants?|check ?outs?)\b"),
    ("checkout", r"\bcheck ?-?outs?\b|\bcheckouts?\b|\bleaving\b|\bmoving out\b|\bexpir\w*\b|\bcontracts?\b"),
    ("reservations", r"\breserv\w*|\bbookings?\b|\bcheck ?-?ins?\b|\bcheckins?\b|\barriv\w*|\bincoming\b|\bcoming in\b"),
    ("occupancy", r"\boccupan\w*|\boccupied\b|\bhow full\b|\bfull\b"),
    ("tenants", r"\b(tenants?|residents?|boarders?)\b"),
    ("money", r"\b(unpaid|paid|payments?|rent|revenue|income)\b"),
    ("report", r"\b(report|summary|summari[sz]e|overview)\b"),
    ("temporary", r"\btemporary\b|\bguests?\b"),
    ("history", r"\bhistory\b"),
    ("people", r"^who\b|\bwho (is|are|lives?|stays?)\b|\bnames?\b|\bstaying\b|\bliving\b"),
]
REQUEST_START = re.compile(r"^(please |pls |also |and |then |tapos |plus )*(how many|how much|how|who|whos|which|what|whats|when|where|why|"
                           r"is there|are there|is it|are any|do (we|i|you)|does|did|can (you|u|i|we)|could you|show|list|tell|give|check|"
                           r"count|find|display|any|i need|i want|let me know|report|summari[sz]e|compare)\b")
CONDITION = re.compile(r"^(but |and |also |then |plus )*(do not|dont|don't|not|never|except|excluding|exclude|without|only|no |skip|"
                       r"apart from|other than|besides|leave out|ignore|just|unless|if|that|which (are|is|have|has)|with|for|on|in|from|until|by)\b")
COMMAND = re.compile(r"^(please )?(check (in|out)|checkin|checkout|reserve|book|add|create|delete|remove|move|transfer|extend|cancel|update|"
                     r"change|set|edit|rename|put|assign|mark|make|clear|forget|remember|go to|open|scroll|slide)\b")
HARD = re.compile(r"(?<=[?;!\n])\s*|(?<=[a-z0-9)])\.\s+(?=[a-z])", re.I)
SOFT = re.compile(r"\s*,\s*(?:and |then |also |tapos |ug |at |plus )?|\s+(?:and|tapos|then|ug|plus)\s+(?=\S)|\s+and also\s+|\s+also\s+(?=(?:how|who|which|what|show|list|tell|check|give)\b)", re.I)
LEAD = re.compile(r"^(?:and|also|then|tapos|plus|ug|at|but)\s+", re.I)


GREETING = re.compile(r"^\s*(hi+|hello+|hey+|hiya|yo|good (?:morning|afternoon|evening|day)|maayong (?:buntag|hapon|gabii|udto|adlaw)|"
                      r"magandang (?:umaga|hapon|gabi|araw)|kumusta|kamusta|musta)\b(?:[\s,]+(?:there|po|sir|ma'?am|boss|bot|assistant|everyone|team|again))*"
                      r"[\s,!.]*(?:(?:so|um+|uh+|ok(?:ay)?|well)\b[\s,]*)?", re.I)
GREET_BACK = {"morning": "Good morning!", "buntag": "Good morning!", "umaga": "Good morning!", "afternoon": "Good afternoon!", "hapon": "Good afternoon!",
              "udto": "Good afternoon!", "evening": "Good evening!", "gabii": "Good evening!", "gabi": "Good evening!"}
# small talk around the real request: never answered as a request of its own
PLEASANTRY = re.compile(r"^(thanks?( you)?|thank u|ty|thx|tnx|salamat( po| kaayo)?|daghang salamat|maraming salamat|ok(ay)?|cool|nice|great|please|pls|"
                        r"busy day( today)?|hope (you('re| are)|ur) (well|ok|good)|sorry to bother( you)?|quick question|i have (a few|some|several|many|\d+) "
                        r"questions?|please help( me)?|help me( out)?|anyway|so|um+|uh+)( a lot| so much| po| kaayo)?[\s!.,]*$", re.I)
MARKERS = re.compile(r"(^|[.?!;]\s*|,\s*)(?:and\s+)?(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|fourth(?:ly)?|next|lastly|finally|last but not least|"
                     r"one more thing|another thing|una|ikaduha|ikatlo|pangalawa|pangatlo|panghuli|katapusan)\s*[,:]\s*", re.I)


def greeting(text):
    """'Good morning! how many vacant beds?' -> ('Good morning!', 'how many vacant beds?'). Only when a real request follows."""
    m = GREETING.match(text or "")
    if not m:
        return None, text
    rest = text[m.end():].strip()
    if len(rest.split()) < 2:
        return None, text                             # just "hello": the greeting itself is the message
    word = m.group(1).lower().split()[-1]
    return GREET_BACK.get(word, ""), rest


def topic_of(english):
    for name, pat in TOPICS:
        if re.search(pat, english):
            return name
    return None


def _en(piece):
    return lang.to_english(piece) or piece.lower()


def split(text):
    """-> list of separate requests (original wording kept, so names and language survive).
    A single request, a command, or anything doubtful comes back as ONE piece: the existing rules then handle it as before."""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(raw) < 25:
        return [raw] if raw else []
    marked = MARKERS.sub(lambda m: m.group(1) if m.group(1).strip() in (".", "?", "!", ";", "") else ". ", raw)
    pieces = []                                       # (original, english, hard_start)
    for sentence in [s for s in HARD.split(marked) if s and s.strip()]:
        parts = [p for p in SOFT.split(sentence) if p and p.strip()]
        for i, p in enumerate(parts):
            p = p.strip(" ,")
            if p and not PLEASANTRY.match(p) and not (GREETING.match(p) and GREETING.match(p).end() >= len(p.rstrip(" !.,"))):
                pieces.append((p, _en(p), i == 0))
    if len(pieces) < 2:
        return [raw]
    def is_command(en):
        body = LEAD.sub("", en)
        return bool(COMMAND.match(body)) and not re.match(r"^(please )?check\b(?! (in|out))", body)
    if sum(1 for _o, en, _h in pieces if is_command(en)) > 1:
        return [raw]                                  # several changes at once: one request, as before (the confirm flow asks)
    groups = []                                       # [[originals], english, topic, is_command]
    for orig, en, hard in pieces:
        body = LEAD.sub("", en)
        topic = topic_of(body)
        cmd = is_command(en)
        starts = bool(REQUEST_START.match(body)) or cmd
        cond = bool(CONDITION.match(en)) or bool(CONDITION.match(body))
        if cmd:                                       # "… and check out Ana": the change is its own request
            if groups and groups[-1][2] is None:      # only small talk before it: it belongs to the change
                groups[-1][0].append(orig)
                groups[-1][1] += " " + en
                groups[-1][2], groups[-1][3] = "command", True
            else:
                groups.append([[orig], en, "command", True])
            continue
        if groups and (cond or not (starts or hard) or topic is None or topic == groups[-1][2] or
                       (groups[-1][2] is None)) and not (groups[-1][3] and starts and topic):
            g = groups[-1]
            g[0].append(orig)
            g[1] += " " + en
            g[2] = g[2] or topic
            continue
        groups.append([[orig], en, topic, False])
    if len(groups) < 2:
        return [raw]
    return [LEAD.sub("", ", ".join(g[0]).strip(" ,")) for g in groups]


def commands(text):
    """The separate changes asked for in one message ("check out Ana and transfer Ben to S-122" -> two)."""
    raw = re.sub(r"\s+", " ", str(text or "")).strip()
    out = []
    for sentence in [s for s in HARD.split(raw) if s and s.strip()]:
        for p in [p for p in SOFT.split(sentence) if p and p.strip()]:
            body = LEAD.sub("", _en(p))
            if COMMAND.match(body) and not re.match(r"^(please )?check\b(?! (in|out))", body):
                out.append(LEAD.sub("", p.strip(" ,")))
            elif out and (CONDITION.match(body) or not REQUEST_START.match(body)):
                out[-1] += ", " + p.strip(" ,")          # "… with a good record": still the same change
    return out


# ------------------------------------------------------------------------------------------- negations
_NEG = r"(?:except(?: for)?|excluding|exclude|without|but not|not including|other than|apart from|besides|do not include|dont include|" \
       r"do not show|dont show|leave out|skip|ignore|minus|not|no)"
_ART = r"(?:for |in )?(?:the |any |those |all |all the )?"
_GENDER = {"female": "male", "male": "female"}
_GROUP = {"students": "reviewees", "reviewees": "students"}


def exclusions(english):
    """'vacant rooms except the female rooms' -> ('vacant rooms male', [note]).
    Every room is Male, Female or Mixed (and Students, Reviewees or Mixed), so leaving one out is the same as asking
    for the other one: the rules then pick the other kind plus mixed rooms. The note tells the user how it was read."""
    t, notes = english, []
    m = re.search(r"\b" + _NEG + r"\s+" + _ART + r"(female|male)s?(?:[- ]only)?(?: rooms?| beds?| ones?| tenants?)?\b", t)
    if m:
        gone, keep = m.group(1), _GENDER[m.group(1)]
        t = (t[:m.start()] + " " + t[m.end():]).strip()
        if not re.search(r"\b%s\b" % keep, t):
            t += " " + keep
        notes.append("I left out the %s-only rooms, so this shows %s and mixed rooms." % (gone, keep))
    m = re.search(r"\b" + _NEG + r"\s+" + _ART + r"(students?|reviewees?)(?: rooms?| beds?| ones?)?\b", t)
    if m:
        gone = m.group(1).rstrip("s") + "s"
        keep = _GROUP[gone]
        t = (t[:m.start()] + " " + t[m.end():]).strip()
        if not re.search(r"\b%s?\b" % keep.rstrip("s"), t):
            t += " " + keep
        notes.append("I left out the %s-only rooms, so this shows %s and mixed rooms." % (gone.rstrip("s"), keep.rstrip("s")))
    # "vacant beds but not the reserved ones": reserved beds are never counted as vacant, so nothing changes; just say so
    m = re.search(r"\b(?:but )?" + _NEG + r"\s+" + _ART + r"(?:reserved|booked|held)(?: ones| beds?)?\b(?! rooms?)", t)
    if m and not re.search(r"\brooms? (?:that|which|with)\b", t[max(0, m.start() - 30):m.start()]):
        t = (t[:m.start()] + " " + t[m.end():]).strip()
        notes.append("Reserved beds are never counted as vacant, so they're already left out.")
    # rooms where someone is already due to arrive (a reservation or a temporary guest)
    m = re.search(r"\b" + _NEG + r"\b[^.?!;]{0,60}?\b(?:someone|somebody|anyone|people|a tenant|tenants|guests?|a guest|reservations?|reserved|booked|"
                  r"bookings?|on hold|held)\b(?:[^.?!;]{0,25}?\b(?:coming in|coming|arriving|check(?:ing)? in|moving in|reserved|booked|incoming))?", t)
    if m and re.search(r"reserv|book|coming|arriv|check|moving in|incoming|hold|held", m.group(0)):
        t = (t[:m.start()] + " " + t[m.end():]).strip() + " excluding incoming"
        notes.append("I left out every room that already has a reservation or a guest due to arrive.")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\b(but|and) (?=(and|but)\b)|\s(but|and)$", "", t).strip()
    return t, notes


# ------------------------------------------------------------------------------------------- honest answers about the assistant
HOW_I_WORK = ("I run on this app's own server and work with rules and a small trained language model built for dormitory questions — not a general "
              "chatbot like ChatGPT, and no outside AI service. I fix spelling, understand English, Tagalog, Cebuano and mixes, and then read your "
              "records to answer.")

HONEST = [
    ("files",
     r"\b(read|open|see|view|check|scan|analy[sz]e|look at|process|understand)\b.*\b(files?|attachments?|documents?|pdfs?|images?|photos?|pictures?|"
     r"screenshots?|excel|spreadsheets?|word docs?|uploads?|uploaded)\b|\b(can|do) (you|u) (accept|take|handle) (files?|attachments?|uploads?)\b",
     "No — I can't open files, photos or attachments, and nothing you attach in this chat reaches me. I only read the text you type and the records "
     "saved in the tracker. Tenant documents you upload on a tenant's record are stored safely, but I can't read what is inside them. If you paste "
     "the text you need into the chat, I'll work with that."),
    ("realtime",
     r"\b(real[- ]?time|live|up[- ]to[- ]date|latest|current) (data|records|information|numbers|counts|database)\b|\b(access|connected) to (the |your |my )?"
     r"(database|records|data)\b|\bis (this|that|your answer) (live|real|current|up to date|accurate)\b|\bwhere do (the|your) numbers come from\b",
     "Yes, for your own dormitory. Every count I give comes from the records saved on the server at the moment you ask — I don't use old copies or "
     "guess numbers. Two limits: I only see what is saved (unsaved edits on another screen aren't included), and I only see the records your page "
     "is allowed to see. On the Branch Admin page that's your own branch; viewers, marketing and Super Admin pages never get tenant names."),
    ("outside",
     r"\b(send|email|e-mail|text|sms|message|call|notify|remind|post|share)\b.{0,40}\b(email|e-mail|sms|text messages?|texts?|messenger|facebook|"
     r"viber|whatsapp|phone|tenants?|guardians?|parents?)\b.*$|\b(search|browse|look up|google)\b.{0,20}\b(internet|web|online|google)\b|"
     r"\b(internet|online|web) (access|search)\b",
     "I can't do that. I can't send emails, text messages or notifications, and I can't browse the internet — I only work inside this tracker. "
     "What I can do: list the tenants you want to contact with their saved contact numbers (Branch Admin page only), so you can reach them yourself."),
    ("misunderstand",
     r"\bwhy (can ?not|cant|can't|do not|dont|don't|did not|didnt|didn't|won't|wont|do) (you|u)\b.*\b(understand|get|answer|know|see|read)\b|"
     r"\b(you|u) (do not|dont|don't|did not|didnt|didn't) (understand|get it|get me)\b|\bwhy (is|was) (your|the) answer wrong\b",
     HOW_I_WORK + " So I can still misread a question, especially very unusual wording, a name I've never seen, or something the tracker doesn't "
     "record (like rent or payments). What helps most: name the thing you want (vacant beds, a room number, a tenant's name, a date), and if my "
     "answer is off, tell me what you meant — you don't need special commands or perfect grammar."),
    ("memory",
     # NOT "what do you remember (about me)": agent.py lists the saved preferences for that
     r"\bhow (long|much) (do|can|will) (you|u) remember\b|\bdo (you|u) (remember|forget) (our|the|this|previous|old) (chats?|conversations?|messages?)\b",
     "Inside a chat I keep track of what we were talking about, so you can say “what about the male rooms?” or “that room”. I can also keep a few "
     "preferences you ask me to remember. I don't remember other users' chats, and a new chat starts fresh. Your saved records always win over "
     "anything I remember."),
    ("length",
     r"\b(how long|how many (words|characters|letters)|max(imum)?|limit)\b.*\b(message|question|text)\b|\b(long|longer) (messages?|questions?)\b",
     "You can send up to %d characters in one message, and I read all of it — including several questions or conditions at once. If a message is "
     "longer, I tell you exactly where I stopped reading instead of pretending I saw the rest." % MAX_CHARS),
]


# tenant details the app has no field for (a tenant record holds: name, contact, address, 2 emergency contacts, photo, documents)
UNTRACKED = re.compile(r"\b(birthdays?|birth ?dates?|date of birth|ages?|how old|schools?|course|university|college|nationality|religion|"
                       r"occupation|jobs?|salary|email address(es)?|e-?mail|facebook|allerg\w*|medical|blood type)\b")
UNTRACKED_LABEL = {"birthday": "birthdays", "birth": "birth dates", "birthdate": "birth dates", "date": "birth dates", "age": "ages",
                   "how": "ages", "school": "schools", "course": "courses", "university": "schools", "college": "schools",
                   "email": "email addresses", "e-mail": "email addresses", "job": "jobs", "allergy": "medical details",
                   "allergie": "medical details", "medical": "medical details", "blood": "medical details"}
WORLD = re.compile(r"\b(weather|rain(ing)?|typhoon|temperature outside|news|traffic|stock market|exchange rate|basketball|lotto)\b")


def honesty(english, page=None):
    """Specific, honest answers about what the assistant can access and do. -> agent.reply or None."""
    t = (english or "").lower().strip(" ?!.")
    if WORLD.search(t) and not re.search(r"\b(rooms?|beds?|tenants?|vacan\w*|reserv\w*|dorm\w*)\b", t):
        return agent.reply("offtopic", "I can't check that — I have no internet access, so I don't know about weather, news or anything outside this "
                           "tracker. Ask me about your rooms, beds, tenants, reservations or check-outs instead.", log=True)
    m = UNTRACKED.search(t)
    if m and not re.search(r"\b(send|notify|text|message|call|remind|post)\b", t) and re.search(r"\b(tenants?|residents?|boarders?|guests?|his|her|their|room|bed|s-?\d+|whose|who)\b|'s\b", t):
        field = m.group(0)
        return agent.reply("not_tracked", "The tracker doesn't record %s, so I can't tell you that — and I won't guess. For each tenant it keeps: "
                           "full name, contact number, home address, up to two emergency contacts, a photo and uploaded documents, plus their room, "
                           "bed, stay dates and resident type." % UNTRACKED_LABEL.get(field.split()[0].rstrip("s"), field), log=True)
    if not re.search(r"\b(you|your|u|ur|assistant|ai|bot|chat)\b", t) and not re.search(r"^(can|could|is|are|do|does)\b", t):
        return None
    for name, pat, text in HONEST:
        if re.search(pat, t):
            return agent.reply("limitations", text, log=True)
    return None


def plural_note(n_parts, extra):
    if not extra:
        return None
    return ("Your message had more than %d separate requests. I answered the first %d; still open: %s. Send those again and I'll answer them."
            % (n_parts, n_parts, "; ".join("“%s”" % x for x in extra)))
