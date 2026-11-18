"""The assistant's extra understanding.

  * control words   "cancel", "stop", "what?" always work and never start a loop
  * definitions     "is a reserved bed considered occupied?", "what does overdue mean?"
  * limits          "what are your limitations?" gets a real answer for the page you are on
  * room reports    "how many vacant / overdue / reserved / temporary in S-105" (Branch Admin)
  * people          "is Terrins present?", "find Terrins in the history" (Branch Admin ONLY)
  * screen commands "show me only the vacant beds" sets the page filter and reports what it shows
  * Super Admin     "find Sanciangko dorm" types it in the search bar and reports that dormitory

Privacy: tenant names and numbers are read here only for the Branch Admin's own records. The Dormitory
Viewer and Marketing pages never reach the functions that read people."""
import difflib
import re
from datetime import datetime, timedelta, timezone

import agent
import smart
from store import KINDS, list_docs

R = agent.reply

VERB = (r"add|create|check ?in|checkin|check ?out|checkout|reserve|book|move|transfer|extend|cancel|delete|remove|show|find|search|"
        r"look|list|give|tell|open|go|filter|display|report|put|assign|set|change|update|mark|make|locate|count|write|fill|type|"
        r"enter|generate|clear|reset|hide|see|view|get|explain|describe|summari[sz]e|compare|rename|edit|take|scroll|slide|swipe|build|register|insert")
POLITE = re.compile(r"^(?:(?:hey|hi|hello|ok|okay|so|and|now|then)[ ,]+)?(?:(?:please|kindly|pls|plz)[ ,]+)?"
                    r"(?:(?:can|could|would|will|may) (?:you|u)(?: please| kindly| also| now| just)?(?: help me(?: to)?)? |"
                    r"i (?:want|need|would like) (?:you )?to |i wanna |help me (?:to )?|let me |lets |let us )"
                    r"(?=(?:%s)\b)" % VERB)


VERB_WORDS = ["add", "create", "reserve", "book", "move", "transfer", "extend", "cancel", "delete", "remove", "show", "find", "search", "look", "list", "give", "open",
              "filter", "display", "report", "assign", "change", "update", "locate", "count", "write", "generate", "clear", "reset", "hide", "view", "describe",
              "compare", "rename", "edit", "scroll", "slide", "checkout", "checkin"]


def command_form(q):
    """'can you add …', 'please show …', 'i want you to check out …' -> the plain command."""
    t = (q or "").strip()
    # a misspelled command word right after "can you" is fixed first: "can you fnd …" -> "can you find …"
    m = re.match(r"^((?:(?:hey|hi|hello|ok|okay|so|and|now|then)[ ,]+)?(?:(?:please|kindly|pls|plz)[ ,]+)?(?:(?:can|could|would|will|may) (?:you|u)(?: please| kindly| also| now| just)? |"
                 r"i (?:want|need|would like) (?:you )?to |please |kindly |pls ))([a-z]{3,9})\b", t)
    if m and not re.fullmatch(VERB, m.group(2)) and m.group(2) not in ("help", "tell", "explain", "know", "have", "the", "you", "not", "also", "check", "say", "speak",
                                                                       "understand", "read", "hear", "talk", "learn", "remember", "forget", "access", "share",
                                                                       "send", "print", "export", "save", "undo", "repeat", "stop", "wait", "just", "even", "ever",
                                                                       "still", "really", "please", "like", "work", "think", "guess", "answer", "reply", "translate"):
        near = difflib.get_close_matches(m.group(2), VERB_WORDS, n=1, cutoff=0.74)
        if near and near[0][0] == m.group(2)[0]:
            t = m.group(1) + near[0] + t[m.end():]
    t2 = POLITE.sub("", t, count=1)
    t2 = re.sub(r"^(please|kindly|pls|plz)[ ,]+(?=(?:%s)\b)" % VERB, "", t2)
    return t2 if t2 else t


ROOM_TOKEN = re.compile(r"(?<![\w-])(?<!room )(?<!rooms )(?<!room no )(?<!room number )([a-z]{1,3}-?\d{2,4}[a-z]?)(?![\w-])")
NOT_ROOM = re.compile(r"^(a|an|by|in|on|to|at|of|is|or|it|if|up|no|so|we|us|my|me|do|as|be|bed|for|the|and|day|top|q|h)-?\d")


