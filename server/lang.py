"""Understands how people really type: misspellings, short forms, Cebuano (Bisaya), Tagalog and mixes
(Taglish / Bislish), and rewrites the question into the plain English the assistant's rules already know.

    to_english("pila pay bakante nga bed karun para sa babae?")  ->  "how many vacant bed now for female?"

Only words the assistant needs are changed. Words it does not recognise (for example people's names) are left
exactly as they were, so "check in Ana Reyes to room 201" keeps the name. No outside service is used.
"""
import re
import unicodedata
from difflib import get_close_matches

# ---------------------------------------------------------------------------------------------- phrases
# (pattern, replacement), applied in order on lower-case text. Longer phrases come first.
_P = [
    # "how many" first: "unsa ka daghan ang bakante" is NOT "who are you", and "ilang tenant" is "how many tenants", not "their"
    (r"\bunsa (?:ka|kaha ka)?\s?(?:ka)?daghan\b|\bpila (?:ka)?kadaghan\b|\bgaano (?:ka)?dami\b", "how many"),
    (r"\bilang\b(?= (?:tenants?|kama|beds?|kwarto|kuwarto|rooms?|tao|boarders?|lalaki|babae|bakante|students?|reviewees?|estudyante|ang|ka|na|pa|po|araw|days?|buwan)\b)", "how many"),
    (r"\bkilala (?:mo |nimo |nyo |niyo )?(?:ba )?(?:si |ni )?", "do you know "),
    (r"\b(?:kasama|kauban|kaubang|kasabay) (?:ni|si|sa)\b", "staying with"),
    (r"\b(?:nasa|naa sa|nandito sa|nandoon sa|andito sa)\b", "in"),
    (r"\b(?:kinsa|sino|sinu) (?:ka|ikaw|man ka|ka ba|ka ba talaga)\b|\bunsa (?:ka|man ka)\b(?! ?(?:ka)?daghan)|\bano ka\b", "who are you"),
    (r"\b(?:kumusta|kamusta|musta)\b", "hello"),
    # --- checking out / in, leaving, arriving
    (r"\b(?:mo|mag|magche|magcheck|mag-che|maga|nag|nagche|nag-che|mo-|mag-|nag-)[- ]?check[- ]?outs?\b", "check out"),
    (r"\b(?:mo|mag|magche|magcheck|mag-che|maga|nag|nagche|nag-che|mo-|mag-|nag-)[- ]?check[- ]?ins?\b", "check in"),
    (r"\bcheck-(ins?|outs?)\b", r"check \1"),
    (r"\bmag[- ]?out\b|\bmo[- ]?gawas\b|\bmogawas\b|\bmobiya\b|\bmo[- ]?biya\b|\baalis\b|\bmangalis\b|\blalayas\b", "check out"),
    (r"\bmo[- ]?abot\b|\bmoabot\b|\bdarating\b|\bmusulod\b|\bpapasok\b", "check in"),
    # --- contracts ending
    (r"\b(?:hapit|duol) na (?:ma)?(?:human|mahuman|tapos|matapos|expire)\b|\bmalapit (?:na|nang) (?:matapos|mag[- ]?expire|ma[- ]?expire)\b",
     "expiring soon"),
    (r"\b(?:ma|mag|mag-e|mage)[- ]?expire\b|\bmahuman\b|\bmatatapos\b|\bmatapos\b|\bmaexpire\b", "expire"),
    (r"\bkontrata?\b|\bkontrato\b", "contract"),
    # --- money
    (r"\b(?:wala|dili|di|hindi) pa (?:ka|naka|nakaka|nakapag|nag)?[- ]?(?:bayad|pay|paid)\b|\bwala (?:ka|naka)bayad\b|\bdi pa bayad\b|\butang\b|\bunpaid\b",
     "unpaid"),
    (r"\b(?:total|kabuuang|ang|tanan|lahat ng)(?: na| nga)? kita\b|\bkinita\b|\bginansya\b|\bincome\b", "revenue"),
    (r"\babang\b|\brenta\b|\bupa\b|\bbayad sa (?:kwarto|room|kuwarto)\b", "rent"),
    (r"\btagpila\b|\bmagkano\b|\bpila(?:y| ang)? (?:bayad|presyo|price)\b", "how much"),
    # --- question words
    (r"\bpila(?: na| pa| pay| ka| kaha| ra)*\b|\bilan(?: na| pa| po)*\b|\bgaano karami\b", "how many"),
    (r"\bilang\b|\bilaha\b|\bnila\b|\bila\b", "their"),
    (r"\bkinsa(?: ang| si| ni| sila)?\b|\bsino(?:-sino)?(?: ang| yung| ba| si| po)?\b|\bsinu\b|\bsno\b", "who"),
    (r"\basa(?: na| ang| nga)?(?= (?:room|rooms|kwarto|branch|branches|dorm|dorms|bed|beds|location)\b)|\b(?:asa|asang) nga\b|\baling\b|\balin(?:g)?\b|\bunsang\b|\bunsa nga\b|\bunsa(?:ng)? klase(?:ng)?\b", "which"),
    (r"\bkanus-?a\b|\bkailan\b|\bkelan\b", "when"),
    (r"\bngano(?:ng)?\b|\bbakit\b|\bbkt\b", "why"),
    (r"\bunsaon\b|\b(?:pa)?paano\b|\bpano\b", "how"),
    (r"\bunsay\b|\bunsa(?: man)?\b|\bano(?:ng)?\b|\banu\b", "what"),
    (r"\basa(?: dapit)?\b|\bsaan\b", "where"),
    # "naa pay / naa pa ba / wala pay": Cebuano "is there still" ("pay" here is "pa + y", never a payment)
    (r"\bnaa pa(?:y| ba(?:y)?)?\b(?= (?:\w+ )?(?:available|bakante|vacant|reservation|kwarto|room|rooms|bed|beds|kama|space|slot))", "is there"),
    (r"\b(?:(?:can|could|pwede|puede)(?: (?:i|we|you|ba|pa|ko|ta))*(?: still)? )?(?:mo-?)?(?:accommodate|take in|accept|fit|squeeze in|tanggap\w*|dawat\w*)\s+(?:(?:ug|og|ng|nang) )?(?:another|one more|a new|new|an additional|additional|more|isa pa(?:ng)?|usa pa ka)\s+"
     r"(?:tenants?|persons?|people|boarders?|residents?|guests?|students?|reviewees?)\b", "is there vacant bed"),
    (r"\bnaa ba(?:y)?\b|\bnaay\b|\bnaa\b(?= (?:\w+ )?(?:available|bakante|vacant|reservation|upcoming|pending|kwarto|room|bed|kama))|"
     r"\bmayroon(?: bang| ba)?\b|\bmeron(?: bang| ba)?\b|^may\b(?! (?:i|we|you)\b)|\bmay(?= (?:\w+ )?(?:bakante|available|vacant|reservation|upcoming|pending|admin|branch|room|kwarto|kama|bed|suspicious)\b)",
     "is there"),
    (r"\bpwede(?: ba| ko| ba ko| ako)?\b|\bpuede(?: ba)?\b|\bmakaya ba\b", "can i"),
    # --- places and things
    (r"\bkwart[oa]ng?\b|\bkuwart[oa]ng?\b|\bkwarto\b|\bsilid\b", "room"),
    (r"\bkatre\b|\bhigdaanan\b|\bkama\b", "bed"),
    (r"\bbakante(?:ng| nga)?\b|\bbakanti(?:ng)?\b|\bbakant\b|\bvakante\b|\bbakate\b|\bbakanteng\b", "vacant"),
    (r"\bokupado\b|\b(?:may|naay) (?:na)?(?:katira|nakatira|nagpuyo|puyo)\b", "occupied"),
    (r"\bpuno(?: na)?\b(?! sa)", "full"),
    (r"\b(?:lalaki|lalake|laki|lalakihan|lalaking|lalakeng)\b", "male"),
    (r"\b(?:babae|babaye|babaeng|bayi|babayi|kababaihan)\b", "female"),
    (r"\b(?:estudyante|istudyante|studyante|estudyanteng)\b", "student"),
    (r"\bandana\b|\bpalapag\b|\bsalog\b", "floor"),
    (r"\b(?:ika-?duhang|ikaduha|ika-?lawang|ikalawa|segundo)\b", "second"),
    (r"\b(?:ika-?tulong|ikatulo|ika-?tlong|ikatlo|ikatlong)\b", "third"),
    (r"\b(?:una nga|unang|ika-?unang|first)\b", "first"),
    (r"\bnangungupahan\b|\btig-?abang\b|\bnagpuyo\b|\bnakatira\b|\bboarders?\b", "tenants"),
    (r"\bbedspacers?\b", "bedspace tenants"),
    (r"\bsa (?:among |amo |aming |atong |ating |inyong )?(?:branch|dorm|dormitoryo)\b(?=\s*[?.!]*\s*$)", "in my dorm"),   # "… sa branch." = here
    (r"\bsangay\b", "branch"), (r"\b(?:pangalan|ngalan|pangan)\b", "name"),
    (r"\bpara(?: sa)?\b", "for"), (r"\bpaki-?\b|\bpakisuyo\b|\bpalihug\b|\bpalihog\b", "please"),
    (r"\bsunod(?: nga)?\b|\bsusunod(?: na)?\b", "next"), (r"\bproblema\b|\bproblem(?:s)?\b|\bguba\b|\bsira\b", "problem"),
    (r"\bnaa\b", "in"), (r"\b(?:pud|pod|din|rin)\b", "also"), (r"\bkung\b", "if"), (r"\bkag\b|\bug\b(?= [a-z]+ (?:and|ug))", "and"),
    (r"\bmga tawo\b|\btawo\b|\btao\b", "people"),
    # --- time
    (r"\bkarong adlawa\b|\bkaron(?:g)? adlaw\b|\bngayong araw\b|\bngayon araw\b|\bngayong araw na ito\b|\bsa adlaw karon\b", "today"),
    (r"\b(?:sunod|sunod nga|susunod na|sa susunod na) (?:semana|semanaha|linggo)\b|\bnxt week\b", "next week"),
    (r"\b(?:sunod|sunod nga|susunod na|sa susunod na) (?:bulan|buwan|bulana)\b|\bnxt month\b", "next month"),
    (r"\b(?:karong|karon nga|ngayong|ngayon na) (?:bulana|bulan|buwan|buwana)\b", "this month"),
    (r"\b(?:karong|karon nga|ngayong) (?:semanaha|semana|linggo)\b", "this week"),
    (r"\b(?:niaging|miaging|nakaraang|nakaraan na|last na) (?:bulan|buwan)\b", "last month"),
    (r"\b(?:niaging|miaging|nakaraang) (?:semana|linggo)\b", "last week"),
    (r"\bugma\b|\bbukas\b|\btom+or+o?w\b|\btmrw?\b|\btmw\b|\b2mo?r+o?w\b|\btommorow\b|\btomorow\b|\btomorrrow\b", "tomorrow"),
    (r"\bkaron\b|\bkarun\b|\bkaraon\b|\bngayon\b|\bngaun\b|\bngayun\b|\bright now\b|\bat the moment\b|\bcurrently\b|\bcurrent\b", "now"),
    (r"\bkagahapon\b|\bkahapon\b", "yesterday"),
    (r"\bsemana\b|\blinggo\b", "week"),
    (r"\bbulan\b|\bbuwan\b", "month"),
    (r"\btuig\b|\btaon\b", "year"),
    (r"\bweekend\b|\bsabado ug domingo\b|\bsabado at linggo\b", "this weekend"),
    # --- amounts / ranking
    (r"\bpinaka-?\s?(?:daghan|marami|maraming|madami|madaming)\b|\bpinakamaraming?\b|\bpinakadaghan\b|\bpinakamadami\b", "most"),
    (r"\bpinaka-?\s?(?:gamay|kaunti|konti|mababa|ubos|low)\b|\bpinakagamay\b|\bpinakamababa(?:ng)?\b|\bpinakaubos\b", "lowest"),
    (r"\bpinaka-?\s?(?:taas|mataas|high)\b|\bpinakamataas(?:ng| na)?\b|\bpinakataas\b", "highest"),
    (r"\bpinaka-?\s?(?:maayo|maganda|magandang)\b|\bpinakamaganda(?:ng)?\b|\bpinakamaayo\b", "best"),
    (r"\bdaghan(?: kaayo)?\b|\bmarami(?:ng)?\b|\bmadami(?:ng)?\b", "many"),
    (r"\bgamay\b|\bkaunti\b|\bkonti\b|\bmababa(?:ng)?\b|\bhinay\b|\bniubos\b|\bbumaba\b|\bmigamay\b", "low"),
    (r"\btanan(?:g)?\b|\blahat(?: ng)?\b|\btanang\b", "all"),
    (r"\b(?:isa|usa)\b", "one"), (r"\b(?:duha|dalawa)\b", "two"), (r"\b(?:tulo|tatlo)\b", "three"),
    (r"\b(?:upat|apat)\b", "four"), (r"\blima\b", "five"), (r"\b(?:unom|anim)\b", "six"),
    # --- verbs / requests
    (r"\b(?:i-?pakita|ipakita|pakita|ipakita mo|pakit-?a|paki-?show|show mo|i-?show|pakita daw)\b", "show"),
    (r"\b(?:i-?check|icheck|paki-?check|check mo|check daw|tan-?awa|tingnan|tignan|silipin)\b", "check"),
    (r"\b(?:i-?list|ilista|list mo|i-?lista)\b", "list"),
    (r"\b(?:i-?compare|compare mo|ikumpara|ikompara|kumpara)\b", "compare"),
    (r"\b(?:i-?update|update mo|usba|baguhin|ilisan|i-?usab)\b", "update"),
    (r"\b(?:i-?summarize|paki-?summarize|summarize mo|i-?summary)\b", "summarize"),
    (r"\b(?:i-?predict|predict mo|tagna|hulaan)\b", "predict"),
    (r"\b(?:i-?generate|generate mo|himoa|gumawa ng)\b", "generate"),
    (r"\b(?:i-?reserve|magpa-?reserve|nagpa-?reserve|nag-?reserve|pareserve|i-?book|magpa-?book|reserba)\b", "reserve"),
    (r"\b(?:i-?analyze|analyze mo|analisa(?:hon)?)\b", "analyze"),
    (r"\b(?:i-?prioritize|tutukan|unahon|unahin)\b", "prioritize"),
    (r"\bkinahanglan\b|\bkailangan(?:g)?\b|\bnid\b|\bneed(?:s|ed)?\b", "need"),
    (r"\bmo-?follow up\b|\bi-?follow up\b|\bfollow-?up\b", "follow up"),
    (r"\bnag-?request\b|\bnirequest\b", "requested"),
    (r"\b(?:hindi|wala|dili) pa (?:nag|naka|na)[- ]?(?:a-?)?update\b", "not updated"), (r"\bnag-?change\b|\bnag-?usab\b|\bnagbago\b", "changed"),
    (r"\bpermiso\b|\bpahintulot\b", "permission"), (r"\b(?:pag|mag|nag)-?manage\b", "manage"),
    (r"\bnag-?update\b|\bnaka-?update\b|\bna-?update\b", "updated"),
    (r"\bnag-?submit\b", "submitted"),
    # --- my / our / particles
    (r"\b(?:akong|akoa|nako|nko|ko|q|ku)\b(?= *[?.!]?$)", "mine"),
    (r"\b(?:akong|akoang|aking|nako|nko)\b", "my"), (r"\b(?:imong|imo|iyong|inyong|nimo)\b", "your"),
    (r"\b(?:nato|natin|namo|namin|ato|atong|amo|among)\b", "our"),
]
_PHRASES = [(re.compile(p), r) for p, r in _P]

