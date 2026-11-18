"""pages.py: answers that depend on WHICH page and tab the person is on (2026-11-17).

The Branch Admin page had most of the brain; the Dormitory Viewer, Super Admin and Marketing pages each have their own
assistant code, so questions like "what is the purpose of this tab?" got a wrong-page answer there (the Viewer repeated
"How the numbers work", Super Admin described the Branch Admin tabs). Everything here is checked BEFORE the page's own
rules, and only for questions about the page itself, so the data answers are unchanged.

  first(q, page, tab, ctx)   -> reply or None
"""
import re

import agent

R = agent.reply

# ------------------------------------------------------------------------------------------ what each tab is for
VIEWER_TABS = {
    "vacancies": ("Vacancies",
                  "The Vacancies tab is the summary of this dormitory. At the top it counts the beds: total, vacant, occupied, reserved, "
                  "upcoming vacancies and overdue, with the occupancy and vacancy rate. Below that, every room has a card showing each "
                  "bed's colour and dates. Use the filters (gender, resident group, status) to narrow it down; every number follows them."),
    "hallway": ("Hallway layout",
                "The Hallway layout tab is the floor plan of this dormitory: every room in its real place, with a dot for each bed in its "
                "status colour. Click a room to open its card with the beds and their check-in and check-out dates, and click it again "
                "(or ×) to close it. It is read-only."),
    "analytics": ("Analytics",
                  "The Analytics tab shows this dormitory's numbers as charts: the bed status bar, upcoming vacancies (expected "
                  "check-outs), scheduled check-ins (reserved beds), vacant beds by room, beds by gender, beds by resident group, and the "
                  "next 30 days of occupied beds from the scheduled dates. Every number follows the filters at the top, and dates are "
                  "shown without any names."),
}
VIEWER_PAGE = ("This is the Dormitory Viewer: a read-only page for one dormitory. It shows which beds are vacant, occupied or reserved and "
               "when beds free up, but never who lives there. It has three tabs: Vacancies (counts and room cards), Hallway layout (the "
               "floor plan) and Analytics (charts). You can't reserve or change anything here; contact the dormitory for that.")

SUPER_TABS = {
    "overview": ("Overview",
                 "The Overview tab is your dashboard for all connected dormitories: each one's beds, occupancy and vacancy in one table, "
                 "plus a Needs attention list with open requests and branches whose numbers are out of date."),
    "dorms": ("Dormitories",
              "The Dormitories tab lists the dormitories connected to you and lets you connect a new one: ask its Branch Admin for a "
              "one-time pairing code (from their Central Link tab), enter it here, and they approve what they share with you."),
    "trading": ("Analytics",
                "The Analytics tab shows how many beds are empty in each dormitory over time, and what is expected next, so you can compare "
                "branches and spot changes."),
    "inbox": ("Inbox",
              "The Inbox has two parts. Permission requests: a Branch Admin needs your approval to pause viewer access, change the viewer "
              "password or remove its dorm server; their reason is shown, and once you accept, the change happens on their side by itself. "
              "Central inbox: decisions and alerts from your Branch Admins."),
    "accounts": ("Accounts",
                 "The Accounts tab lists the Branch Admin accounts connected to you and the viewers who joined your server, with an activity "
                 "log of connections, decisions, removals and blocks. The log can't be edited or deleted."),
    "server": ("Server Details",
               "The Server Details tab sets up your Super Admin server for viewers: the link, code and password you give them, the list of "
               "viewers who joined, and the blocked list. Passwords are stored only as a fingerprint, so if you forget one, set a new one."),
    "security": ("Security",
                 "The Security tab is about your own Super Admin account. You only see and manage the dormitories you connected yourself."),
}
SUPER_PAGE = ("This is the Super Admin page: it connects several dormitories and shows their shared numbers side by side. Tabs: Overview, "
              "Dormitories, Analytics, Inbox, Accounts, Server Details and Security. You see counts and statistics only, never tenant names.")

MARKET_PAGE = ("This is the Dormitory Directory (Marketing Viewer): a list of every dormitory that publishes its vacancies, with how many "
               "beds are free, also for male, female, students, reviewees and aircon. Search by name or city, filter the list, and click "
               "a dormitory to open its read-only viewer page. To reserve, contact the dormitory directly.")

PURPOSE = re.compile(
    r"\b(?:what(?:'s| is)?(?: the)? (?:purpose|point|use|function|job)(?: of)?|what (?:is|does|do) (?:this|the|our|my)(?: current)? (?:tab|page|screen|view|part|section)"
    r"(?: (?:for|do|show|mean|about|contain))?|what am i (?:looking at|seeing)|where am i|what tab is this|what page is this|which (?:tab|page) (?:is this|am i (?:in|on))|"
    r"explain (?:me )?(?:this|the|our|my)(?: current)? (?:tab|page|screen|view|part|section)|explain (?:me )?(?:this|that)(?: part)?$|"
    r"(?:tab|page|screen) (?:purpose|for what)|(?:in|on|about) (?:this|our|the|my) current (?:tab|page)|(?:this|our|the) current (?:tab|page)|"
    r"para saan (?:ang|ni|kini|ito)|unsa(?:y| ang)? (?:gamit|purpose))\b")