def name_rooms(q):
    """'how many vacant in s-105' -> '... in room s-105' (a bare room name gets the word room)."""
    def fix(m):
        tok = m.group(1)
        if NOT_ROOM.match(tok) or re.match(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", tok):
            return tok
        return "room " + tok
    t = ROOM_TOKEN.sub(fix, q or "")
    # "in 105", "sa 105", "of 105": three or four digits right after a place word, not a year
    t = re.sub(r"\b(in|inside|sa|at|of|for) (?!20\d\d\b)(\d{3,4})(?= |$|\?)(?! (beds?|days?|rooms?|tenants?|weeks?|months?|people|persons?|percent))", r"\1 room \2", t)
    return t


# ------------------------------------------------------------------------------------------ control words
CANCEL = re.compile(r"^(cancel( (it|that|this|the request|everything))?|never ?mind|nvm|stop( (it|that|asking))?|forget (it|that)|no thanks?|nope|quit|exit|"
                    r"abort|do not|dont|don't|leave it|skip( it)?|wag na|ayaw na|huwag na|ayaw|undo that|enough|no more|go back)\b[ .!]*(please)?[ .!]*$")
CONFUSED = re.compile(r"^(what|huh|ha|eh|unsa|ano|hmm+|h+m+|\?+|what do you mean|what is that|i (do not|dont|don't) (understand|get it)|"
                      r"i am confused|confusing|pardon|sorry|come again|say (that )?again|repeat( that)?|unsa man|ano daw|what are you (saying|asking))[ ?!.]*$")
ACK = re.compile(r"^(ok|okay|k|kk|alright|all right|sige|cge|got it|i see|noted|nice|good|great|cool|wow|fine|sure|yes|yep|yeah|oo|no)[ .!]*$")


def control(conn, uid, q, page):
    """Short control messages. They never repeat the previous answer and never keep a question loop alive."""
    t = (q or "").strip().lower()
    now = datetime.now(timezone.utc)
    cur = conn.cursor()
    if page in (None, "", "admin"):
        try:
            draft = smart.get_draft(cur, uid, now)
        except Exception:
            draft = None
    else:
        draft = None
    if CANCEL.match(t):
        if draft:
            with conn.transaction():
                smart.set_draft(cur, uid, None, now)
            return R("cancelled", "Okay, cancelled. Nothing was changed.")
        return R("cancelled", "Okay. Nothing is in progress and nothing was changed.")
    if CONFUSED.match(t):
        if draft:
            return R("clarify", "Sorry for the confusion. I was in the middle of your request and asked: “%s” "
                     "Answer that, or say “cancel” to stop." % smart._repeat_question(draft).replace(" (Say 'cancel' to stop.)", ""))
        return R("clarify", "Sorry, let me be clearer. Ask me in your own words, for example “how many vacant beds in Room S-105?” "
                 "or “what can you do?”.")
    if ACK.match(t) and not draft:
        return R("ack", "Okay. Tell me if you need anything else.")
    return None


# ------------------------------------------------------------------------------------------ definitions
ST = r"(vacan\w*|occupied|reserved?|reservations?|temporary|temp|overdue|upcoming|checkout soon|full)"
DEFS = [
    # (pattern, answer)
    (r"\b(reserv\w*)\b.*\b(consider\w*|count\w*|same as|treated|part of|included?|mean\w*|is it|still)\b.*\b(occup\w*|vacan\w*|free|available)\b|"
     r"\b(is|are|does|do)\b.*\breserv\w*\b.*\b(occup\w*|vacan\w*|free|available)\b|\b(occup\w*|vacan\w*)\b.*\b(includ\w*|count\w*)\b.*\breserv\w*",
     "A reserved bed counts as occupied, not vacant. It is being held for a client who is about to move in, so nobody else can take it. "
     "On the Room Canvas it shows “Occupied · Reserved”, and the Reserved number tells you how many of the occupied beds are held that way."),
    (r"\b(temporary|temp|short[- ]stay)\b.*\b(consider\w*|count\w*|same as|treated|part of|included?|mean\w*|is it|still)\b.*\b(occup\w*|vacan\w*|free|available)\b|"
     r"\b(is|are|does|do)\b.*\b(temporary|temp)\b.*\b(occup\w*|vacan\w*|free|available)\b|\b(occup\w*|vacan\w*)\b.*\b(includ\w*|count\w*)\b.*\btemporar\w*",
     "A bed used by a temporary client counts as occupied, not vacant. Someone is sleeping there, even if only for a short stay. "
     "It becomes vacant again when the temporary client is checked out."),
    (r"\boverdue\b.*\b(consider\w*|count\w*|same as|treated|included?|still|is it)\b.*\b(occup\w*|vacan\w*|free|available)\b|\b(is|are)\b.*\boverdue\b.*\b(occup\w*|vacan\w*)\b",
     "An overdue bed is still occupied. The tenant's check-out date has passed but they have not been checked out, so the bed is not vacant yet. "
     "Extend the stay or check the tenant out in Checkout Reminders."),
    (r"\b(upcoming( vacan\w*)?|checkout soon|check ?out soon|leaving soon)\b.*\b(consider\w*|count\w*|same as|treated|included?|still|is it)\b.*\b(occup\w*|vacan\w*|free|available)\b|"
     r"\b(is|are)\b.*\bupcoming\b.*\b(occup\w*|vacan\w*)\b",
     "An upcoming vacancy is still occupied today. It only means the tenant's check-out date is within 7 days, so the bed will be free soon. "
     "It is counted as vacant only after the tenant is checked out."),
    (r"\b(is|are|does|do|can)\b.*\bvacan\w*\b.*\b(consider\w*|count\w*|same as|treated|mean\w*)\b.*\boccup\w*|\bvacan\w*\b.*\b(is|same as)\b.*\boccupied\b",
     "No. Vacant and occupied are opposites. A vacant bed has no tenant, no reservation and no temporary client, so it can be given to someone right now. "
     "Occupied means a tenant, a reserved client or a temporary client holds the bed."),
    (r"\b(what|whats|meaning|mean|define|definition|explain)\b.*\b(counts?|consider\w*)\b.*\boccupied\b|\bwhat (is|are|does) (an? )?occupied( beds?)?( mean)?\b|"
     r"\b(meaning|definition) of occupied\b|\bdefine occupied\b|\bwhich beds? (are|is|count as) occupied\b.*\b(mean|count|consider)\w*",
     "Occupied means the bed cannot be given to a new person today. That covers four cases: a tenant is staying, the bed is reserved for a client, "
     "a temporary client is using it, or the tenant is overdue (past the check-out date but still there)."),
    (r"\b(difference|different|compare|vs|versus)\b.*\breserv\w*\b.*\btemporar\w*|\b(difference|different|compare|vs|versus)\b.*\btemporar\w*\b.*\breserv\w*",
     "A reserved client has not arrived yet: the bed is only being held until the check-in date. A temporary client is already staying, for a short time, "
     "in a bed that is free. Both count as occupied, because in both cases the bed cannot be given to someone else."),
    (r"\b(difference|different|compare|vs|versus)\b.*\b(bed ?space\w*)\b.*\bwhole room\b|\b(difference|different|vs|versus)\b.*\bwhole room\b.*\bbed ?space\w*|"
     r"\bwhat (is|does) (a )?(bed ?space\w*|whole room)( mean)?\b",
     "Bedspace means each bed is rented separately, so strangers can share the room. Whole Room means one person or group takes the entire room: "
     "once anyone is in it, all its beds stop counting as vacant."),
    (r"\b(difference|different|vs|versus)\b.*\boverdue\b.*\bupcoming\b|\b(difference|different|vs|versus)\b.*\bupcoming\b.*\boverdue\b",
     "Upcoming means the check-out date is still ahead, within 7 days. Overdue means the check-out date has already passed and the tenant is still there. "
     "Both beds are occupied today."),
    (r"\b(difference|different|vs|versus)\b.*\b(students?)\b.*\breviewees?\b|\bwhat (is|are) (a )?reviewees?\b",
     "Students are enrolled in school; reviewees are preparing for a board or licensure exam. A room can be for Students, Reviewees or Mixed, "
     "and the app only offers beds whose room accepts the person's group."),
    (r"\b(what|how)\b.*\boccupancy rate\b.*\b(mean|computed|calculated|calculate|compute|formula)\b|\bwhat is (the )?occupancy rate\b.*\bmean\b|\bformula\b.*\boccupancy\b",
     "Occupancy rate = occupied beds ÷ all beds × 100. Occupied includes tenants, reserved beds, temporary clients and overdue tenants. "
     "Vacancy rate is the rest: vacant beds ÷ all beds × 100."),
    (r"\bwhat (is|does) (a )?(full room|fully occupied)( mean)?\b|\bwhen is a room full\b",
     "A room is full when it has no vacant bed left: every bed has a tenant, a reservation or a temporary client."),
    (r"\b(can|could)\b.*\b(reserved?|reservation)\b.*\bbed\b.*\b(given|give|assign\w*|used?|taken?|occup\w*)\b.*\b(another|other|someone|different)\b",
     "No. One bed holds one reservation, and a reserved bed is kept for that client. If the plan changes, cancel the reservation first in Reserved Clients; "
     "then the bed is vacant again and can go to someone else."),
]
DEF_GATE = re.compile(r"\b(why|consider\w*|count\w*|mean\w*|meaning|define|definition|difference|different|same as|treated|includ\w*|vs|versus|formula|"
                      r"what (is|are|does)|whats|is it|still|when is)\b|^(is|are|does|do|can|could)\b")


TERMS = [
    (r"upcoming( vacan\w*)?", "Upcoming vacant means an occupied bed whose check-out date is within the next 7 days. It is still occupied today, but it will be free soon, "
                              "so you can already offer it to someone arriving after that date."),
    (r"check ?out soon|checkout 48h?", "Checkout soon means the tenant leaves within 48 hours. The bed is still occupied until they are checked out."),
    (r"whole rooms?", "Whole Room means one person or group takes the entire room: once anyone is in it, all its beds stop counting as vacant."),
    (r"bed ?spac\w*", "Bedspace means each bed is rented separately, so different people can share the room."),
    (r"overdue", "Overdue means the tenant's check-out date has passed but they are still in the bed. The bed stays occupied (shown red) until you extend the stay "
                 "or check them out in Checkout Reminders."),
    (r"temporar\w*", "A temporary client is a short-stay guest placed in any free bed (only gender has to match), usually while waiting for a permanent bed. "
                     "The bed counts as occupied until the temporary client is checked out."),
    (r"reserv\w*", "Reserved means a bed is held for a client who has a check-in date but has not moved in yet. It counts as occupied because nobody else can take it. "
                   "When the client arrives, check them in from Reserved Clients and the bed becomes a normal occupied bed."),
    (r"vacan\w*", "Vacant means the bed is free right now: no tenant, no reservation and no temporary client. In a Whole Room, every bed stops being vacant "
                  "as soon as one person takes the room."),
    (r"occupied|occupancy(?! rate)", "Occupied means the bed cannot be given to a new person today. That covers four cases: a tenant is staying, the bed is reserved "
                                     "for a client, a temporary client is using it, or the tenant is overdue (past the check-out date but still there)."),
    (r"occupancy rate", "Occupancy rate = occupied beds ÷ all beds × 100. Occupied includes tenants, reserved beds, temporary clients and overdue tenants."),
    (r"vacancy rate", "Vacancy rate = vacant beds ÷ all beds × 100. A reserved or temporary bed is not vacant, so it is not counted here."),
    (r"reviewees?", "A reviewee is a resident preparing for a board or licensure exam. Rooms can be for Students, Reviewees or Mixed."),
    (r"full rooms?|fully occupied", "A room is full when it has no vacant bed left: every bed has a tenant, a reservation or a temporary client."),
    (r"tenant history", "Tenant History keeps everyone who checked out: their room, bed, dates and their good or bad record. Entries are kept for 2 years."),
    (r"bad records?|good records?", "When you check a tenant out you mark their stay as a good or a bad record. A bad record needs a reason (for example unpaid rent). "
                                    "It is saved in Tenant History so you can check it if the person comes back."),
    (r"data transfer", "Data Transfer hands all of this dormitory's records to a new account, for example when a Branch Admin resigns. You write the reason, "
                       "generate a one-time code, and the new account uses it; you approve the request in your Inbox."),
    (r"central link", "Central Link connects your dormitory to a Super Admin with a pairing code. You decide separately whether to share the directory listing, "
                      "analytics, and room status. Tenant names are never shared."),
    (r"dorm(itory)? viewers?", "A Dormitory Viewer is a read-only account that opens your dormitory with its code and password. It sees bed status and dates only, never names."),
    (r"super ?admins?", "A Super Admin oversees several dormitories. They only see counts and statistics from dormitories whose Branch Admin approved sharing."),
    (r"branch admins?", "A Branch Admin manages one dormitory: its rooms, beds, tenants, reservations and check-outs. Only the Branch Admin sees tenant names and numbers."),
]
MEAN = re.compile(r"\b(mean\w*|meaning|define|definition|explain|ibig sabihin|pasabot|kahulugan|what is an?|what are|whats an?|what is the|stand for)\b|^what (nang |kanang |ang |yung )?[a-z ]{3,25}$")
WHY = [
    (r"\bwhy\b.*\breserv\w*", "A reserved bed is counted as occupied because it is already promised to a client with a check-in date. If it were shown as vacant, "
                              "it could be given to someone else by mistake. Cancel the reservation and it becomes vacant again."),
    (r"\bwhy\b.*\btemporar\w*", "A temporary client's bed is counted as occupied because a person is really staying in it, even if only for a short time."),
    (r"\bwhy\b.*\boverdue\b", "An overdue bed is still occupied because the tenant has not been checked out yet. The date passed, but the person may still be there, "
                              "so the app waits for you to extend the stay or check them out."),
    (r"\bwhy\b.*\b(whole room|all beds)\b", "In a Whole Room one person or group rents the entire room, so all its beds stop being vacant together."),
]


def _term(t):
    if re.search(r"\b(how many|list|show|which|who|when|where|count|report|filter)\b", t) or not MEAN.search(t):
        return None
    for pat, text in TERMS:
        if re.search(r"\b(%s)\b" % pat, t):
            rest = re.sub(r"\b(%s)\b" % pat, " ", t)
            rest = re.sub(r"\b(what|whats|is|are|an?|the|does|do|mean\w*|of|define|definition|explain|ibig|sabihin|pasabot|kahulugan|beds?|rooms?|clients?|"
                          r"tenants?|guests?|status|word|term|nang|kanang|ang|yung|me|to|please|in|this|app|tracker|here|stand|for|by|you|it|that)\b", " ", rest)
            if len(rest.split()) <= 1:
                return text
    return None


def definitions(q, page):
    t = (q or "").lower().strip(" ?")
    for pat, text in WHY:
        if re.search(pat, t) and re.search(r"\b(occup\w*|not vacant|count\w*|consider\w*|vacan\w*|full)\b", t) and not re.search(r"\broom\s+[a-z]?-?\d", t):
            return R("definition", text)
    if not re.search(r"\broom\s+[a-z]?-?\d", t):
        term = _term(t)
        if term:
            return R("definition", term, suggestions=["How many beds are vacant?", "What are your limitations?"])
    if not DEF_GATE.search(t) or re.search(r"\broom\s+[a-z]?-?\d", t):
        return None
    if re.search(r"\b(how many|list|show|which rooms?|who)\b", t) and not re.search(r"\b(consider\w*|count as|mean\w*)\b", t):
        return None
    for pat, text in DEFS:
        if re.search(pat, t):
            return R("definition", text, suggestions=["How many beds are vacant?", "What does overdue mean?", "What are your limitations?"])
    return None


# ------------------------------------------------------------------------------------------ limits and abilities
LIMIT_Q = re.compile(r"\b(limit\w*|restrict\w*|weakness\w*|can not do|cannot do|cant do|can't do|unable|not able|not allowed|"
                     r"what (do|can) you not|things you (cant|can't|cannot|can not)|boundar\w*|shortcoming\w*)\b")
ABLE_Q = re.compile(r"\bwhat (can|could|do) you (actually |really |exactly |even |else |all )?(do|help|offer|know)\b|\b(your )?(capabilit\w*|abilit\w*|skills?|features?|functions?)\b.*\b(you|your|assistant|ai)\b|"
                    r"\bwhat are you (for|able|capable|good)\b|\bhow can you help\b|\bwhat can i ask\b|\bwhat (commands?|questions?) can\b|^help$|"
                    r"\bwhat (is|are) your (job|purpose|role|use)\b")

CAN = {
    "admin": ["Count and list beds: vacant, occupied, reserved, temporary, overdue, upcoming (whole dorm or one room, e.g. “how many vacant in S-105”)",
              "Find a person in your own records: “is Terrins present?”, “find Terrins in the history”",
              "Prepare changes for you to confirm: check in, check out (with a good or bad record), extend, transfer, reserve, add a temporary client, add or edit a room",
              "Choose the best bed for a new client and tell you the next best one",
              "Work the screen for you: “show only the vacant beds”, “open Tenant History”, “search for Room S-105”",
              "Explain how any part of the tracker works and what each status means",
              "Understand English, Tagalog, Cebuano, mixed language, and wrong spelling; read answers aloud and listen to your voice"],
    "viewer": ["Count vacant and occupied beds, also for male, female, students or reviewees",
               "Report one room: “how many vacant in Room S-105”",
               "Show upcoming vacancies and when the next bed frees up",
               "Set the page filters for you: “show me what is vacant”, “show only female rooms”",
               "Explain what each bed status means"],
    "marketing": ["Tell you which dormitory has the most vacant beds, also for male, female, students, reviewees or air-conditioned rooms",
                  "Find a dormitory by name or city and filter the list for you",
                  "Compare dormitories and suggest where a client can stay"],
    "superadmin": ["Report vacancy and occupancy for the dormitories that approved sharing, and compare or rank them",
                   "Find one dormitory: “find Sanciangko dorm” searches it and reports it",
                   "Show trends from the daily snapshots and list requests waiting in your Inbox",
                   "Open any tab for you"],
}
CANNOT = {
    "admin": ["I never change anything by myself. Every change is shown to you first and happens only after you press Confirm",
              "I don't know about rent, payments or money: the tracker does not record them",
              "I can't see other dormitories' tenants, and I can't change passwords or accounts",
              "I can't finish a data transfer for you; I can only fill in the reason, because handing over your records is your decision",
              "I only know what is saved in the tracker. I can't guess things that were never recorded, like repairs or complaints",
              "Voice needs Chrome or Edge, and I don't read phone numbers aloud"],
    "viewer": ["This page is read-only: I can't reserve, check in or change anything",
               "I can't tell you who lives in a bed. Names, contact numbers and other tenant details stay with the Branch Admin",
               "I don't know rent or prices; ask the dormitory",
               "I only see the dormitory you opened"],
    "marketing": ["I only see vacancy counts for each dormitory, not their rooms or check-out dates",
                  "I can't share tenant names, contact numbers or any personal details",
                  "I don't know rent or prices, and I can't reserve a bed for you"],
    "superadmin": ["I only see dormitories whose Branch Admin approved sharing",
                   "I can't see tenant names, contact numbers or other private details of any branch",
                   "I can't change a branch's rooms or tenants; only its Branch Admin can",
                   "I don't know rent, payments or revenue"],
}
PAGE_NAME = {"admin": "Branch Admin", "viewer": "Dormitory Viewer", "marketing": "Marketing Viewer", "superadmin": "Super Admin"}


def limits(q, page):
    t = (q or "").lower().strip(" ?")
    p = page if page in CAN else "admin"
    if LIMIT_Q.search(t) and re.search(r"\b(you|your|ai|assistant|u)\b|^limit\w*$", t):
        return R("limitations", "Here are my limits on the %s page:" % PAGE_NAME[p],
                 [{"type": "list", "items": CANNOT[p]}, {"type": "note", "text": "What I can do: " + "; ".join(x.split(":")[0] for x in CAN[p][:4]) + "."}],
                 suggestions=["What can you do?"])
    if ABLE_Q.search(t):
        return R("capabilities", "Here is what I can do on the %s page:" % PAGE_NAME[p],
                 [{"type": "list", "items": CAN[p]}, {"type": "note", "text": "Ask “what are your limitations?” to see what I can't do."}],
                 suggestions=["What are your limitations?"])
    return None


# ------------------------------------------------------------------------------------------ curiosity
CURIOUS = [
    (r"\b(are you|r u|you are) (a )?(real )?(human|person|robot|bot|machine|ai|alive|real)\b|\bare you (chatgpt|gpt|gemini|claude|siri|alexa)\b",
     "I'm an AI assistant, not a person. I was built into the Vecancy Tracker by the developer Mr. Hortelano, Terrins, and I only work with this dormitory system."),
    (r"\b(how do you work|how were you (made|built|trained)|how are you made|where do you get (your|the) (answers?|data|information)|how do you know)\b",
     "I read your question, fix spelling and translate Tagalog or Cebuano words, then match it to what I was trained on. For numbers I read the live "
     "records this page is allowed to see, so the counts are real and not guessed."),
    (r"\b(do you learn|can you learn|are you learning|do you get smarter)\b",
     "I remember the current chat, so you can ask follow-ups like “what about females?”, and I keep things you ask me to remember. "
     "I don't learn new skills by myself; the developer trains me with new questions."),
    (r"\b(what|which) languages?\b.*\b(you|speak|understand|know)\b|\b(do|can) you (speak|understand|know) (tagalog|filipino|bisaya|cebuano|english|taglish)\b|"
     r"\bmakasabot ka\b|\bnakakaintindi ka\b",
     "I understand English, Tagalog, Cebuano (Bisaya) and mixed language, even with wrong spelling. I answer in simple English."),
    (r"\b(are you|is (it|this|my data)) (safe|secure|private)\b|\b(who can see|do you share|will you share|do you save|do you store)\b.*\b(data|chat|conversation|information|messages?)\b",
     "Your chat is saved only under your own account. Tenant names and numbers are shown only to the dormitory's Branch Admin; viewers, marketing "
     "and Super Admin pages never get them."),
    (r"\b(can you|do you) (make|do) mistakes?\b|\bare you (always )?(right|correct|accurate)\b|\bcan i trust you\b",
     "Counts come straight from the saved records, so they are as correct as the records are. I can still misunderstand a question; if an answer "
     "looks wrong, ask it another way. I never change anything without your confirmation."),
    (r"\b(how are you|how r u|kumusta( ka)?|kamusta( ka)?|musta)\b",
     "I'm doing well, thank you. Ready to help with your dormitory."),
    (r"\b(what is|whats) your name\b|\bdo you have a name\b|\bwhat should i call you\b",
     "I'm the Vecancy Tracker assistant. I was created by the developer Mr. Hortelano, Terrins."),
    (r"\b(how old are you|when were you (born|made|created)|what is your age)\b",
     "I was created in 2026 together with the Vecancy Tracker."),
    (r"\b(tell me a joke|joke|make me laugh)\b",
     "Why did the bed go to school? To become a bunk scholar. Now, back to your dormitory: what would you like to know?"),
    (r"\b(i love you|love you|you are (great|smart|good|amazing|awesome|the best)|good job|well done|nice work|galing|ayos)\b",
     "Thank you! Happy to help."),
    (r"\b(you are|ur|you're|youre) (stupid|dumb|useless|bad|wrong|bobo|tanga|bugo)\b|\b(stupid|useless|bobo|tanga|bugo) (ai|bot|assistant|ka)\b",
     "Sorry I got that wrong. Tell me again in other words and I'll try to do better, or say “what can you do?” to see what I understand."),
    (r"\b(what (time|day|date) is it|what is (the )?(date|time|day) (today|now)|todays date|what day is today)\b", None),   # filled with the date
    (r"\bwho is (terrins|mr\.? hortelano|the developer|your (creator|developer|maker|boss))\b|\bwho (developed|programmed|designed) (you|this( app| system)?)\b",
     "Mr. Hortelano, Terrins is the developer who created the Vecancy Tracker and me, its assistant."),
]


def curiosity(q, page, today=None):
    t = (q or "").lower().strip(" ?!.")
    for pat, text in CURIOUS:
        if re.search(pat, t):
            if text is None:
                d = today or datetime.now(timezone.utc).date()
                text = "I can't see a clock, but today is %s %d, %d." % (d.strftime("%A, %B"), d.day, d.year)   # %-d fails on Windows
            return R("smalltalk", text)
    return None


# ------------------------------------------------------------------------------------------ Branch Admin: bed status helpers
def bed_status(room, bed, today):
    """vacant | reserved | temporary | overdue | soon | occupied  (same meaning as the Room Canvas)."""
    if bed.get("tenant"):
        end = smart.parse_iso(bed.get("end"))
        if bed.get("temporaryClientId"):
            return "temporary"
        if end and end < today:
            return "overdue"
        if end and end <= today + timedelta(days=2):
            return "soon"
        return "occupied"
    if bed.get("reservedFor"):
        return "reserved"
    if (room.get("tenancyMode") == "Whole Room") and any(b.get("tenant") for b in room["beds"]):
        return "occupied"
    return "vacant"


LABEL = {"vacant": "Vacant", "reserved": "Occupied · reserved", "temporary": "Occupied · temporary", "overdue": "Overdue",
         "soon": "Occupied · checkout soon", "occupied": "Occupied"}
WANT_ST = [("vacant", r"\b(vacan\w*|available|free|empty|open|unoccupied)\b"), ("overdue", r"\boverdue\b|\bpast (the )?(check ?out|due)\b|\blate\b"),
           ("reserved", r"\breserv\w*\b|\bbook\w*\b"), ("temporary", r"\b(temporar\w*|temp|short[- ]stay)\b"),
           ("soon", r"\b(checkout soon|check ?out soon|leaving soon|48)\b"), ("occupied", r"\b(occupied|taken|in use|filled)\b")]


def _rooms_in(t, rec):
    """Rooms named in the text (needs the room's own name; 'room 105' also finds 'S-105')."""
    out = []
    for m in re.finditer(r"\brooms?\s*(?:no\.?|number|#)?\s*([a-z0-9][a-z0-9-]*)", t):
        tok = m.group(1)
        if not re.search(r"\d", tok):
            continue
        hits = [r for r in rec.rooms if smart.norm(r.get("room")) == tok] or \
               [r for r in rec.rooms if smart.norm(r.get("room")).replace("-", "") == tok.replace("-", "")] or \
               [r for r in rec.rooms if smart.norm(r.get("room")).endswith("-" + tok)]
        out.append((hits[0] if len(hits) == 1 else None, tok))
    return out


def _counts(room, today):
    c = {k: 0 for k in LABEL}
    for b in room["beds"]:
        c[bed_status(room, b, today)] += 1
    c["total"] = len(room["beds"])
    c["inuse"] = c["total"] - c["vacant"]
    return c


def room_report(conn, uid, t, today):
    """'how many vacant / overdue / reserved / temporary in room S-105', 'report room S-105'."""
    if re.search(r"\b(who|whose|names?|contacts?|numbers? of the|phone)\b", t) and not re.search(r"\bhow many\b", t):
        return None
    ask = re.search(r"\b(how many|count|number of|total|report|status|summary|summari[sz]e|overview|any|is there|are there|does|do we have|search|find|look for|locate|"
                    r"vacan\w*|available|free|overdue|reserv\w*|temporar\w*|occupied|full|empty|beds? (left|remaining))\b", t)
    if not ask:
        return None
    if re.search(r"\b(next (week|month)|tomorrow|on (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|by (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))", t):
        return None                                    # date questions are answered by the forecast answers
    rec = smart.Records(conn.cursor(), uid)
    refs = _rooms_in(t, rec)
    if not refs:
        return None
    missing = [tok for r, tok in refs if r is None]
    if missing:
        return R("room_missing", "I can't find Room %s in your records. Your rooms: %s." % (missing[0].upper(), ", ".join(str(r.get("room")) for r in rec.rooms[:20])))
    rows_all, texts, blocks = [], [], []
    wanted = [k for k, p in WANT_ST if re.search(p, t)]
    for room, _tok in refs[:4]:
        c = _counts(room, today)
        beds = [(smart.bed_label(b, i), bed_status(room, b, today), b) for i, b in enumerate(room["beds"])]
        name = "Room %s" % room.get("room")
        parts = []
        for k in wanted:
            n = c[k] if k != "occupied" else c["inuse"]
            who = [s for s, st, _b in beds if (st == k if k != "occupied" else st != "vacant")]
            word = {"vacant": "vacant", "overdue": "overdue", "reserved": "reserved", "temporary": "temporary", "soon": "checking out soon", "occupied": "occupied"}[k]
            parts.append("%d %s bed%s%s" % (n, word, "" if n == 1 else "s", (" (" + ", ".join(who[:8]) + ")") if 0 < n <= 8 else ""))
        full = "%d beds: %d vacant, %d occupied" % (c["total"], c["vacant"], c["inuse"])
        inside = [("%d reserved" % c["reserved"]) if c["reserved"] else "", ("%d temporary" % c["temporary"]) if c["temporary"] else "",
                  ("%d overdue" % c["overdue"]) if c["overdue"] else "", ("%d checking out soon" % c["soon"]) if c["soon"] else ""]
        inside = [x for x in inside if x]
        if inside:
            full += " (including %s)" % ", ".join(inside)
        if parts:
            texts.append("%s has %s. All together, %s." % (name, " and ".join(parts), full))
        else:
            texts.append("%s has %s." % (name, full))
        rows = []
        for slot, st, b in beds:
            who = b.get("tenant") or ""
            if st == "reserved":
                p = next((p for p in rec.prospects if p.get("id") == b.get("reservedFor")), None)
                who = ("Reserved for " + str(p.get("name"))) if p else "Reserved"
            rows.append([slot, LABEL[st], who or "—", smart.pretty(smart.parse_iso(b.get("end"))) if b.get("end") else "—"])
        blocks += [{"type": "subheading", "text": "%s · %s · %s" % (name, room.get("gender") or "Mixed", room.get("demographic") or "Mixed")},
                   {"type": "table", "columns": ["Bed", "Status", "Who", "Check-out"], "rows": rows}]
        rows_all += rows
    nav = {"tab": "dashboard", "roomId": refs[0][0]["id"]} if len(refs) == 1 else None
    if nav and re.search(r"^(search|find|look for|locate)\b", t):
        nav["filters"] = {"status": "all", "gender": "all", "demographic": "all", "search": str(refs[0][0].get("room"))}
        texts.insert(0, "I typed “%s” in the search box." % refs[0][0].get("room"))
    return R("room_report", " ".join(texts), blocks, nav=nav,
             suggestions=["Who is in this room?", "Show only the vacant beds"])


# ------------------------------------------------------------------------------------------ Branch Admin: find a person
PERSON_TRIG = re.compile(
    r"^(is|are|was|does|did|do we have|have we|has) .*\b(present|here|there|around|staying|still (here|staying|with us)|a tenant|our tenant|in the (dorm\w*|building|records?|list|history|system)|"
    r"checked (in|out)|living here|with us|exist\w*|registered|a (reserved?|temporary) client|reserved|on the list)\b|"
    r"^(find|search( for)?|look (for|up)|locate|look for|where is|wheres|where did|which room is|what room is|who is|whos|do we have|is there|"
    r"check if|tell me (about|where)|show( me)?|get|open|give me)\b|\bin (the |my |our )?(tenant )?history\b|\b(history|records?) of\b|\bever (stay\w*|live\w*|been)\b|"
    r"\b(contacts?|numbers?|phone|mobile|cellphone|emergency|address|email|details|info\w*|profile)\b.*\b(of|for|ni|kay)\b|[a-zñ]+'?s (contact|number|phone|mobile|emergency|address|email|details|info\w*|profile)\b|"
    r"\b(records?|standing|reputation)\b.*\b(of|for|ni|kay)\b|[a-zñ]+'?s (record|standing|reputation)\b|\b(have|has|with) (a |an )?(bad|good|clean) record\b|\bblack ?list\w*\b|"
    r"\b(present|staying)\b.*\b(or|if)\b.*\b(check ?out|checked ?out|left)\b")
PERSON_STOP = set("""is are was were does did do we have has had a an the our my your their his her its this that there here present around staying still with us
tenant tenants resident residents client clients guest guests boarder person people someone anyone named called name in at on of for to from by and or if
dorm dormitory building records record list history system checked check in out living exist exists registered reserved reserve temporary find search look
up locate where wheres which what room who whos tell me about show get open give please can you could now right today currently ever stay stayed lived been
information info details data profile contact number numbers phone it he she they him them mr mrs ms sir maam any some no not yet already also too did
old past previous former before bed beds status still stays lives live emergency address email mobile cellphone ni kay sa ang ng si
full complete all whole checkout checkin checkedout left gone bad good reason reasons say said standing reputation blacklist blacklisted why whether
then so but just really again one ones canvas hallway matrix dashboard screen page tab using through inside ba na pa po lang naman""".split())


def _name_tokens(text):
    toks = [w for w in re.findall(r"[a-zñ][a-zñ'.-]*", (text or "").lower()) if w.strip(".'-") not in PERSON_STOP and len(w.strip(".'-")) >= 2]
    return [w.strip(".'-") for w in toks]


def _name_score(tokens, name):
    """How well the typed words match a saved name (0 = no match). Handles first names, partial names and small typos."""
    words = re.findall(r"[a-zñ]+", (name or "").lower())
    if not words or not tokens:
        return 0
    score = 0
    for tk in tokens:
        best = 0
        for w in words:
            if tk == w:
                best = max(best, 3)
            elif len(tk) >= 3 and (w.startswith(tk) or tk.startswith(w) and len(w) >= 4):
                best = max(best, 2)
            elif len(tk) >= 4 and difflib.SequenceMatcher(None, tk, w).ratio() >= 0.8:
                best = max(best, 2)
        if not best:
            return 0                                   # every typed word must belong to the name
        score += best
    return score


def _when(v):
    d = smart.parse_iso(str(v)[:10]) if v else None
    return smart.pretty(d) if d else "—"


def _ts_date(v):
    """A saved time -> the user's LOCAL date (precise.TZ holds this request's time zone; UTC when unknown)."""
    try:
        import precise
        shift = getattr(precise.TZ, "offset", 0) * 60
    except Exception:
        shift = 0
    try:
        if isinstance(v, dict) and "__ts" in v:
            return datetime.fromtimestamp(v["__ts"] / 1000 + shift, timezone.utc).date()
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 + shift, timezone.utc).date()
        if isinstance(v, str):
            return smart.parse_iso(v[:10])
    except Exception:
        return None
    return None