# particles that only carry tone; removed after the phrases above have used them
_FILLER = set("""ba bay bang daw raw nga ang ng mga yung yong lang lng man ra kaayo kay sila siya po ho naman nman
mo nimo ninyo niyo kita ta si ni sa na pa ug og o tapos then ah eh oh uy uyy hay kuan bitaw jud gyud talaga""".split())
_KEEP_SHORT = {"ok", "yes", "no", "hi", "id", "ac", "pm", "am", "vs", "in", "on", "to", "at", "of", "is", "it", "me", "my", "we", "up", "an", "a", "i"}

# ---------------------------------------------------------------------------------------------- spelling
SHORT = {"revwee": "reviewee", "reviwee": "reviewee", "reviewe": "reviewee", "revewee": "reviewee", "riviewee": "reviewee", "reviwer": "reviewee",
         "revwees": "reviewees", "studnt": "student", "studen": "student", "stdent": "student", "femal": "female", "femle": "female", "fmale": "female",
         "capcity": "capacity", "capasity": "capacity", "kapasidad": "capacity", "romm": "room", "rom": "room", "roon": "room",
         "createor": "creator", "creater": "creator", "websit": "website", "fnd": "find", "fin": "find", "serch": "search", "seach": "search",
         "scrool": "scroll", "scrol": "scroll", "skrol": "scroll", "slied": "slide", "slid": "slide", "presnt": "present", "prsent": "present",
         "akready": "already", "alredy": "already", "hisotry": "history", "chekcout": "checkout", "checkot": "checkout", "hallwy": "hallway",
         "limitaion": "limitation", "limitaions": "limitations", "limitasion": "limitation", "limitasyon": "limitation", "limtation": "limitation",
         "limitions": "limitations", "limition": "limitation", "limit": "limitation", "limits": "limitations",
         "vecan": "vacant", "vecant": "vacant", "vecants": "vacant", "vacan": "vacant", "vecancy": "vacancy", "vacent": "vacant", "vakant": "vacant",
         "concider": "consider", "concidered": "considered", "consider": "considered", "considerd": "considered", "conside": "considered",
         "occcupied": "occupied", "ocupied": "occupied", "occupid": "occupied", "ocuppied": "occupied", "okupado": "occupied",
         "reserve": "reserve", "reseve": "reserve", "resrve": "reserve", "reserb": "reserve", "temporry": "temporary", "temporay": "temporary",
         "temprary": "temporary", "tempoary": "temporary", "overdu": "overdue", "overdo": "overdue", "ovedue": "overdue",
         "defination": "definition", "definasyon": "definition", "meanig": "meaning", "recoerd": "record", "recrod": "record", "rekord": "record",
         "chekc": "check", "chek": "check", "tenatn": "tenant", "tenat": "tenant", "histroy": "history", "histori": "history",
         "pls": "please", "plz": "please", "pls.": "please", "u": "you", "ur": "your", "r": "are", "wat": "what", "wht": "what",
         "hw": "how", "hm": "how many", "rm": "room", "rms": "rooms", "bd": "bed", "bds": "beds", "thx": "thanks", "tnx": "thanks",
         "abt": "about", "nxt": "next", "wk": "week", "wks": "weeks", "mos": "months", "yr": "year", "ppl": "people",
         "avail": "available", "avl": "available", "avlbl": "available", "vac": "vacant", "occ": "occupied", "res": "reservation",
         "2day": "today", "tdy": "today", "tday": "today", "tmr": "tomorrow", "b4": "before", "info": "information", "w/": "with",
         "im": "i am", "dont": "do not", "cant": "cannot", "whats": "what is", "wheres": "where is", "hows": "how is",
         "gimme": "give me", "shw": "show", "sho": "show", "lst": "list", "lemme": "let me", "wanna": "want to", "gonna": "going to", "nd": "and", "n": "and",
         "sem": "semester", "approx": "about", "dorms": "dorms", "dormitory": "dorm", "dormitories": "dorms", "pct": "percent",
         "vecant": "vacant", "vacnt": "vacant", "vacent": "vacant", "vaccant": "vacant", "vaacant": "vacant", "vacan": "vacant",
         "vecancy": "vacancy", "vacncy": "vacancy", "vancancy": "vacancy", "vacany": "vacancy", "vacansy": "vacancy",
         "avalable": "available", "availabe": "available", "availble": "available", "avaliable": "available", "avilable": "available",
         "ocupied": "occupied", "occupide": "occupied", "ocupancy": "occupancy", "occupacy": "occupancy", "ocuppancy": "occupancy",
         "reservaton": "reservation", "resevation": "reservation", "reservasyon": "reservation", "femal": "female", "femail": "female",
         "femle": "female", "mle": "male", "studnt": "student", "studnts": "students", "studyante": "student", "tenat": "tenant",
         "tennant": "tenant", "tenents": "tenants", "tennants": "tenants", "contrat": "contract", "contarct": "contract",
         "branchs": "branches", "brach": "branch", "bransh": "branch", "mantenance": "maintenance", "maintainance": "maintenance",
         "revenu": "revenue", "reveneu": "revenue", "tomrrow": "tomorrow", "tomoro": "tomorrow", "chekout": "checkout",
         "checkot": "checkout", "chek": "check", "chck": "check", "rooom": "room", "roon": "room", "fl": "floor", "flr": "floor",
         "2nd": "second", "3rd": "third", "1st": "first", "4th": "fourth", "girs": "girls", "boyz": "boys", "gurls": "girls", "grls": "girls", "grl": "girl", "gurl": "girl", "bys": "boys",
         "fem": "female", "stud": "student", "studs": "students", "rev": "reviewee", "revs": "reviewees", "mgmt": "management"}
