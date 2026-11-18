"""Language understanding for the assistant: spelling fixes, synonyms and a small classifier TRAINED on
example sentences (no outside AI service, no API key).

How it works
  1. normalize(): lower-case, expand short forms ("pls", "rm", "u"), map synonyms ("boys" -> male,
     "free/available/open beds" -> vacant), and fix misspellings of the app's own words with difflib
     ("vacncy" -> vacancy, "hallwy" -> hallway).
  2. classify(): compares the sentence with every training example using character 3-gram vectors
     (cosine similarity) plus word overlap, and returns the best intent if it is clearly similar.
     To teach it something new, add example sentences to EXAMPLES below — no code changes are needed.
"""
import math
import re
from collections import Counter
from difflib import get_close_matches

import lang

SHORT = {"pls": "please", "plz": "please", "pls.": "please", "u": "you", "ur": "your", "r": "are", "wat": "what",
         "wht": "what", "hw": "how", "hm": "how many", "rm": "room", "rms": "rooms", "bd": "bed", "bds": "beds",
         "thx": "thanks", "tnx": "thanks", "abt": "about", "w/": "with", "info": "information", "stats": "statistics",
         "stat": "statistics", "nxt": "next", "wk": "week", "wks": "weeks", "mo": "month", "yr": "year",
         "dorm": "dorm", "dorms": "dorms", "dormitory": "dorm", "dormitories": "dorms", "ppl": "people",
         "im": "i am", "dont": "do not", "cant": "cannot", "whats": "what is", "wheres": "where is", "hows": "how is",
         "gimme": "give me", "opn": "open", "goto": "go to", "shw": "show", "hallwy": "hallway", "rprt": "report", "repot": "report", "lemme": "let me", "wanna": "want to", "gonna": "going to", "nd": "and"}
PHRASES = [  # (pattern, replacement) applied in order, on whole words
    (r"\b(boys?|guys?|men|man|males?|lalaki)\b", "male"),
    (r"\b(girls?|ladies|lady|women|woman|females?|babae)\b", "female"),
    (r"\b(co-?ed|unisex|mixed gender)\b", "mixed"),
    (r"\b(free|available|open|unoccupied|empty|bakante)\s+(beds?|slots?|spaces?|rooms?)\b", r"vacant \2"),
    (r"\b(bed ?spaces?|slots?)\b", "beds"),
    (r"\b(moving out|move out|leaving|check ?outs?|checking out|departures?|contract ends?)\b", "checkout"),
    (r"\b(moving in|move in|arriving|arrivals?|check ?ins?|checking in)\b", "checkin"),
    (r"\b(soon to be vacant|about to be vacant|will be vacant|becoming vacant|opening up|upcoming vacanc(y|ies))\b", "upcoming vacancy"),
    (r"\b(occupancy rate|how full)\b", "occupancy"),
    (r"\b(show|display|bring up|pull up)\b", "show"),
    (r"\b(take me|bring me|lead me|direct me|redirect me)\b", "take me"),
    (r"\b(hall ?way|hallway map|floor ?plan|floor map|map)\b", "hallway"),
]
VOCAB = """vacancy vacancies vacant occupied occupancy reserved reservation reservations upcoming checkout checkin
hallway analytics vacancies report summary compare comparison room rooms bed beds tenant tenants male female mixed
students reviewees students student reviewee dorm dorms server canvas matrix calendar schedule history transfer central
memory remember forget format table bullet detailed statistics increase decrease why trend forecast risk highest lowest
available overdue temporary guests contact number navigate open show week month today tomorrow""".split()


def normalize(text):
    t = re.sub(r"[“”\"'’`]", "", str(text or "").lower())
    t = re.sub(r"[^a-z0-9+#:/\-. ]+", " ", t)
    words = []
    for w in t.split():
        w2 = w.strip(".")
        if w2 in SHORT:
            words.append(SHORT[w2])
            continue
        if len(w2) >= 5 and w2.isalpha() and w2 not in VOCAB and w2 not in lang.VOCAB and w2 not in lang._ENGLISH:
            hit = get_close_matches(w2, VOCAB, n=1, cutoff=0.82)
            if hit and hit[0][0] == w2[0] and abs(len(hit[0]) - len(w2)) <= 1:   # obvious typos only ("check" stays "check")
                w2 = hit[0]
        words.append(w2)
    t = " ".join(words)
    for pat, rep in PHRASES:
        t = re.sub(pat, rep, t)
    return re.sub(r"\s+", " ", t).strip()