def person_lookup(conn, uid, t, raw, today):
    """Branch Admin only. Looks in current tenants, reserved clients, temporary clients and Tenant History."""
    low = (raw or t or "").lower()
    low = command_form(re.sub(r"[?!,]", " ", low).strip())
    # "find X in the room canvas / on the hallway / in the list": the place is not part of the name
    place = re.search(r"\b(?:in|on|at|from|sa|inside|using|through)\s+(?:the\s+|my\s+|our\s+)?(room canvas|canvas|hallway layout|hallway|bed matrix|matrix|dashboard|"
                      r"screen|page|tab|dorm\w*|building|system|records?|list|data|tenant list|tenant information)\b", low)
    if place:
        low = (low[:place.start()] + " " + low[place.end():]).strip()
    want_record = bool(re.search(r"\b(records?|standing|reputation|black ?list\w*)\b", low)) and not re.search(r"\b(in|from) (the |my |our )?records?\b", low)
    trig = PERSON_TRIG.search(low) or PERSON_TRIG.search(t) or (want_record and re.search(r"\b(of|for|ni|kay|have|has|with|is|does)\b", low))
    if not trig:
        return None
    if re.search(r"\b(vacan\w*|available|beds?\b(?! of)|rooms? (with|that|are|have)|report|filter|only|all (tenants|rooms)|dormitor\w*|tab|page|layout|analytics|"
                 r"calendar|reminders?|inbox|central|viewers?|how many|list of|everyone|overdue tenants|female|male|students?|reviewees?)\b", low) and \
            not re.search(r"\b(named|called)\b", low):
        if not re.search(r"\bin (the |my |our )?(tenant )?history\b", low):
            return None
    want_hist = bool(re.search(r"\bhistory\b|\bever\b|\b(former|previous|past|old) tenant\b|\bchecked out\b|\bbefore\b", low))
    both = bool(re.search(r"\b(present|here|staying|still)\b.*\b(or|if)\b.*\b(check ?out|checked ?out|left|gone|history)\b", low))   # "present, or already checked out?"
    if both:
        want_hist = False
    want_contact = bool(re.search(r"\b(contacts?|numbers?|phone|mobile|cellphone|emergency|address|email|details|info\w*|profile)\b", low))
    low = re.sub(r"([a-zñ]+)'s\b", r"\1", low)
    tokens = _name_tokens(low)
    if want_contact and tokens and tokens[0].endswith("s") and len(tokens[0]) > 3 and re.search(r"\b%s (contact|number|phone|mobile|emergency|address|email|details|info\w*|profile)\b" % re.escape(tokens[0]), low):
        tokens[0] = tokens[0][:-1]                      # "anas contact number" -> ana
    if not tokens or len(tokens) > 7:
        return None
    cur = conn.cursor()
    rec = smart.Records(cur, uid)
    hist = []
    try:
        hist = [dict(d, id=i) for i, d, _v in list_docs(cur, KINDS["tenant_history"], [uid], limit=5000)]
    except Exception:
        hist = []
    everyone = [b.get("tenant") for _r, _i, b in rec.occupied()] + [p.get("name") for p in rec.prospects] + [h.get("tenant") for h in hist]
    if not any(_name_score(tokens, n) for n in everyone):
        # second chance: drop words that are only misspelled filler ("akready", "hisotry", "thet") and try again
        kept = [w for w in tokens if not difflib.get_close_matches(w, PERSON_STOP, n=1, cutoff=0.78 if len(w) >= 5 else 0.85)]
        if kept and len(kept) < len(tokens) and any(_name_score(kept, n) for n in everyone):
            tokens = kept
        else:
            # or keep only the words that really belong to somebody's name
            named = [w for w in tokens if any(_name_score([w], n) for n in everyone)]
            if named and len(tokens) - len(named) <= 2 and any(_name_score(named, n) for n in everyone):
                tokens = named
    found = []                                          # (score, kind, row, nav)
    for r, i, b in rec.occupied():
        s = _name_score(tokens, b.get("tenant"))
        if s:
            kind = "Temporary client (staying now)" if b.get("temporaryClientId") else "Tenant (staying now)"
            found.append((s + 1, "now", [b.get("tenant"), kind, "Room %s, %s" % (r.get("room"), smart.bed_label(b, i)),
                                        "%s → %s" % (_when(b.get("start")), _when(b.get("end")) if b.get("end") else "no end date")],
                          {"tab": "dashboard", "roomId": r["id"], "filters": {"status": "all", "gender": "all", "demographic": "all", "search": str(b.get("tenant") or "")}},
                          b.get("tenantId")))
    for p in rec.prospects:
        if p.get("checkedIn"):
            continue
        s = _name_score(tokens, p.get("name"))
        if s:
            rb = p.get("reservedBed") or {}
            room = rec.room(rb.get("roomId")) if rb.get("roomId") else None
            where = ("Room %s, %s (held)" % (room.get("room"), rb.get("slot"))) if room else "No bed chosen yet"
            found.append((s, "reserved", [p.get("name"), "Reserved client (not arrived yet)", where,
                                          "check-in %s%s" % (_when(p.get("checkIn")), (" → " + _when(p.get("checkOut"))) if p.get("checkOut") else "")],
                          {"tab": "reserve"}, None))
    for h in hist:
        s = _name_score(tokens, h.get("tenant"))
        if s:
            left = _ts_date(h.get("leftAt"))
            recd = h.get("record")
            note = ("good record" if recd == "good" else "bad record: %s" % (h.get("recordReason") or "no reason written") if recd == "bad" else "no record saved")
            found.append((s - (0 if want_hist else 1), "history",
                          [h.get("tenant"), "Tenant History (%s)" % (h.get("reason") or "left"), "Room %s, %s" % (h.get("room"), h.get("slot")),
                           "%s → %s; left %s; %s" % (_when(h.get("start")), _when(h.get("end")), smart.pretty(left) if left else "—", note)],
                          {"tab": "history"}, {"record": recd, "reason": h.get("recordReason") or "", "left": left, "why": h.get("reason") or ""}))
    typed = " ".join(w.capitalize() for w in tokens)
    strong = bool(re.search(r"\b(present|staying|history|named|called|living here|with us|still here)\b", low)) or want_record or bool(place)
    import lang
    known = set(getattr(lang, "VOCAB", [])) | set(getattr(lang, "_ENGLISH", []))
    plain_words = [w for w in tokens if w in known]
    if re.match(r"^(are|is) there\b", low) and not re.search(r"\b(named|called)\b", low):
        strong = False
    if not found:
        if not strong or plain_words or len(tokens) > 3:
            return None                                # "find the report", "are there duplicate records" are not about a person
        return R("person_search", "No. I searched your current tenants, reserved clients, temporary clients and Tenant History and found nobody named “%s”. "
                 "Check the spelling or try just the first name." % typed, suggestions=["List all tenants", "Open Tenant History"])
    best = max(f[0] for f in found)
    top = [f for f in found if f[0] >= best - 1]
    if want_hist:
        top = [f for f in found if f[1] == "history"] or top
    top.sort(key=lambda f: ({"now": 0, "reserved": 1, "history": 2}[f[1]] if not want_hist else {"history": 0, "now": 1, "reserved": 2}[f[1]], -f[0]))
    now_hits = [f for f in top if f[1] == "now"]
    first = top[0]
    if want_contact and not want_hist:
        people = now_hits or top
        infos = {}
        try:
            infos = {i: dd for i, dd, _v in list_docs(cur, KINDS["tenants"], [uid], limit=5000)}
        except Exception:
            infos = {}
        rows, lines = [], []
        for f in people[:6]:
            info = infos.get(f[4]) if len(f) > 4 and f[4] else {}
            info = info or {}
            ecs = ["%s %s" % ((e or {}).get("name") or "", (e or {}).get("phone") or "") for e in (info.get("ec1"), info.get("ec2")) if isinstance(e, dict) and (e.get("name") or e.get("phone"))]
            contact = str(info.get("contact") or info.get("phone") or "").strip()
            rows.append([f[2][0], f[2][2], contact or "not on file", "; ".join(x.strip() for x in ecs) or "not on file", str(info.get("email") or info.get("address") or "—")])
            addr = str(info.get("address") or "").strip()
            lines.append("%s (%s): contact %s; emergency %s%s" % (f[2][0], f[2][2], contact or "not on file", "; ".join(x.strip() for x in ecs) or "not on file",
                                                                 ("; address " + addr) if addr and re.search(r"\b(address|live|lives|living|home)\b", low) else ""))
        return R("person_contact", "Contact details from your Tenant Information — %s." % " | ".join(lines),
                 [{"type": "table", "columns": ["Name", "Where", "Contact", "Emergency contact", "Email / address"], "rows": rows}],
                 nav=people[0][3], suggestions=["Open Tenant Information"])
    hist_hits = sorted([f for f in found if f[1] == "history" and f[0] >= best - 2], key=lambda f: f[4]["left"] or datetime(1970, 1, 1).date(), reverse=True)
    if want_record:
        # "what is the record of X? if bad, say the reason"
        if hist_hits:
            h = hist_hits[0]
            ex = h[4]
            verdict = ("a GOOD record" if ex["record"] == "good" else
                       "a BAD record. Reason: %s" % (ex["reason"] or "no reason was written") if ex["record"] == "bad" else
                       "no good or bad record (none was saved at check-out)")
            text = "%s has %s. That is from Tenant History: %s, left %s." % (h[2][0], verdict, h[2][2], smart.pretty(ex["left"]) if ex["left"] else "date not saved")
            if now_hits:
                text += " %s is staying again now in %s." % (now_hits[0][2][0], now_hits[0][2][2])
            if len(hist_hits) > 1:
                text += " There are %d past stays; all are in the table." % len(hist_hits)
            return R("person_record", text, [{"type": "table", "columns": ["Name", "Record", "Where", "Dates"], "rows": [f[2] for f in hist_hits[:12]]}],
                     nav={"tab": "history"}, suggestions=["Is %s present?" % h[2][0]])
        text = ("%s has no record yet. They are still %s (%s), and a good or bad record is only saved when you check them out." % (
            first[2][0], "a reserved client" if first[1] == "reserved" else "staying", first[2][2]))
        return R("person_record", text, [{"type": "table", "columns": ["Name", "Record", "Where", "Dates"], "rows": [f[2] for f in top[:12]]}], nav=first[3])
    if both:
        # "is X present, or already checked out? if checked out, find them in the history"
        if now_hits:
            f0 = now_hits[0]
            text = "Yes, %s is present: %s, %s. Not checked out yet" % (f0[2][0], f0[2][2], f0[2][3])
            text += (", but there is an older stay in Tenant History (%s)." % hist_hits[0][2][3]) if hist_hits else ", so there is nothing in Tenant History."
            first = f0
        elif hist_hits:
            h = hist_hits[0]
            ex = h[4]
            text = "No, %s is not present. Already checked out: I found them in Tenant History — %s, %s." % (h[2][0], h[2][2], h[2][3])
            first = h
        else:
            text = "%s is not staying yet and has not checked out. They are a reserved client: %s, %s." % (first[2][0], first[2][2], first[2][3])
        return R("person_search", text, [{"type": "table", "columns": ["Name", "Record", "Where", "Dates"], "rows": [f[2] for f in (now_hits + hist_hits or top)[:12]]}],
                 nav=first[3], suggestions=["What is the record of %s?" % first[2][0]])
    if want_hist and first[1] == "history":
        text = "Yes, I found %s in Tenant History: %s, %s." % (first[2][0], first[2][2], first[2][3])
        if now_hits:
            text += " %s is also staying now in %s." % (now_hits[0][2][0], now_hits[0][2][2])
    elif want_hist:
        text = "%s is not in Tenant History, because they have not checked out yet. %s: %s." % (first[2][0], first[2][1], first[2][2])
    elif first[1] == "now" and len(now_hits) > 1:
        text = "Yes. %d people with that name are staying now: %s." % (len(now_hits), "; ".join("%s in %s" % (f[2][0], f[2][2]) for f in now_hits[:6]))
    elif first[1] == "now":
        text = "Yes, %s is here: %s, %s." % (first[2][0], first[2][2], first[2][3])
    elif first[1] == "reserved":
        text = "%s is not staying yet. They are a reserved client: %s, %s." % (first[2][0], first[2][2], first[2][3])
    else:
        text = "%s is not staying now. I found them in Tenant History: %s, %s." % (first[2][0], first[2][2], first[2][3])
    if len(top) > 1 and not (first[1] == "now" and len(now_hits) == len(top)):
        text += " I found %d matching records; all are in the table." % len(top)
    return R("person_search", text, [{"type": "table", "columns": ["Name", "Record", "Where", "Dates"], "rows": [f[2] for f in top[:12]]}],
             nav=first[3], suggestions=["Contact details of %s" % first[2][0], "Open Tenant History"])