def _tab_from_text(t, tabs):
    for key, (label, _txt) in tabs.items():
        if re.search(r"\b%s\b" % re.escape(label.lower()), t) or re.search(r"\b%s\b" % re.escape(key), t):
            return key
    return None


def purpose(page, tab, t):
    if not PURPOSE.search(t):
        return None
    if page == "viewer":
        key = _tab_from_text(t, VIEWER_TABS) or (tab if tab in VIEWER_TABS else None)
        if re.search(r"\bpage\b", t) and not re.search(r"\b(tab|view|part|section)\b", t):
            return R("page_purpose", VIEWER_PAGE + ((" You are on the %s tab now." % VIEWER_TABS[key][0]) if key else ""))
        if key:
            return R("tab_purpose", VIEWER_TABS[key][1], suggestions=["What do the colours mean?", "How many beds are vacant?"])
        return R("page_purpose", VIEWER_PAGE)
    if page == "superadmin":
        key = _tab_from_text(t, SUPER_TABS) or (tab if tab in SUPER_TABS else None)
        if re.search(r"\bpage\b", t) and not re.search(r"\b(tab|view|part|section)\b", t):
            return R("page_purpose", SUPER_PAGE + ((" You are on the %s tab now." % SUPER_TABS[key][0]) if key else ""))
        if key:
            return R("tab_purpose", SUPER_TABS[key][1])
        return R("page_purpose", SUPER_PAGE)
    if page == "marketing":
        return R("page_purpose", MARKET_PAGE)
    # Branch Admin: the tab help that already exists for each tab
    import smart
    label = smart.TAB_LABELS.get(tab or "")
    if label and not (re.search(r"\bpage\b", t) and not re.search(r"\b(tab|view|part|section)\b", t)):
        text = smart.tab_help(tab)
        if text:
            return R("tab_purpose", "You are on the %s tab. %s" % (label, text))
    return None


# ------------------------------------------------------------------------------------------ small page facts
def page_facts(page, t, ctx):
    if page in ("viewer", "superadmin", "marketing") and re.search(r"\b(log ?out|sign ?out|logout|signout|exit the (app|page)|leave the page)\b", t):
        extra = " To go back to the directory instead, press Back to viewers at the top left." if page == "viewer" else ""
        return R("sign_out", "Press Sign out at the top right of the page. For safety you are also signed out when you close the tab.%s" % extra)
    if page == "viewer" and re.search(r"\b(dorm(itory)?|this|the|our|my) code\b|\bcode of (this|the) dorm", t):
        code = str((ctx or {}).get("code") or "").upper()
        return R("viewer_code", ("You are viewing the dormitory with code %s. The code and password come from its Branch Admin; I never see "
                                 "or show passwords." % code) if code else "Open a dormitory first by entering its code and password.")
    if page == "superadmin" and re.search(r"\b(approve|accept|reject|decline|deny)\b.*\b(request|requests|permission|change|password)\b|"
                                          r"\bhow (do|can) i (approve|accept|reject)\b", t):
        return R("super_approve", "Open the Inbox tab. Under Permission requests, each request from a Branch Admin shows what they want "
                                  "(pause viewer access, change the viewer password or remove their dorm server) and their reason. Press "
                                  "Accept or Reject. Once you accept, the change happens on their side by itself.", nav={"tab": "inbox"})
    if page == "marketing" and re.search(r"\b(reserve|book|rent|apply|inquire|enquire|contact)\b", t):
        return R("read_only", "You can't reserve from the directory: it only shows how many beds are free. Click a dormitory to open its "
                              "viewer page and check which beds are vacant, then contact that dormitory directly to reserve.",
                 suggestions=["Which dorm has the most vacant beds?", "Find dorms with vacant beds for females"])
    return None


def rewrite(q, page):
    """Wordings each page's own rules already answer well."""
    t = q
    if page == "superadmin":
        # "what is the occupancy rate" was refused as a one-dormitory question; across branches it is the comparison
        if re.match(r"^(?:what(?:'s| is)? |tell me |give me |show(?: me)? )?(?:the |our |my |current |overall |total )*(?:occupancy|vacancy)(?: rate| percentage| %)?\s*\??$", t):
            t = "compare the branches"
    return t


def first(q, page, tab, ctx):
    t = re.sub(r"\s+", " ", str(q or "").lower()).strip()
    t = re.sub(r"\bnow (tab|page|screen|view|part|section)\b", r"current \1", t)   # the translator turns "current" into "now"
    # "i mean in our current page" / "what i mean is …": the person is correcting the last answer; the rest is the question
    t = re.sub(r"^(?:no[, ]+)?(?:what )?i mean(?:t)?(?: is)?[, ]*", "", t).strip() or t
    return purpose(page, tab, t) or page_facts(page, t, ctx)