# --------------------------------------------------------------------------- training examples
EXAMPLES = {
    "vacancy_summary": ["how many beds are vacant", "how many vacant beds are there", "any vacant beds", "is there space",
                        "are there available beds", "how many free beds do we have", "vacancy now", "current vacancy",
                        "how many beds are left", "is the dorm full", "total vacant", "count of vacant beds",
                        "how many slots are available", "do you have vacancy", "vacant beds for male", "how many beds for female are vacant"],
    "occupancy_summary": ["how many beds are occupied", "occupancy rate", "how full is the dorm", "how many tenants are there",
                          "how many people live here", "occupied beds count", "what is the occupancy"],
    "upcoming": ["show upcoming vacancies", "which beds will be vacant soon", "who is leaving soon", "when will a bed be free",
                 "next checkout", "beds opening up this week", "upcoming checkouts", "when is the next vacancy",
                 "list the checkouts this month", "what beds become available next week"],
    "checkins": ["scheduled check ins", "who is arriving", "reserved beds", "upcoming reservations", "when do reservations start",
                 "how many reservations"],
    "compare": ["compare male and female", "male vs female vacancy", "compare students and reviewees", "which is more vacant male or female",
                "compare rooms", "compare categories", "difference between boys and girls rooms", "compare by gender"],
    "report": ["report the vacancy", "give me a vacancy report", "make a report", "vacancy report please", "summary report",
               "generate report", "status report", "full report on vacancy", "overview of the dorm", "give me a summary"],
    "explain": ["explain the statistics", "what does occupancy rate mean", "explain these numbers", "what is upcoming vacancy",
                "what do the colors mean", "explain the legend", "what is overdue", "how is vacancy calculated", "explain the stats"],
    "trend": ["why did vacancy increase", "why is vacancy going up", "vacancy trend", "what changed", "why did it drop",
              "how will vacancy change", "forecast the vacancy", "what will happen next month", "trend of occupancy"],
    "room_status": ["show me the occupancy status", "status of this room", "what about this room", "is this room full",
                    "who is in this room", "beds in room 201", "room 205 status", "tell me about room 210", "occupancy of the selected room"],
    "highest": ["which dorm has the highest vacancy", "most vacant dorm", "which room has the most vacant beds", "where is the most space",
                "best dorm for availability", "which branch is the emptiest", "lowest occupancy"],
    "nav_hallway": ["open the hallway", "go to the hallway layout", "show the map", "take me to the floor plan", "hallway please"],
    "nav_analytics": ["open analytics", "show the charts", "go to statistics", "take me to analytics", "show graphs"],
    "nav_vacancies": ["open vacancies", "show the room cards", "go to the vacancy list", "show all rooms", "vacancies tab"],
    "memory_show": ["what do you remember", "show my memory", "what do you know about me", "my saved preferences"],
    "help": ["what can you do", "help", "how do i use this", "what can i ask", "commands", "how does this work", "hello", "hi"],
    "admin_only": ["check out a tenant", "delete this room", "add a tenant", "update the contact number", "change the bed assignment",
                   "edit the room", "remove the reservation", "create a reservation", "move a tenant", "show tenant names",
                   "who lives in room 201", "give me the tenant phone number", "what is the name of the tenant"],
}


def _grams(text):
    t = " " + text + " "
    return Counter(t[i:i + 3] for i in range(len(t) - 2))


def _cos(a, b):
    num = sum(v * b.get(k, 0) for k, v in a.items())
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


_TRAINED = [(intent, normalize(ex), _grams(normalize(ex)), set(normalize(ex).split()))
            for intent, exs in EXAMPLES.items() for ex in exs]
_STOP = set("the a an is are of to for me my in on at this that what how do does please you i can show".split())


def classify(text, allowed=None, threshold=0.42):
    """-> (intent, score) or (None, best_score). `allowed` limits the intents for the current page."""
    t = normalize(text)
    g, words = _grams(t), set(t.split()) - _STOP
    best, score = None, 0.0
    for intent, _ex, eg, ew in _TRAINED:
        if allowed and intent not in allowed:
            continue
        ew2 = ew - _STOP
        overlap = len(words & ew2) / max(1, len(ew2 | words)) if (ew2 or words) else 0
        s = 0.7 * _cos(g, eg) + 0.3 * overlap
        if s > score:
            best, score = intent, s
    return (best, score) if score >= threshold else (None, score)