# ------------------------------------------------------------------------------------------ Branch Admin: data transfer reason
def transfer_reason(t, raw):
    low = (raw or t or "").lower()
    if not re.search(r"\b(data )?transfer\w*\b", low) or not re.search(r"\b(reason|purpose|why|because|resign\w*|leaving|quit\w*|retir\w*|code)\b", low):
        return None
    if re.search(r"\b(room|bed|tenant|resident|client)\b", low) and not re.search(r"\bdata\b", low):
        return None                                    # moving a tenant between beds is a different request
    if not re.search(r"\b(add|put|write|set|fill|type|enter|make|generate|create|start|prepare|do|want|need)\b", low):
        return None
    m = re.search(r"\b(?:because|since|as|cause|coz|kay|kasi|reason is|reason:|purpose is|purpose:|that says?|saying)\s+(.{3,160})$", (raw or t).strip(" .?!"), re.I)
    reason = m.group(1).strip() if m else None
    if not reason:
        m = re.search(r"\b(i(?: am|'m| will| want to| need to| have to)? ?(?:resign\w*|leaving|quit\w*|retir\w*).{0,80})$", (raw or t).strip(" .?!"), re.I)
        reason = m.group(1).strip() if m else None
    if not reason:
        return R("transfer_reason", "What reason should I write for the data transfer? For example: “because I am resigning and Maria takes over”.",
                 nav={"tab": "transfer"})
    reason = reason[0].upper() + reason[1:]
    reason = re.sub(r"\bi\b", "I", reason)
    return R("transfer_reason", "Done: I opened Data Transfer and wrote your reason: “%s”. Check it, then press Generate transfer code yourself. "
             "I did not create the code, because handing over all your records is your decision." % reason,
             nav={"tab": "transfer", "transferPurpose": reason[:200]})