VOCAB = sorted(set("""vacant vacancy vacancies available availability occupied occupancy occupant tenant tenants resident
residents reservation reservations reserved reserve booking bookings checkout checkin contract contracts expire expiring
expired tomorrow today yesterday week month months year next last female male mixed student students reviewee reviewees
bedspace bedspacer room rooms bed beds floor second third first ground branch branches dorm dorms report summary compare
comparison hallway analytics revenue income payment payments unpaid balance rent maintenance repair cleaning inspection
capacity schedule upcoming overdue emergency contact number phone history transfer register registered profile profiles
missing duplicate overlap overlapping available forecast predict prediction trend trends increase decrease decreasing
increasing highest lowest most least percent percentage rate performance marketing promotion promote strategy customers
recommend recommendation improve improvement attention priority prioritize pending request requests permission admin
admins super viewer viewers directory approve approved suspicious activity update updated records record inconsistent
verification verify semester calendar matrix canvas temporary guest guests whole entire everything everyone""".split()))
_ENGLISH = set("""the a an and or but if then than that this these those there their they them what which who whom whose
when where why how is are was were be been being have has had do does did can could would should will shall may might
must not no yes all any some each every many much more less few one two three four five six seven eight nine ten for of
in on at to from by with about into over under after before between during within without until till since per via
my our your his her its me us you i we he she it show list give tell find check open go make create add delete remove
change edit move set get see look need want like please thanks thank hello hi hey okay ok sure maybe just only also still
even again now soon later early late good bad best worst big small high low full empty free left right new old other
same different most least first last next week month year day days time date dates people person name names
recent recently almost already changes changed change unavailable unoccupied consistently consistent currently rates rate
scheduled schedule registered pending expired active assigned overall average total within before after during average
cause become becomes caused happens happen should would tenants rooms beds charges cheaper higher lower likely""".split())