# ------------------------------------------------------------------------------------------ screen filters
SHOW = re.compile(r"^(show|display|filter|view|see|let me see|list|give me|get|hide|only|just|open|find|highlight|select|choose|pick|click|set)\b")
F_STATUS = [("full", r"\bfull( rooms?)?\b|\bfully (occupied|booked)\b"), ("vacant", r"\b(vacan\w*|available|free|empty|unoccupied)\b"),
            ("overdue", r"\boverdue\b"), ("reserved", r"\breserv\w*\b"), ("temporary", r"\btemporar\w*\b|\btemp\b"), ("occupied", r"\boccupied\b|\btaken\b")]


def _filters_from(t):
    f = {}
    for k, p in F_STATUS:
        if re.search(p, t):
            f["status"] = k
            break
    if re.search(r"\bfemales?\b|\bgirls?\b|\bwomen\b|\bladies\b", t):
        f["gender"] = "Female"
    elif re.search(r"\bmales?\b|\bboys?\b|\bmen\b", t):
        f["gender"] = "Male"
    elif re.search(r"\bmixed gender\b|\bmixed rooms?\b", t):
        f["gender"] = "Mixed"
    if re.search(r"\bstudents?\b", t):
        f["demographic"] = "Students"
    elif re.search(r"\breviewees?\b", t):
        f["demographic"] = "Reviewees"
    return f


CLEAR = re.compile(r"\b(clear|reset|remove|turn off|no|cancel)\b.*\bfilters?\b|\bshow (me )?(all|everything|every (bed|room))\b( again)?$|\b(all|every) (beds?|rooms?) again\b|\bunfilter\b")


def admin_screen(conn, uid, t, today, ctx):
    """'show me only the vacant beds' -> sets the Room Canvas filter and reports what is on screen."""
    if CLEAR.search(t):
        return R("screen_filter", "Done: I cleared the filters, so every room and bed is shown again.",
                 nav={"filters": {"status": "all", "gender": "all", "demographic": "all", "search": ""}})
    if not SHOW.match(t):
        return None
    f = _filters_from(t)
    explicit = re.search(r"\b(only|just|filter\w*|nothing but|alone)\b", t)
    if not f or not (explicit or re.search(r"^(filter|highlight|select|choose|pick|click)\b", t)):
        return None
    if re.search(r"\b(who|names?|contacts?|history|reservations? (list|tab)|tab|page|report|how many|next (week|month)|tomorrow|on (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))\b", t):
        return None
    if re.search(r"\broom\s+[a-z]?-?\d", t):
        return None                                    # one room: the room report answers it
    if re.search(r"\b(reservations?|clients?|tenants?|guests?|residents?|check ?outs?|check ?ins?|people|list)\b", t) and not explicit:
        return None                                    # "show my reservations": a list of people, not a screen filter
    if "status" not in f and not explicit:
        return None
    rec = smart.Records(conn.cursor(), uid)
    rows, rooms_hit = [], set()
    for r in rec.rooms:
        if f.get("gender") and (r.get("gender") or "Mixed") != f["gender"]:
            continue
        if f.get("demographic") and (r.get("demographic") or "Mixed") != f["demographic"]:
            continue
        c = _counts(r, today)
        if f.get("status") == "full" and c["vacant"]:
            continue
        for i, b in enumerate(r["beds"]):
            st = bed_status(r, b, today)
            ok = (f.get("status") in (None, "full") or st == f["status"] or (f["status"] == "occupied" and st in ("occupied", "soon")))
            if ok:
                rooms_hit.add(r["id"])
                who = b.get("tenant") or ""
                if st == "reserved":
                    p = next((p for p in rec.prospects if p.get("id") == b.get("reservedFor")), None)
                    who = ("Reserved for " + str(p.get("name"))) if p else "Reserved"
                rows.append(["Room %s" % r.get("room"), smart.bed_label(b, i), LABEL[st], who or "—"])
    words = [f.get("status"), (f.get("gender") or "").lower(), (f.get("demographic") or "").lower()]
    label = " ".join(w for w in words if w) or "matching"
    nav = {"filters": {"status": f.get("status", "all"), "gender": f.get("gender", "all"), "demographic": f.get("demographic", "all"), "search": ""}}
    tab, named = _tab_in(t, ctx)
    if named or (ctx or {}).get("tab") != tab:
        nav["tab"] = tab
    if named:
        label += " in the " + TAB_LABEL[tab]
    if not rows:
        return R("screen_filter", "I set the filter to %s, but nothing matches right now, so the screen is empty. Say “clear the filters” to see everything again." % label, nav=nav)
    by_room = {}
    for x in rows:
        by_room.setdefault(x[0], []).append(x[1])
    shown = "; ".join("%s (%s)" % (k, ", ".join(v[:6]) + ("…" if len(v) > 6 else "")) for k, v in list(by_room.items())[:8])
    text = "Done: the screen now shows only %s %s. Report: %d bed%s in %d room%s — %s%s. Say “clear the filters” to see everything again." % (
        label, "rooms" if f.get("status") == "full" else "beds", len(rows), "" if len(rows) == 1 else "s", len(rooms_hit), "" if len(rooms_hit) == 1 else "s",
        shown, " and more" if len(by_room) > 8 else "")
    return R("screen_filter", text, [{"type": "table", "columns": ["Room", "Bed", "Status", "Who"], "rows": rows[:60]}], nav=nav,
             suggestions=["Clear the filters", "Show only the overdue beds"])


def viewer_nav(t):
    """Dormitory Viewer: the filter to click for 'show me what is vacant', 'show only female rooms'. No data is read here."""
    if CLEAR.search(t):
        return {"filters": {"status": "all", "gender": "all", "demographic": "all", "room": "all", "search": ""}}, "cleared"
    if not SHOW.match(t):
        return None, None
    f = _filters_from(t)
    out = {}
    if f.get("status") == "vacant":
        out["status"] = "vacant"
    elif f.get("status") == "full":
        out["status"] = "full"
    elif re.search(r"\bupcoming\b|\bsoon\b", t):
        out["status"] = "upcoming"
    for k in ("gender", "demographic"):
        if f.get(k):
            out[k] = f[k]
    if not out:
        return None, None
    names = {"vacant": "rooms that have a vacant bed", "full": "full rooms", "upcoming": "rooms with an upcoming vacancy"}
    label = ", ".join(x for x in [names.get(out.get("status"), ""), (out.get("gender") or "").lower(), (out.get("demographic") or "").lower()] if x)
    return {"filters": out}, label


# ------------------------------------------------------------------------------------------ find a dormitory (Super Admin / Marketing)
FIND = re.compile(r"^(find|search( for)?|look (for|up)|locate|where is|wheres|show( me)?|open|report( on| for| about)?|how is|hows|tell me about|check|"
                  r"give me (a )?(report|summary) (on|of|for|about)|status of|what about|do we have|is there)\b\s*(the |a |an |our |my )?")
DORM_WORDS = r"\b(dorm\w*|branch\w*|residences?|hall|house|building|the|a|an|please|now|report|status|vacanc\w*|data|details|info\w*|in the search( bar)?|search bar|bar|for me|and|then|give|me|its|it)\b"


def _dorm_match(text, names):
    """names: [name]. -> (best name or None, typed words)."""
    typed = re.sub(DORM_WORDS, " ", text)
    typed = re.sub(r"[^a-zñ0-9 ]", " ", typed)
    toks = [w for w in typed.split() if len(w) >= 2]
    if not toks:
        return None, ""
    best, score = None, 0
    for n in names:
        words = re.findall(r"[a-zñ0-9]+", (n or "").lower())
        s = 0
        for tk in toks:
            for w in words:
                if tk == w:
                    s += 3
                    break
                if len(tk) >= 4 and (w.startswith(tk) or difflib.SequenceMatcher(None, tk, w).ratio() >= 0.8):
                    s += 2
                    break
            else:
                s -= 1                                 # a typed word that is not part of this name
        if s > score:
            best, score = n, s
    return (best if score >= 2 else None), " ".join(toks)


def super_find(conn, uid, t):
    m = FIND.match(t)
    if not m or not agent.is_super(conn.cursor(), uid):
        return None
    rest = t[m.end():].strip(" ?.")
    if not rest or re.search(r"\b(highest|lowest|most|least|best|worst|all|every|each|trend|compare|which|pending|requests?|inbox|accounts?|security|server|analytics|"
                             r"overview|tab|page|how many|total|combined)\b", rest):
        return None
    cur = conn.cursor()
    allb = [(i, d) for i, d, _v in list_docs(cur, KINDS["branches"], [], limit=500) if d.get("requestedBy") == uid]
    name, typed = _dorm_match(rest, [d.get("dormName") for _i, d in allb])
    strong = t.startswith(("find", "search", "look", "locate", "where"))
    if not name:
        if not strong or not typed:
            return None
        return R("super_find", "I searched the Dormitories tab for “%s” and found nothing. Connected dormitories: %s." % (
            typed, ", ".join(str(d.get("dormName")) for _i, d in allb[:15]) or "none yet"), nav={"tab": "dorms", "search": typed})
    bid, doc = next((i, d) for i, d in allb if d.get("dormName") == name)
    shared = doc.get("analyticsStatus") == "approved"
    text = "Found it: I typed “%s” in the search bar. " % name
    blocks = []
    if not shared:
        text += "%s has not approved analytics sharing (directory: %s, analytics: %s), so I have no bed numbers to report yet." % (
            name, doc.get("dirStatus") or "—", doc.get("analyticsStatus") or "—")
    else:
        snaps = next((s for b, _d, s in agent.super_branches(cur, uid) if b == bid), [])
        if not snaps:
            text += "%s is connected but has not sent any data yet." % name
        else:
            last = snaps[-1]
            tot, vac = int(last.get("total") or 0), int(last.get("vacant") or 0)
            occ = int(last.get("occupied") if last.get("occupied") is not None else tot - vac)
            text += "Report for %s%s: %d beds, %d vacant, %d occupied (%s occupancy). Last update: %s." % (
                name, (" in " + doc["location"]) if doc.get("location") else "", tot, vac, occ, agent._p(agent._pct(occ, tot)),
                last["_t"].strftime("%b %-d, %Y"))
            week = [s for s in snaps if (last["_t"] - s["_t"]).days <= 7]
            if len(week) > 1:
                diff = vac - int(week[0].get("vacant") or 0)
                text += " Compared with a week ago: %s." % ("no change in vacant beds" if diff == 0 else "%d %s vacant bed%s" % (abs(diff), "more" if diff > 0 else "fewer", "" if abs(diff) == 1 else "s"))
            blocks = [{"type": "table", "columns": ["Dormitory", "Beds", "Vacant", "Occupied", "Occupancy"],
                       "rows": [[name, tot, vac, occ, agent._p(agent._pct(occ, tot))]]}]
    return R("super_find", text, blocks, nav={"tab": "dorms", "search": name}, suggestions=["Which dorm has the highest vacancy?", "Clear the search"])


def market_find(conn, uid, t):
    m = FIND.match(t)
    if not m:
        return None
    rest = t[m.end():].strip(" ?.")
    if not rest or re.search(r"\b(highest|lowest|most|least|best|worst|all|every|each|compare|which|how many|total|vacan\w*|available|female|male|students?|"
                             r"reviewees?|aircon\w*|mixed|cheap\w*|near|in [a-z]+ city)\b", rest):
        return None
    cur = conn.cursor()
    items = [d for _i, d, _v in list_docs(cur, KINDS["directory"], [], limit=500)]
    name, typed = _dorm_match(rest, [d.get("dormName") for d in items])
    strong = t.startswith(("find", "search", "look", "locate", "where"))
    if not name:
        if not strong or not typed:
            return None
        return R("market_find", "I searched the directory for “%s” and found no dormitory with that name. Listed: %s." % (
            typed, ", ".join(str(d.get("dormName")) for d in items[:15])), nav={"filter": "all", "search": typed})
    d = next(x for x in items if x.get("dormName") == name)
    g = lambda k: int(d.get(k) or 0)
    text = "Found it: I typed “%s” in the search bar. Report: %s%s has %d vacant bed%s out of %d (male %d, female %d, students %d, reviewees %d)." % (
        name, name, (" in " + d["location"]) if d.get("location") else "", g("vacant"), "" if g("vacant") == 1 else "s", g("total"),
        g("maleVacant"), g("femaleVacant"), g("studentVacant"), g("revieweeVacant"))
    return R("market_find", text, nav={"filter": "all", "search": name}, suggestions=["Which dorm has the most vacant beds?"])


# ------------------------------------------------------------------------------------------ read-only pages
PERSON_ASK = re.compile(
    r"^(is|are|was|does|did|has) (?!there\b|it\b|the\b|a\b|an\b|this\b|that\b|any\b|room\b|rooms\b|bed\b|beds\b|reserv\w*\b|vacan\w*\b|overdue\b|temporar\w*\b|upcoming\b|occup\w*\b)"
    r"[a-zñ]+( [a-zñ]+){0,2} (present|here|there|around|staying|still (here|staying)|a tenant|checked (in|out)|living here|in (the )?history|with (us|you))\b|"
    r"\b(tenant|resident|person|client|guest|someone|boarder|student) (named|called)\b|\bin (the )?tenant history\b|\btenant history\b|"
    r"\b(contacts?|contact details|numbers?|phone|mobile|cellphone|emergency contact|address|email) (of|for|ni|kay) (?!the\b|a\b|an\b|all\b|every\b|each\b|beds?\b|rooms?\b|"
    r"vacan\w*\b|tenants?\b|residents?\b|dorm\w*\b|branch\w*\b|occup\w*\b|reserv\w*\b|people\b|this\b|that\b|my\b|our\b|your\b)[a-zñ]+|"
    r"\b(records?|standing|reputation) (of|for|ni|kay) (?!the\b|a\b|an\b|all\b|every\b|each\b|beds?\b|rooms?\b|vacan\w*\b|tenants?\b|residents?\b|dorm\w*\b|"
    r"branch\w*\b|occup\w*\b|reserv\w*\b|people\b|this\b|that\b|my\b|our\b|your\b|check\w*\b)[a-zñ]+|\b(bad|good) record\b|"
    r"^(find|search for|search|look for|locate|where is) [a-zñ]+( [a-zñ]+)? (in|on|at) (the )?(room canvas|canvas|hallway|matrix|list|records?|history)\b")
CHANGE_VERB = re.compile(r"^(add|create|check ?in|checkin|check ?out|checkout|reserve|book|delete|remove|move|transfer|extend|assign|put|edit|update|"
                         r"rename|register|mark|make)\b")
PRIV_TEXT = {
    "viewer": "I can't look up a person here. The Dormitory Viewer only shows bed status and dates; tenant names, numbers and history stay with the "
              "dormitory's Branch Admin. I can tell you which beds are vacant, occupied or reserved.",
    "marketing": "I can't look up a person here. The directory only has vacancy counts for each dormitory; tenant names, numbers and history stay with "
                 "each dormitory's Branch Admin.",
    "superadmin": "I can't look up a person here. A Super Admin sees counts and statistics only; tenant names, numbers and history stay with each "
                  "dormitory's Branch Admin.",
}
RO_TEXT = {
    "viewer": "I can't do that here. The Dormitory Viewer is read-only, so nothing can be added, reserved, checked in or changed from this page. "
              "Ask the dormitory's Branch Admin. I can show you which beds are vacant or filter the page for you.",
    "marketing": "I can't do that here. The Marketing Viewer is read-only: it shows each dormitory's vacancy counts and nothing can be added or changed. "
                 "Contact the dormitory to reserve. I can find a dormitory or filter the list for you.",
    "superadmin": "I can't do that here. A Super Admin cannot change a branch's rooms, tenants or reservations; only that dormitory's Branch Admin can. "
                  "I can find a dormitory and report its numbers.",
}


def readonly_pages(conn, uid, t, page):
    """Dormitory Viewer, Marketing and Super Admin: people are private, changes are not possible, filters can be cleared."""
    if page not in PRIV_TEXT:
        return None
    if CLEAR.search(t) or re.search(r"^(clear|reset|remove)( the)? (search|filters?)\b", t):
        nav = {"viewer": {"filters": {"status": "all", "gender": "all", "demographic": "all", "room": "all", "search": ""}},
               "marketing": {"filter": "all", "search": ""}, "superadmin": {"tab": "dorms", "search": ""}}[page]
        return R("nav_filter", "Done: I cleared the filters, so everything is shown again.", nav=nav)
    if PERSON_ASK.search(t):
        return R("privacy", PRIV_TEXT[page])
    if CHANGE_VERB.match(t) and not re.search(r"\b(filters?|search|view|report|summary|comparison|chart|strateg\w*|plan|campaign|marketing|post|caption|"
                                              r"message|advert\w*|ad|list|recommendation|suggestion|sense)\b", t):
        if page != "superadmin" or re.search(r"\b(tenants?|beds?|rooms?|reserv\w*|clients?|check ?in|check ?out|checkout|guests?|residents?)\b", t):
            return R("read_only", RO_TEXT[page], suggestions=["How many beds are vacant?", "What can you do?"])
    if page == "viewer":
        m = re.match(r"^(find|search for|search|look for|locate|where is|wheres) ([a-zñ]+(?: [a-zñ]+)?)$", t.strip(" ?."))
        if m:
            import lang
            words = m.group(2).split()
            known = set(getattr(lang, "VOCAB", [])) | set(getattr(lang, "_ENGLISH", []))
            if not any(w in known or len(w) < 3 for w in words):
                return R("privacy", "If “%s” is a person, I can't search people here: tenant names stay with the Branch Admin. "
                         "If it is a room, say “show room %s”." % (m.group(2).title(), m.group(2)))
    return None


def super_show(conn, uid, t):
    """Super Admin: 'show me only the vacant' -> opens Dormitories and reports which dormitories have vacant beds."""
    if not SHOW.match(t) or not re.search(r"\b(vacan\w*|available|free|full|fully occupied)\b", t):
        return None
    if re.search(r"\b(trend|chart|analytics|highest|lowest|most|least|compare|report|tab|total|all|combined|how many|every|each|overall)\b", t):
        return None
    if not re.search(r"\b(only|just|filter\w*)\b", t) and len(t.split()) > 7:
        return None
    cur = conn.cursor()
    if not agent.is_super(cur, uid):
        return None
    rows = []
    for _bid, doc, snaps in agent.super_branches(cur, uid):
        if snaps:
            last = snaps[-1]
            tot, vac = int(last.get("total") or 0), int(last.get("vacant") or 0)
            rows.append([doc.get("dormName"), tot, vac, tot - vac])
    if not rows:
        return None
    full = bool(re.search(r"\b(full|fully occupied)\b", t))
    hit = sorted([r for r in rows if (r[2] == 0) == full], key=lambda r: -r[2])
    if not hit:
        return R("super_show", "No dormitory is %s right now." % ("full" if full else "showing a vacant bed"), nav={"tab": "dorms", "search": ""})
    text = ("%d dormitor%s full: %s." % (len(hit), "y is" if len(hit) == 1 else "ies are", ", ".join(str(r[0]) for r in hit)) if full else
            "I opened Dormitories. %d dormitor%s vacant beds: %s. Dormitories with vacancies are listed first on the page." % (
                len(hit), "y has" if len(hit) == 1 else "ies have", "; ".join("%s (%d)" % (r[0], r[2]) for r in hit[:10])))
    return R("super_show", text, [{"type": "table", "columns": ["Dormitory", "Beds", "Vacant", "Occupied"], "rows": hit}], nav={"tab": "dorms", "search": ""})


TABS = [("hallway", r"\bh(all|igh|al) ?wa+y\b|\bhallway layout\b|\bfloor plan\b|\blayout\b"), ("matrix", r"\b(bed )?matrix\b"),
        ("dashboard", r"\b(room )?canvas\b|\bdashboard\b"), ("analytics", r"\banalytics?\b")]


def _tab_in(t, ctx):
    """The tab the user named ('in the hallway'), or the one they are on, or Room Canvas."""
    for tab, pat in TABS:
        if re.search(pat, t):
            return tab, True
    here = (ctx or {}).get("tab")
    return (here if here in ("dashboard", "matrix", "hallway", "analytics") else "dashboard"), False


TAB_LABEL = {"hallway": "Hallway Layout", "matrix": "Bed Matrix", "dashboard": "Room Canvas", "analytics": "Analytics"}


def admin_nav(t, ctx):
    """Branch Admin: 'show me the vacant rooms' keeps its normal answer and also sets the screen filter."""
    if not re.match(r"^(show|display|view|see|let me see|list)\b", t):
        return None, None
    if re.search(r"\b(trend|floor|almost|fully|next|tomorrow|month|week|year|history|report|who|names?|contacts?|how many|by |per |each|longest|most|least|"
                 r"highest|lowest|compare|percent\w*|rate|chart|graph|soon|upcoming|today|expir\w*|room\s+[a-z]?-?\d)\b", re.sub(r"\bfloor plan\b", "", t)):
        return None, None
    f = _filters_from(t)
    if f.get("status") not in ("vacant", "overdue", "reserved", "temporary", "full"):
        return None, None
    nav = {"filters": {"status": f["status"], "gender": f.get("gender", "all"), "demographic": f.get("demographic", "all"), "search": ""}}
    tab, named = _tab_in(t, ctx)
    if named or (ctx or {}).get("tab") != tab:
        nav["tab"] = tab
    label = " ".join(w for w in [f["status"], (f.get("gender") or "").lower(), (f.get("demographic") or "").lower()] if w)
    return nav, label + ((" in the " + TAB_LABEL[tab]) if named else "")


# ------------------------------------------------------------------------------------------ who are you / who made this / my name
WHO_YOU = re.compile(r"^(and |so |but |hey |hi |hello |ok |okay )?((who|hu|wat|what|sino|kinsa) ?(are|r|is|ba|ang|man)? ?(you|u|ya|ikaw|ka|this|dis)( are| r| is)?( really| exactly| ba| man| diay)?|"
                     r"who (are|r) (you|u) (really|exactly|anyway)|what are you|introduce (yourself|urself)|tell me (about|who) (yourself|you are)|"
                     r"(can|could) (you|u) introduce (yourself|urself)|your name|(what|whats) (is )?(your|ur) name|kinsa ka|sino ka|ikaw kinsa|who am i (talking|chatting|speaking) (to|with))[ ?!.]*$")
CREATOR = re.compile(r"\b(who|sino|kinsa|whos|name of)\b.*\b(creat\w*|made|make|makes|built|build|develop\w*|program\w*|design\w*|own\w*|author\w*|invent\w*|behind|gumawa|"
                     r"naghimo|nagbuhat|code[dr]?|wrote|write)\b|\b(creator|developer|maker|author|owner|programmer|inventor|founder)\b.*\b(of|ng|sa|this|the|you|your)\b|"
                     r"\b(who|whose) (is|are)? ?(the )?(creator|developer|maker|author|owner|programmer|founder)\b|\bcreated by (who|whom)\b|\bwho (do|does) (this|you|it) belong\b")
NAME_SAY = re.compile(r"^(?:(?:hi|hello|hey|good (?:morning|afternoon|evening))[ ,!.]*)?(?:my name is|my name's|i am called|call me|you can call me|ako si|ako ay si|ako ni|"
                      r"ang pangalan ko ay|pangalan ko ay|akong pangalan kay|akong ngalan kay|i am|i'm|im|this is)\s+([a-zñ][a-zñ .'-]{1,40}?)[ .!]*$")
NAME_ASK = re.compile(r"\b(what is|whats|do you (know|remember)|tell me|say) my name\b|\bwho am i\b|\bkinsa ko\b|\bsino ako\b|\bmy name\?$|"
                      r"\b(do|can|did) (you|u) (know|recogni[sz]e|remember) (me|who i am)\b|\b(you|u) (know|recogni[sz]e|remember) me\b|\bkilala mo (ba )?ako\b|\bkaila ka (ba )?nako\b")