def _fix_word(w):
    if w in SHORT:
        return SHORT[w]
    if len(w) < 5 or not w.isalpha() or w in VOCAB or w in _ENGLISH:
        return w
    hit = get_close_matches(w, VOCAB, n=1, cutoff=0.8)
    # only obvious typos: same first letter and about the same length ("vecant" -> "vacant", never "recent" -> "rent")
    if hit and hit[0][0] == w[0] and abs(len(hit[0]) - len(w)) <= 1:
        return hit[0]
    return w


def to_english(text):
    """-> the question in simple English (lower case). Names and unknown words are kept."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[“”\"’`]", "", t).replace("'", "")
    t = re.sub(r"([?!.,;:])", r" \1 ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # spelling and short forms first (so "bakanteng" and "vecant" both become "vacant" below)
    t = " ".join(_fix_word(w) for w in t.split())
    for pat, rep in _PHRASES:
        t = pat.sub(rep, t)
    words = [w for w in t.split() if w not in _FILLER or w in _KEEP_SHORT]
    t = " ".join(words)
    t = re.sub(r"\s+([?!.,;:])", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def looks_local(text):
    """True when the sentence uses Cebuano / Tagalog words (used to keep the original for names)."""
    return to_english(text) != re.sub(r"\s+", " ", str(text or "").lower()).strip()