NOT_NAME = set("""a an the here there fine ok okay good great sad happy tired confused lost new old sure sorry ready done busy back late not so very really
the admin owner manager staff viewer student reviewee tenant resident user branch super marketing looking trying asking going resigning leaving having
your his her their from in at on with about also just still now curious wondering""".split())


DEV = re.compile(r"\b(ter+in+s?|ter+ins|terins|terrin|terrence|hortelano|hortilano|hortelanio|ortelano)\b")
DEV_STORY = ("Terrins T. Hortelano (Mr. Hortelano, Terrins) is the developer of this website. He designed and built the Vecancy Tracker, and me, its AI assistant, "
             "to help dormitory staff see which beds are vacant, occupied or reserved at any moment, keep tenant records, reservations and check-outs in one place, "
             "and stop double-booking and paper lists.")
PAGE_HELP = {
    "admin": "On this Branch Admin page I can count and list your beds, report one room, find a tenant, prepare check-ins, check-outs, reservations and new rooms "
             "for you to confirm, filter or scroll the screen, and explain any part of the tracker.",
    "viewer": "On this Dormitory Viewer page I can tell you which beds are vacant or occupied, report one room, filter the page and explain the colours. "
              "It is read-only, and I never share tenant names.",
    "marketing": "On this Marketing Viewer page I can tell you which dormitory has vacant beds, find a dormitory and filter the list. I never share tenant names.",
    "superadmin": "On this Super Admin page I can report and compare the dormitories that approved sharing, find one dormitory and open any tab. "
                  "I only see totals, never tenant names.",
}
ASK_ME = {"admin": ["How many beds are vacant?", "Show me only the vacant beds", "What can you do?"],
          "viewer": ["How many beds are vacant?", "Show me what is vacant", "What can you do?"],
          "marketing": ["Which dorm has the most vacant beds?", "What can you do?"],
          "superadmin": ["Which dorm has the highest vacancy?", "What can you do?"]}
GREET = re.compile(r"^(hi+|hello+|helo+|hey+|heya|hiya|yo|sup|hola|oi|uy|hoy|psst|greetings|good ?(morning|afternoon|evening|day|noon)|gud ?(morning|am|pm|evening|eve)|"
                   r"morning|afternoon|evening|magandang (umaga|hapon|gabi|araw|tanghali)|maayong (buntag|hapon|gabii|adlaw|udto)|kumusta|kamusta|musta|"
                   r"hello there|hi there|hey there|whats up|what's up|wassup|ayo|mabuhay|maayo)( (po|ai|assistant|bot|there|friend|buddy|sir|maam|everyone|again|you))*[ !.?,]*$")


def _local_hour(ctx):
    try:
        ms = float((ctx or {}).get("now") or 0) or datetime.now(timezone.utc).timestamp() * 1000
        return int(((ms / 1000) - float((ctx or {}).get("tzOffset") or 0) * 60) // 3600 % 24)
    except Exception:
        return datetime.now(timezone.utc).hour


def _my_name(conn, uid):
    try:
        return agent.mem_all(conn.cursor(), uid).get("name")
    except Exception:
        return None


def _is_dev(name):
    return bool(name and DEV.search(name.lower()) and re.search(r"hortelano|terrins|terins", name.lower()))


def about_me(conn, uid, t, raw, page, ctx=None):
    """Greetings, 'who are you', 'who created this website', 'who is Terrins Hortelano', 'my name is …', 'what is my name'."""
    low = re.sub(r"\s+", " ", (raw or t or "").lower()).strip()
    low_c = low.strip(" ?!.")
    p = page if page in PAGE_HELP else "admin"
    me = _my_name(conn, uid)
    # ---- a greeting starts a short, friendly conversation (different every time of day, uses your name)
    if GREET.match(low) or GREET.match(t):
        h = _local_hour(ctx)
        part = "Good morning" if 5 <= h < 12 else "Good afternoon" if 12 <= h < 18 else "Good evening"
        if re.search(r"\b(morning|umaga|buntag|am)\b", low):
            part = "Good morning"
        elif re.search(r"\b(afternoon|hapon|noon|tanghali|udto)\b", low):
            part = "Good afternoon"
        elif re.search(r"\b(evening|gabi|gabii|eve|pm)\b", low):
            part = "Good evening"
        who = (", " + me.split()[0]) if me else ""
        if _is_dev(me):
            text = "%s, Mr. Hortelano! Welcome back to your own creation. I'm the assistant you built into the Vecancy Tracker, ready when you are." % part
        else:
            opening = ["%s%s! I'm the Vecancy Tracker assistant, made by the developer Mr. Hortelano, Terrins, to help you with this dormitory system.",
                       "%s%s! Nice to see you. I'm your Vecancy Tracker assistant, built by Mr. Hortelano, Terrins, and I'm ready to help.",
                       "%s%s, and welcome! I'm the AI assistant of the Vecancy Tracker, created by the developer Mr. Hortelano, Terrins."]
            text = opening[(datetime.now(timezone.utc).minute + len(low)) % len(opening)] % (part, who)
        if re.search(r"\b(kumusta|kamusta|musta|whats up|what's up|wassup|sup)\b", low):
            text += " I'm doing well, thank you for asking."
        text += " " + {"admin": "You can ask me things like “how many beds are vacant?” or tell me “reserve a bed for Ana, female student”.",
                       "viewer": "You can ask me things like “how many beds are vacant?” or “show me what is vacant”.",
                       "marketing": "You can ask me things like “which dorm has vacant beds for females?”.",
                       "superadmin": "You can ask me things like “which dorm has the highest vacancy?” or “find Sanciangko dorm”."}[p]
        if not me:
            text += " What is your name?"
        return R("greeting", text, suggestions=ASK_ME[p])
    # ---- who are you: the full introduction
    if WHO_YOU.match(low) or WHO_YOU.match(t):
        text = ("Hello, I am an AI assistant created by the developer Mr. Hortelano, Terrins. I am here to help you. "
                "I live inside the Vecancy Tracker, the dormitory system he built, and I read the same live records you see on this page, so my numbers are real, not guesses. "
                + PAGE_HELP[p] + " I understand English, Tagalog and Cebuano, even with wrong spelling, and I can read my answers aloud or listen to your voice. "
                "I never change anything unless you press Confirm.")
        if me:
            text += " And I remember you: you are %s%s." % (me, ", my developer" if _is_dev(me) else "")
        return R("identity", text, [{"type": "list", "items": CAN[p][:5]}], suggestions=["What are your limitations?", "Who created this website?"])
    # ---- who is Terrins Hortelano / do you know your developer
    asks_dev = DEV.search(low) and re.search(r"\b(who|whos|sino|kinsa|do you know|you know|know|kilala|kaila|tell me about|about|what (do|did)|is he|did he|why did|"
                                             r"recogni[sz]e|remember|heard of|what is|whats|developer|creator|made|created|built)\b", low) and \
        not re.search(r"\b(present|staying|check ?in|check ?out|checkout|history|record|reserve|room|bed|contact|number|temporary|add|find|search|locate|where)\b", low)
    if asks_dev:
        extra = ""
        if page in (None, "", "admin"):                 # only the Branch Admin may also hear about a tenant with the same name
            try:
                toks = [w for w in re.findall(r"[a-zñ]+", low) if DEV.fullmatch(w)]
                rec = smart.Records(conn.cursor(), uid)
                hit = next(((r, i, b) for r, i, b in rec.occupied() if _name_score(toks, b.get("tenant"))), None)
                if hit:
                    extra = " By the way, your records also have a tenant with that name: %s in Room %s." % (hit[2].get("tenant"), hit[0].get("room"))
            except Exception:
                extra = ""
        why = re.search(r"\bwhy\b", low)
        return R("creator", ("He built it " + DEV_STORY.split(" to help ", 1)[1][:-1].join(["to help ", "."]) if why else "Yes, I know him. " + DEV_STORY) + extra,
                 suggestions=["Who are you?", "What can you do?"])
    if (CREATOR.search(low) or CREATOR.search(t)) and re.search(r"\b(you|u|this|website|web ?site|site|app|application|system|tracker|program|page|platform|software|ai|assistant|"
                                                               r"bot|it|vecancy|vacancy|project)\b", low) and not re.search(r"\b(rooms?|tenants?|reservations?|report|beds?|record)\b", low):
        about_ai = re.search(r"\b(you|u|ai|assistant|bot)\b", low) and not re.search(r"\b(website|web ?site|site|app|system|tracker|program|page|platform|software|project)\b", low)
        return R("creator", ("I was created by the developer Mr. Hortelano, Terrins (Terrins T. Hortelano). He built me into the Vecancy Tracker so that dormitory staff "
                             "can simply ask for what they need instead of searching through tabs.") if about_ai else
                 "This website, the Vecancy Tracker, was created by the developer Mr. Hortelano, Terrins (Terrins T. Hortelano). He designed and built it, and me, "
                 "its AI assistant, to help dormitory staff see which beds are vacant, occupied or reserved at any moment, keep tenant records, reservations and "
                 "check-outs in one place, and stop double-booking and paper lists.", suggestions=["Who are you?"])
    if re.search(r"\b(why|what for|purpose|goal|para (sa )?(asa|saan|unsa|ano))\b", low) and re.search(r"\b(this )?(website|web ?site|app|system|tracker|vecancy|vacancy tracker)\b", low) and \
            re.search(r"\b(made|created|built|exist\w*|for|purpose|goal|use|about)\b", low) and not re.search(r"\b(room|bed|tenant|tab)s?\b", low):
        return R("creator", "The Vecancy Tracker exists to help dormitory staff see which beds are vacant, occupied or reserved at any moment, keep tenant records, "
                 "reservations and check-outs in one place, and avoid double-booking. It was created by the developer Mr. Hortelano, Terrins.")
    m = NAME_SAY.match(low_c)
    if m:
        words = [w.strip(".'-") for w in m.group(1).split()]
        plain = low_c.startswith(("i am", "i'm", "im ", "this is"))
        import lang
        known = set(getattr(lang, "VOCAB", [])) | set(getattr(lang, "_ENGLISH", []))
        if words and len(words) <= 3 and not any(w in NOT_NAME for w in words) and not (plain and any(w in known for w in words)):
            name = " ".join(w.capitalize() for w in words if w)
            try:
                with conn.transaction():
                    agent.mem_set(conn.cursor(), uid, "name", name[:60])
            except Exception:
                pass
            if _is_dev(name):
                return R("name_saved", "Mr. Hortelano! I recognize you: you are Terrins T. Hortelano, the developer who created this website and me. "
                         "It is good to talk to my creator. I'll remember it is you. What shall we work on?")
            return R("name_saved", "Nice to meet you, %s! I'll remember your name. How can I help you today?" % name)
    if NAME_ASK.search(low_c):
        try:
            name = agent.mem_all(conn.cursor(), uid).get("name")
        except Exception:
            name = None
        if _is_dev(name):
            return R("name_recall", "Your name is %s. You are my developer, the one who created this website." % name)
        return R("name_recall", ("Your name is %s." % name) if name else "You haven't told me your name yet. Say “my name is …” and I'll remember it.")
    return None


# ------------------------------------------------------------------------------------------ scroll and slide
MOVE = re.compile(r"\b(scroll\w*|scrol\w*|slide\w*|slid\w*|swipe\w*|move (the )?(page|screen|view)|page (up|down)|go (up|down|to the (top|bottom))|"
                  r"(back|go|jump|return) to (the )?(top|bottom|start|end)|pan)\b")


def screen_move(t, raw, page):
    """'can you scroll down?', 'scroll down a little bit', 'slide right the checkout dates', 'go to the top'."""
    low = re.sub(r"\s+", " ", (raw or t or "").lower()).strip(" ?!.")
    low = re.sub(r"\bscroo+l\w*|\bscrol\b|\bscrool\b|\bskrol\w*", "scroll", low)
    low = re.sub(r"\bslie?d\b|\bslaid\b|\bslied\b", "slide", low)
    low = re.sub(r"\bri+f*gh*t\b|\brigth\b|\brght\b", "right", low)
    low = re.sub(r"\blef\b|\bletf\b", "left", low)
    if not MOVE.search(low) or re.search(r"\b(how (do|to|can) i|what is|what does|why)\b", low):
        return None
    if re.search(r"\b(tenant|resident|client|guest)\b.*\bto (room|bed)\b", low):
        return None
    slide = bool(re.search(r"\b(slide\w*|swipe\w*|pan)\b", low))
    d = ("top" if re.search(r"\b(to (the )?(very )?(top|start|beginning)|all the way up|pinakataas)\b", low) else
         "bottom" if re.search(r"\b(to (the )?(very )?(bottom|end)|all the way down|pinakababa)\b", low) else
         "left" if re.search(r"\b(left|previous|prev|back|earlier|wala|kaliwa)\b", low) else
         "right" if re.search(r"\b(right|next|forward|later|tuo|kanan)\b", low) else
         "up" if re.search(r"\b(up|upward|taas|pataas|itaas|saka)\b", low) else
         "down" if re.search(r"\b(down|downward|baba|pababa|ibaba|ubos|more|further)\b", low) else
         ("right" if slide else "down"))
    amount = ("little" if re.search(r"\b(little|bit|slightly|small|kaunti|konti|gamay|a tad|slowly)\b", low) else
              "lot" if re.search(r"\b(a lot|lot|much|far|more|big|plenty|daghan|marami|fast|way)\b", low) else "normal")
    target = ("checkout" if re.search(r"\bcheck ?outs?\b|\bdates?\b|\bcalendar\b|\bschedule\b|\bmonths?\b|\breminders?\b", low) else
              "hallway" if re.search(r"\bhall ?way\b|\blayout\b|\bfloor plan\b", low) else
              "matrix" if re.search(r"\bmatrix\b|\btable\b", low) else
              "chat" if re.search(r"\b(chat|conversation|messages?)\b", low) else None)
    how = {"little": "a little", "lot": "a lot", "normal": ""}[amount]
    if d in ("top", "bottom"):
        text = "Done: I went to the %s of the page." % d
    elif d in ("left", "right"):
        text = "Done: I slid %s%s%s." % ((("the %s " % {"checkout": "check-out dates", "hallway": "Hallway Layout", "matrix": "Bed Matrix", "chat": "chat"}[target]) if target else ""),
                                         "to the " + d, (" " + how) if how else "")
    else:
        text = "Done: I scrolled %s%s." % (d, (" " + how) if how else "")
    nav = {"scroll": {"dir": d, "amount": amount, "target": target}}
    if page in (None, "", "admin") and target == "checkout" and d in ("left", "right"):
        nav["tab"] = "calendar"                         # the check-out month wheel lives in Checkout Schedule
        text = "Done: I opened Checkout Schedule and slid the check-out months to the %s (%s month)." % (d, "previous" if d == "right" else "next")
    return R("screen_move", text, nav=nav)


# ------------------------------------------------------------------------------------------ everyday conversation
TALK = [
    (r"^(thanks?|thank you|thank u|thx|ty|tnx|salamat|daghang salamat|maraming salamat|thanks a lot|thank you (so|very) much|appreciate it)( po| kaayo| ai| assistant)*$",
     ["You're welcome! Tell me if you need anything else.", "Happy to help. Anything else?", "Anytime! I'm here if you need more."]),
    (r"^(bye+|goodbye|good ?night|see you|see ya|later|paalam|babay|sige na|adios|i have to go|gotta go|im leaving|i'm leaving)( po| now| ai| assistant| for now)*$",
     ["Goodbye! Your chat is saved, so you can continue any time.", "See you! I'll be here when you come back."]),
    (r"^(how are you|how r u|how are u|how are you doing|how are you today|how is it going|hows it going|kumusta ka|kamusta ka|musta ka|are you ok|are you okay|you good)\b",
     ["I'm doing well, thank you for asking! Ready to help with your dormitory. How about you?"]),
    (r"^(i am|im|i'm|i feel) (fine|good|great|ok|okay|well|happy|alright)( too| also| thanks| thank you)*$|^(fine|good|great|ok lang|okay lang|maayo|mabuti)( too| thanks| thank you| man| naman)*$",
     ["Glad to hear that! What would you like to do in the tracker?"]),
    (r"^(i am|im|i'm|i feel) (so |very |really |a bit )?(tired|sad|stressed|busy|bored|sleepy|confused|lost|sick|kapoy|pagod)\b",
     ["I'm sorry to hear that. Let me take some work off you: tell me what you need, for example “how many beds are vacant?”, and I'll do the looking."]),
    (r"^(nice to meet you|pleased to meet you|good to meet you|glad to meet you)\b",
     ["Nice to meet you too! What can I do for you today?"]),
    (r"^(are you (there|here|awake|online|alive|listening|working)|you there|hello\?+|anybody (there|home)|can you hear me|do you hear me|testing|test|mic test|check)$",
     ["Yes, I'm here and listening. What do you need?"]),
    (r"^(sorry|my bad|im sorry|i'm sorry|pasensya|pasayloa|oops|ops)\b",
     ["No problem at all. What would you like to do?"]),
    (r"^(ha+|he+|haha+|hehe+|lol|lmao|hihi+|hahaha+|😂|🤣)$", ["Glad that made you smile. What's next?"]),
    (r"^(wow|nice|cool|great|awesome|amazing|perfect|excellent|galing|ayos|nindot|ang galing|very good|good job|well done|nice one|you are (smart|good|great|amazing|the best))\b",
     ["Thank you! I'm glad it helped. Anything else?"]),
    (r"\b(what (can|should) i (ask|say)|what do i (ask|say)|how do i (use|talk to|ask) you|how to use (you|this ai|the assistant)|teach me how to use you)\b",
     ["Just type or say what you need in your own words. Examples: “how many vacant in Room S-105”, “is Ana Reyes present?”, “show me only the vacant beds”, "
      "“scroll down”, “reserve a bed for Ana, female student, check in today”. Anything that changes data waits for your Confirm."]),
    (r"\b(do you (sleep|eat|rest|get tired)|are you tired|do you have (feelings|emotions|a family|friends|a boss))\b",
     ["I'm a program, so I don't sleep, eat or get tired. I'm ready any time you open this page."]),
    (r"\b(where (are|do) you (live|from|stay)|where are you)\b", ["I live inside the Vecancy Tracker website. Wherever you open it, I'm there."]),
    (r"\b(can you (speak|talk)|do you (speak|talk)|can you read (it|that|this) (aloud|out loud)|do you have a voice)\b",
     ["Yes. I read every answer aloud with the browser's voice. Use the speaker button at the top of this chat to turn my voice on or off, "
      "and the microphone button to speak your question."]),
    (r"^(i love you|love you|ily|i like you|mahal kita|gihigugma tika)\b", ["Thank you, that's kind! I like helping you too."]),
    (r"\b(you are|ur|you're|youre|your) (so |very |really )?(stupid|dumb|useless|bad|wrong|bobo|tanga|bugo|slow|annoying|trash|bullshit)\b|^(bullshit|stupid|useless|bobo|tanga|bugo|hays+|haist+|ugh+)\b",
     ["I'm sorry I let you down. Tell me the exact sentence that failed, or ask it another way, and I'll do my best. You can also say “what can you do?”."]),
    (r"^(yes|yep|yeah|oo|sige|sure|ok|okay|go|go ahead|please do|do it|proceed|continue)[ .!]*$",
     ["Okay. Nothing is waiting for a yes right now. Tell me what you would like to do."]),
    (r"^(no|nope|nah|dili|hindi|ayaw)[ .!]*$", ["Okay. Nothing was changed. Tell me if you need something else."]),
    (r"^(wait|hold on|one moment|a moment|sandali|teka|kadali)\b", ["Take your time. I'm here when you're ready."]),
    (r"^(nothing|never mind|nvm|wala|wala lang|none)$", ["Alright. I'm here if you need me."]),
    (r"\b(what is (this|the) (website|app|system|page)|what does this (website|app|system) do|what is (the )?(vecancy|vacancy) tracker|about this (website|app|system))\b",
     ["This is the Vecancy Tracker, a dormitory management system. It shows which beds are vacant, occupied, reserved or overdue, keeps tenant records and reservations, "
      "reminds you about check-outs, and lets viewers see availability without seeing private details. It was created by the developer Mr. Hortelano, Terrins."]),
]


def small_talk(conn, uid, t, raw, page, draft=False):
    low = re.sub(r"\s+", " ", (raw or t or "").lower()).strip(" ?!.,")
    for n, (pat, answers) in enumerate(TALK):
        if re.search(pat, low) or re.search(pat, (t or "").strip(" ?!.,")):
            if draft and n >= 16:                        # "yes" / "no" / "wait" may be an answer to a pending question
                return None
            text = answers[(len(low) + datetime.now(timezone.utc).minute) % len(answers)]
            me = _my_name(conn, uid)
            if me and n in (0, 1, 5) and not text.startswith("Happy"):
                text = text.replace("!", ", %s!" % me.split()[0], 1)
            return R("smalltalk", text)
    return None


# ------------------------------------------------------------------------------------------ commands for the page itself
def ui_command(t, raw, page):
    """'switch to dark mode', 'start the tutorial', 'mute your voice', 'read that again', 'close the chat', 'refresh', 'sign me out'."""
    low = re.sub(r"\s+", " ", (raw or t or "").lower()).strip(" ?!.,")
    low = command_form(low)
    if re.search(r"\b(how (do|to|can) i|what is|what does|where is|explain)\b", low):
        return None
    ui = None
    if re.search(r"\b(dark|night|black)\s*(mode|theme)\b|\bmake it dark\b|\bturn (off|down) the lights?\b|\bdarken\b", low):
        ui, text = {"theme": "dark"}, "Done: I switched the page to dark mode."
    elif re.search(r"\b(light|day|white|bright)\s*(mode|theme)\b|\bmake it (light|bright)\b|\bturn on the lights?\b|\bbrighten\b", low):
        ui, text = {"theme": "light"}, "Done: I switched the page to light mode."
    elif re.search(r"\b(change|switch|toggle|swap)\b.*\b(theme|mode|colou?rs?)\b", low) and \
            not re.search(r"\bcolou?rs?\s+(?:of\s+\S+\s+)?(?:to|into)\s+[a-z#]", low) and \
            not re.search(r"\b(change|switch|swap)\s+(?!the\s+(?:page|screen|app|site)\b)(?!(?:the\s+)?(?:theme|mode|colou?rs?)\b)\S+(?:\s+\S+)?\s+colou?rs?\b", low):
        # "change cr color to blue" / "change the colour of cr to red" is about a hallway shape, not the page theme
        ui, text = {"theme": "toggle"}, "Done: I switched the theme."
    elif re.search(r"\b(start|open|show|play|run|begin|launch|watch|give me|teach me)\b.*\b(tutorial|toturial|tour|guide|walk ?through)\b|^(tutorial|toturial|tour)( please)?$", low):
        ui, text = {"tutorial": True}, "Starting the tutorial for this page. Press Next to move on and Skip tutorial to stop."
    elif re.search(r"\b(mute|silence|quiet|shut up|stop (talking|speaking|reading)|turn off (your |the )?(voice|sound|audio)|voice off|no voice|dont (talk|speak|read)|"
                   r"don't (talk|speak|read)|be quiet|hilom|tahimik)\b", low):
        ui, text = {"voice": "off"}, "Okay, I'll stay quiet. My voice is off; say “turn on your voice” to hear me again."
    elif re.search(r"\b(unmute|turn on (your |the )?(voice|sound|audio)|voice on|speak (again|to me|out loud|up)|talk (again|to me)|read (it|them|your answers?) (aloud|out loud)|"
                   r"use your voice|i want to hear you)\b", low):
        ui, text = {"voice": "on"}, "My voice is on. I'll read my answers aloud from now on."
    elif re.search(r"\b(repeat|say (that|it) again|read (that|it) again|again please|come again|one more time|pakiulit|usba|balika)\b", low) and len(low.split()) <= 6:
        ui, text = {"repeat": True}, "Here is my last answer again."
    elif re.search(r"\b(close|hide|minimi[sz]e|exit|dismiss)\b.*\b(chat|assistant|window|this|panel|yourself|you)\b|^(close|hide|go away)$", low):
        ui, text = {"close": True}, "Closing the chat. Click the assistant button when you need me again."
    elif re.search(r"\b(refresh|reload)\b( the| this)?( page| screen| data| website)?$", low):
        ui, text = {"reload": True}, "Refreshing the page now."
    elif re.search(r"\b(sign|log) ?(me )?(out|off)\b|\blogout\b|\bsignout\b", low):
        ui, text = {"signout": True}, "Signing you out now. See you next time!"
    elif re.search(r"\b(new|fresh|another|start a new|clear (the|this)) (chat|conversation)\b|\bstart over\b", low) and not re.search(r"\bhistory\b", low):
        ui, text = {"newchat": True}, "Starting a new chat."
    elif re.search(r"\b(full ?screen|maximi[sz]e|(expand|enlarge) (the |this |your )?(chat|window|assistant|panel)|make (it|the chat|you) (big|bigger|larger|wide))\b", low):
        ui, text = {"expand": True}, "Done: I made the chat bigger."
    elif re.search(r"\b(print)\b( the| this)?( page| screen| report)?$", low):
        ui, text = {"print": True}, "Opening the print window for this page."
    elif re.search(r"\bgo back\b|\bprevious page\b", low) and len(low.split()) <= 4:
        ui, text = {"back": True}, "Going back."
    if not ui:
        return None
    return R("ui_command", text, nav={"ui": ui})
