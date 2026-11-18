# Setup Guide — Vacancy Tracker

## Try it on one computer first (local test mode)

No Firebase, no PostgreSQL, no hosting: data goes into a SQLite file and the login is a temporary
username + password kept on this computer.

1. Double-click `START-LOCAL.bat` (or run `python run_local.py`). The browser opens the **front page**.
2. On the front page, **Get started** creates an account (a short survey first: how you heard about us and what
   is hard for you, then a "problems solved" screen, then email + password). **Sign in** opens the log-in panel:
   choose your role (its explanation opens under it), then press **Log in**. Both open over the front page,
   80% wide, with the page blurred behind. Sample accounts:
   `sample.one@example.com` / `Sample1234` (has rooms and tenants) and `sample.two@example.com` / `Sample5678`.
   **Create an account** with any email; a username `name@vecancy.tracker` is made for you, but you
   keep signing in with the email. With EASY LOGIN on (the default in local mode) any password works.
3. The account you used is remembered on this computer, so next time you only choose the role and press Log in.
   "Or choose another account" lets you switch. It never opens a page by itself.
4. Your data and accounts are in `local-data/vacancy.db`. They are kept between restarts; delete the
   `local-data` folder only if you want to start over.

## Front page and the one sign-in

- `index.html` is the front page: an interactive 3D dorm in the hero (drag to turn it, tap a window), a live demo,
  the features (with the dorm photo and a tidy hallway map), and Sign in / Get started.
  Both buttons open `login.html` inside a large panel. `login.html` is the **only sign-in**; opened on its own
  (when an app page sends a signed-out visitor) it shows the same panel over a blurred picture of the front page.
- The Get started survey answers are saved with the new account in the `signup_survey` table (local mode).
  The Branch Admin app is `admin.html`.
- `admin.html`, `viewer.html`, `superadmin.html` and `marketing.html` have **no sign-in screen**. If you
  are signed out they send you to `login.html?next=<page>`, and after you sign in you go straight back.
- You can open any of the four pages directly (bookmark, new tab): the session from the front page is
  shared by every page and tab until you sign out (12 hours at most). Signing out on any page signs out
  everywhere. The browser keeps only the signed session token, never the password.
- In local mode the sign-in page signs in with `POST /api/local/login` using the **email**; it does not use
  Firebase. (On a hosted server without local mode, the dialog shows the existing Vecancy sign-in panel.)
- The dorm code + password on the Viewer page and the server code on Marketing are still required: they
  are permissions checked by the server, not a second login.
- Each page opens with a short cinematic intro (`entrance.js` / `entrance.css`). Click or press Esc to
  skip; it becomes a quick fade on devices set to reduce motion.

Differences from the real system: creating an account does not verify a Google account or email, and a
forgotten password cannot be emailed (Update account needs the current password). Local mode only
listens on 127.0.0.1 and must not be put on the internet. The assistant uses scikit-learn if it can
load, otherwise `brain_lite.py`, a built-in matcher over the same `intents.json`.
The same tests run on SQLite and PostgreSQL: `python -m pytest server/tests`.

## Architecture

- **SQL (PostgreSQL)** stores ALL application data: rooms, beds, tenants,
  contracts, viewer/central access, Super Admin data, and the AI assistant's
  conversations, messages, insights and config.
- **Firebase Authentication** holds ONLY the generated login
  (`yourname@vecancy.tracker` + password). No application data is in Firebase.
- **`server/`** (Python/Flask) serves the pages and the JSON API. It verifies
  the Firebase ID token on every request, takes the user id only from that
  token, and enforces the same authorization the old `firestore.rules` did.
  Database credentials never reach the browser.
- One sign-in page (`login.html` + `login.js`), opened from the front page. `auth-ui.js` shares that session with
  `admin.html`, `viewer.html`, `superadmin.html` and `marketing.html`, and sends signed-out visitors to
  the front page.

## Accounts

- **Create Account:** prove your Google account or email (Google popup or an
  emailed sign-in link), pick a name, and set a password. The system creates
  the unique username `name@vecancy.tracker`. A taken name is refused with
  "This name was taken."
- **Sign in:** generated username + password only. Your Google password is
  never requested or stored.
- **Update Account:** verify the original Google/email, see your username
  (it never changes), and set a new password.
- The original email is kept only in the SQL `accounts` table and is never
  shown to other users.

## Setup

1. **Firebase (Authentication only).** In the Firebase Console enable
   **Email/Password**, **Email link (passwordless)** and **Google** under
   Authentication → Sign-in method. Add your hosting domain under
   Authentication → Settings → Authorized domains. Put the web config in
   `firebase-config.js`. You do not need Firestore, Functions or Hosting, so
   there is nothing to pay for.
2. **Database.** Create a free hosted PostgreSQL database (Neon, Supabase,
   etc.) and apply the schema:
   `psql "$DATABASE_URL" -f server/schema.sql`
3. **Server environment variables** (set on the server, never in the browser):
   - `DATABASE_URL`: the PostgreSQL connection string.
   - `FIREBASE_SERVICE_ACCOUNT_JSON`: the Firebase service-account JSON
     (Project settings → Service accounts → Generate new private key).
4. **Install and run:**
   `pip install -r requirements.txt` then
   `python server/app.py` (or, on a host: `gunicorn --chdir server "app:create_app()" --bind 0.0.0.0:$PORT`).
   Open the printed address; serve over HTTPS in production.
5. **Migrating existing Firestore data** (do this before anyone relies on the
   new system; nothing is deleted from Firebase):
   `python server/migrate_firestore.py export backup.json` then
   `python server/migrate_firestore.py import backup.json`.
   Import is all-or-nothing and re-reads every record to confirm it matches.
   Existing users keep their data: when they create their new account the
   same internal user id is reused. Keep the old Firestore data until you have
   checked the result. The old rules and function are kept in `legacy/`.

## Tenant Information and emergency cards

The **Tenant Information** tab keeps each tenant's photo, contact number, home address and two
emergency contacts, organized in room folders. Clicking a tenant's name on **Room Canvas**, or a room
and then a tenant on **Hallway Layout** (while the layout is locked), opens the Tenant Emergency Card
beside the page; clicking the same tenant again hides it.

- One record per tenant (`tenants` table). The bed points to it (`tenantId`), so the information
  follows the tenant when they move rooms. A new tenant in that bed never sees the previous tenant's
  information. Checked-out tenants keep their record under "Not in a room".
- Photos are stored in the database (`tenant_photos` table) and are only sent to the signed-in admin
  who owns them. Only JPEG, PNG or WebP up to 1.5 MB are accepted; the browser shrinks photos first.
- Contact and emergency numbers must be Philippine mobile numbers: `09XXXXXXXXX` or `+639XXXXXXXXX`
  (spaces and hyphens allowed, e.g. `0917-123-4567`, `+63 917 123 4567`). Only the name is required.
- Optional **supporting documents** per tenant (PDF, Word .docx, JPEG, PNG, WebP; up to 5 MB each, 10 per
  tenant) are stored in the `tenant_files` table, owner-only, and can be viewed, replaced or removed.
- **Existing PostgreSQL databases:** run `server/schema.sql` once more to add the new tables
  (it only creates what is missing; nothing is changed or deleted). The local test mode does this
  automatically.

## Built-in Python tracker assistant (no AI API key)

**What it can do now.** It knows which tab you are on and which room you last clicked (shown as
"Looking at: …" above the suggestion buttons). It answers from your own records: who is in a room,
where a tenant is, who leaves this week or month, vacant beds for a gender or resident group,
reservations, temporary guests and a summary. It can also prepare changes: check in, check out,
extend, move a tenant, add/edit/delete a room, add or cancel a reserve client, add or check out a
temporary guest, add a hallway facility. For every change it first says "Here's what I understood:
…", then shows Confirm / Cancel. Nothing is written until you press Confirm, and the change goes
through the same screens and checks as doing it by hand. If something is missing (for example the
checkout date) it asks, and you can answer in the next message or say "cancel".

**Languages and typing mistakes.** Questions can be typed in English, Cebuano (Bisaya), Tagalog or a mix
(Taglish / Bislish), with misspellings and short forms: "pila pay bakante karun?", "may bakanteng kama ba para sa
babae?", "vacnt bedspce for grls". `server/lang.py` turns them into simple English first; names are never changed.

**Several filters at once.** "Is there a vacant bed for a female student bedspacer?" combines gender, student /
reviewee, bedspace / whole room, floor, aircon, group size ("room for 3 girls") and dates ("from Dec 1 for 3 months").

**Who sees what.** Tenant names, contact numbers, emergency contacts and addresses are answered only on the
Branch Admin page, from that admin's own records. The Dormitory Viewer, Marketing Directory and Super Admin
assistants never show them (their data has no names) and say so when asked.

**Honest answers.** Rent, payments, revenue, maintenance, cleaning and inspections are not recorded in the app, so the
assistant says that instead of guessing. Forecasts use only the dates already saved (check-outs and reservations).

**Follow-up questions** work inside the same chat: "Show me all vacant rooms" → "Which of those are for females?" →
"What about students?". A new chat starts fresh. "Give me a summary of everything we discussed" recaps the chat.

The extra answers live in `server/answers.py`; `server/tests/test_language.py` checks the rules above.


The assistant uses a small, deterministic Python rule engine, not a Gemini,
OpenAI, or other language-model API. There is no model API key, model token
charge, or model call. It recognizes a practical set of tracker questions,
explains actual screens/workflows, reports facts from the signed-in user's
current SQL records, and refuses questions outside this application.
It is intentionally limited: it does not understand arbitrary requests like a
large language model and may ask for a room number or other detail when a
request is ambiguous.

The assistant runs inside the Python server (`/api/assistant`, code in
`server/ai.py`). It verifies the sign-in token, reads only the signed-in
user's SQL records, and never writes data. Conversations, messages, insights
and config are stored in the SQL tables `ai_conversations`, `ai_messages`,
`ai_insights` and `ai_config`, tied to the user's internal user id. For a
change, the browser shows a preview and requires confirmation before passing
the request to the tracker's existing validated workflow. It is rate-limited,
never accepts a model-generated database query, and no resident notes leave
the server. There is no AI provider key anywhere. Nothing extra to deploy:
it starts with `python server/app.py`.

### Assistant: navigation, reports and memory (Branch Admin and Super Admin pages)

The assistant button now appears on the **Branch Admin page and the Super Admin page** after you
sign in. It never appears on the front page. The panel can be
made larger with ⤢, and it continues the same conversation when you move between the two pages.

| Say | What happens |
|---|---|
| "Take me to the server" | Opens Viewer Access (Branch Admin) or Server Details (Super Admin) |
| "Open the Room Canvas", "Navigate to Room 205" | Opens the tab / shows that room (only rooms in your own dormitory) |
| "Open the Super Admin analytics" | Opens the Super Admin Analytics tab — only if your account is a Super Admin |
| "Report the vacancy", "…in a table", "…in bullet points" | Report built from your live rooms: per-room table, findings, suggestions |
| "Compare this month with last month" | Vacant beds, rate, check-ins and check-outs side by side |
| "Why did vacancy increase?", "Report the last 14 days" | Splits **confirmed** causes (recorded check-outs, check-ins, reasons) from **possible** ones (not proven by the records) |
| "Which dorm has the highest vacancy?" (Super Admin) | From the latest snapshots of dormitories that approved analytics for you |
| "Update the contact number of Ana Cruz to 0917 123 4567" | Checks the PH number, asks you to confirm, saves, then re-reads the record and tells you the saved result |
| "Remember that I prefer table format for reports" | Saved to **your account only**; reports use it automatically |
| "What do you remember?", "Forget my memory", "Clear my chat history" | View / clear memory (also the **Memory** button) |

Memory is stored in the table `ai_memory` and report tables in `ai_message_extras`, both keyed by
the signed-in account on the server (another account can never read them). Passwords, PINs and
similar secrets are refused and never stored. History older than a Tenant History record's expiry
cannot be reconstructed, and comparisons assume the bed list did not change; the reply says so.

### Super Admin Analytics: candles, direction colours, forecast and risk

* **Candles (OHLC):** pick 🕯️ Candles and an interval (Daily / Weekly / Monthly / Yearly). Each candle
  uses only the snapshots recorded inside that interval: Open = first, Close = last, High / Low =
  highest / lowest. Green body = closed higher than it opened, red = lower, a thin line = unchanged.
* **Line colours:** each step of the recorded line is green when vacancy went up, red when it went
  down, grey when unchanged. Gaps in the records are left empty, never filled in.
* **Forecast (purple, right of NOW):** dashed = confirmed schedule (contract end dates and reserved
  check-ins already in the records); dotted with a shaded range = trend estimate (straight-line fit
  of up to 60 days of daily closing values, 95% range). With fewer than 14 days of history no trend
  is drawn and the note says "Limited reliability". Moving the chart never changes recorded data.
* **Risk:** Red = High, Yellow = Moderate, Green = Safe, shown per dormitory with the reason. Default
  rules: High if vacancy ≥ 30% or it rose ≥ 10 points in 7 days; Moderate if ≥ 15%, rose ≥ 3 points,
  or ≥ 10% of beds check out within 7 days. Change them with **Thresholds** (saved in this browser).
  On the "Vacancy rate" metric the same bands are shaded behind the chart.

**Existing PostgreSQL database:** run `psql "$DATABASE_URL" -f server/schema.sql` once more to add
`ai_memory` and `ai_message_extras` (safe: it only creates what is missing). Local test mode does this
by itself.

### Assistant: commands, room reports and definitions (server/expert.py)

- **Reserved and temporary beds count as occupied.** The Room Canvas shows a reserved bed as "Occupied · Reserved", and the
  Occupied number includes reserved and temporary beds. The assistant answers the same way.
- **"cancel" always works.** "cancel", "stop", "never mind" end a half-finished request. If the assistant cannot use two answers
  in a row, it stops the request by itself instead of asking forever.
- **Definitions and limits.** "is a reserved bed considered occupied?", "what does overdue mean?", "what are your limitations?".
- **One room.** "how many vacant / overdue / reserved / temporary in S-105" (the word "room" is not needed).
- **Branch Admin only: people.** "is Terrins present?", "find Terrins in the history", "contact details of Ana Reyes".
  The Dormitory Viewer, Marketing Viewer and Super Admin pages never look up a person.
- **Branch Admin only: commands (always shown first, saved only after Confirm).**
  "add Terrins as a reserve, male student, check in today, check out 2027, choose the best room" (it also names the next best room);
  "add Terrins as a temporary client, male, today until Friday"; "check out Juan Cruz with a bad record because he did not pay";
  "add a reason to my data transfer because I want to resign" (fills the reason box only; you press Generate).
- **Screen commands.** "show me only the vacant beds", "show only female rooms", "clear the filters" set the page's own filters and
  report what is shown. On the Super Admin page "find Sanciangko dorm" types the name in the new Dormitories search box and reports it.

### Assistant: any wording (round 2)

- "who are you", "who created this website", "my name is Joy" / "what is my name" are answered directly.
- Add a room in any order: "add room name Terin 123 4 capacity for female reviewee", or "add room" → "for female student capacity of 5" → "T567".
- A half-finished request belongs to its chat; a new chat never continues it.
- People (Branch Admin only), any word order and with typos: "can you find Terrins Hortelano in the room canvas?",
  "is Hortelano Terrins present or already checked out?", "what is the record of Terrins? if bad say the reason".
- Screen: "scroll down a little", "go to the top", "slide right the checkout date" (moves the Checkout Schedule months),
  "show me the vacant beds in the hallway" (opens the tab that was named).

### Assistant: conversation, the developer, and page commands (round 3)

- **Greeting:** "hi", "good morning", "maayong buntag", "kumusta" get a friendly greeting that follows the time of day, uses your name
  if you gave it, and asks your name if you didn't.
- **Who are you:** a full introduction (who made it, what it can do on this page, languages, privacy, the Confirm rule).
- **The developer:** "who is Terrins Hortelano", "do you know your developer", "why was this website made" are answered.
  If you say "I am Terrins Hortelano" it greets you as its developer. This is only a greeting: it gives no extra access.
- **Small talk:** thank you, how are you, bye, are you there, how do I use you, and similar.
- **Page commands:** "switch to dark mode / light mode", "start the tutorial", "mute your voice / turn on your voice",
  "read that again", "close the chat", "new chat", "refresh the page", "sign me out".

### Tutorial voice (text to speech)

"Watch" steps repeat their example until Next is pressed, and the tutorial box moves to the place that covers the example least.


Every tutorial step is read aloud with the browser's free built-in voice ("Google US English" in Chrome, the same voice as the
assistant). The speaker button at the top right of the tutorial box turns the voice off or on; the choice is remembered on that
device. The voice stops when you press Next, Back, Skip or Esc.

### Dormitory Viewer, shared status rules and the assistant everywhere

* **One set of status rules** (`vacancy-core.js`, Python copy `server/vacancy_core.py`) is used by the Branch
  Admin, the Dormitory Viewer and the assistant, so a bed has the same status, colour and count everywhere.
  Colours are the Branch Admin Hallway colours: green vacant, blue occupied, amber checkout ≤48 h, brown
  temporary, red overdue, purple reserved. **Upcoming vacancy** = an occupied bed whose check-out is within
  7 days (dashed green outline); it stays counted as occupied.
* **Viewer cards:** each room shows total / occupied / vacant / upcoming / reserved, then every bed with its status,
  check-in and check-out dates. No names, photos or contact details are ever published to viewers.
* **Hallway map:** click a room to open its card beside the map; click it again, ×, Escape or an empty part of
  the map to close it; click another room to switch.
* **Filters** (gender, resident group, room, vacancy, search) apply to every number, the cards, the map and the
  analytics. The **CURRENT STATISTICS** bar stays at the top while scrolling and shows the active scope.
* **Assistant** is on the Branch Admin, Super Admin, Dormitory Viewer and directory pages after sign-in (never on
  the Home / sign-in screen) and continues the same conversation per account. On viewer pages it is read-only and
  never shows names. It understands misspellings and other wordings (`server/agent_nlu.py`); to teach it new
  wordings add example sentences to `EXAMPLES` there, and new explanations to `intents.json`.
* **Super Admin analytics:** a record stays in effect until the next one, so the chart always reaches NOW (also in
  the 1D / hourly view); schedules now carry the check-out / check-in time.

### Sample rooms for sample.one

The first time the local app starts it adds 24 rooms (S-101 …) with invented tenants, dates, a few
reservations and some Tenant History to **sample.one** (password Sample1234). It only adds rooms while the
account has fewer than 24 and never changes existing rooms. To add them by hand: `python server/sample_data.py`.

### November 2026 update (feedback A-0001 … A-0038)

**Existing PostgreSQL database:** run `psql "$DATABASE_URL" -f server/schema.sql` once more. It only adds the two new
tables (`branch_rooms`, `branch_photos`); nothing is deleted. Local mode (`run_local.py`) adds them by itself.

- **Super Admin:** the connect form asks for *Name of the super admin*; the Branch Admin's consent shows "by <name>".
  A third permission, **Room status & dorm view**, lets the Branch Admin share each room's bed status, tenant names,
  dates and room details, and lets that Super Admin open the dorm read-only (**View dorm**, no dorm code or password).
  The server only returns this to the Super Admin who sent the request, only while it is approved; revoking deletes
  the shared copy. Overview: frozen stats, one card per dorm with the Branch Admin's picture, a colour bar
  (occupied blue · vacant green · reserved violet · temporary brown · overdue red), summaries and an
  *Upcoming vacancies* list. Analytics chart: risk strip on the left (green Safe top · yellow Normal · red Risk bottom),
  vacancy drawn upside down so risk is at the bottom, recorded history labelled left of NOW; tidier toolbar.
  Server Details › Viewers: **Remove** (without blocking) next to **Block**.
- **Branch Admin:** frozen statistics on every tab (now with upcoming vacant, reserved and temporary); new legends;
  **Floors** (Hallway Layout › *Add floors / assign rooms*, *View floors*; each floor has its own map); check-in
  can't be saved without both dates or when the tenant doesn't fit the room (reason shown); **Inbox** tab with a red
  count for Super Admin permission requests, data-transfer requests and answers; Analytics shows reserved,
  temporary and a glowing *upcoming vacant*; every **Check out** asks for the tenant's record (Good / Bad + reason),
  shown in the Bed Matrix **Record** column; Central Link has a *Dormitory picture* upload; the supporting-documents
  box is gone from Tenant Information and its two panes stay in place while the page scrolls.
- **Assistant:** its own logo, no provider note or "Looking at" line, a clearer hint, and replies type out over
  about 5 seconds. Check-outs done through the assistant are not rated (it already asked you to confirm).

### November 2026 update, part 2 (second feedback file, 32 items)

No database change is needed (no new tables). Highlights:
- **Branch Admin:** statistics in two rows (bed statuses frozen with the filters; totals row folds away while you
  scroll), Super Admin-style cards with icons; the Record column moved from the Bed Matrix to **Tenant History**,
  which is now kept **2 years** and searchable with the search box; menu with icons, groups and animations.
- **Super Admin › Analytics:** the dormitory cards pick what the chart shows (click = only that one, double-click =
  add/remove, *All dormitories (combined)*, *Select all / Unselect all*, *Safe / Moderate / Risk* buttons), plain-language
  risk reasons, tinted cards, and a **?** help window.
- **Dormitory Viewer:** bigger frozen statistics, room cards tinted green (space) / blue (full), floor on each card and a
  read-only floor switch on the hallway map.
- **Marketing Directory:** frozen statistics and search; **View as dormitory viewer** opens the dorm directly. The server
  (`POST /api/central/open-dorm`) allows this only for someone who joined that Super Admin's directory with the current
  password and isn't blocked, for a dorm linked to that Super Admin with **Directory** approved and its own **Viewer
  Access** switched on. The person is added to that dorm's viewer list, where its Branch Admin can remove or block them.
  The Directory consent text now says so.
- **Tutorials:** a **?** button starts a hands-on tutorial for the current tab (`tutorial.js`, `tutorial.css`).
  On Branch Admin and Super Admin it is fixed just below the top bar (called **No. 1**), on the right.
  “Watch” steps show an example with a pretend mouse pointer: opening the Add room form, moving a tenant by
  dragging, the emergency card, extending a stay and the good/bad record, switching floors, filters fading the
  other rooms, unlocking the layout, adding a facility and removing it, floors, the checkout calendar and sliding
  the months, single and group reservations with a preview on the Room Canvas, temporary stays and reminders,
  tenant search, Viewer Access sub-tabs, and a two-account animation of Data Transfer. Demos never press Save,
  Add, Delete or Check out; they close everything they open and previews disappear. Replay repeats a demo.
- The Menu button shows a red **!** when something inside needs you (overdue tenants, Inbox, temporary reminders).
- Viewer Access + Super Admin: when your dorm is linked to a Super Admin, **Pause access**, **Change password** and
  **Turn off and delete** ask you for a reason, send a request (the reason shows in their Inbox), show
  **Pending approval…**, and happen by themselves once they accept (while the page is open). A new viewer password is
  only kept in the page's memory while waiting; after a reload you type it once more.
- Bed Matrix shows each bed as a card on a phone, with a coloured status.
- Hallway Layout: green cards have a free bed, blue cards are full; the current floor is named above the map;
  the floor buttons are always shown when there are floors (the old “View floors” button was removed).

## Importing sample rooms

`seed-data.js` holds real resident names, so `firebase.json` excludes it (and
`practice.html`) from deployment. The **Import my existing rooms** button is
therefore hidden on the live site and only works when you open the project
from your own computer (for example `firebase serve` or a local web server).

## Overdue reminders, reservations and tenant history

- **Overdue tenants** stay marked *Overdue* until the admin acts. A reminder
  panel at the top of the Room Canvas lists them with **Extend** and
  **Check out** buttons.
- **Reserving a bed:** the admin chooses the bed for each incoming client. The
  scan lists compatible vacant beds and scheduled checkouts. The list shows
  when the current tenant leaves compared with the client's arrival. If the
  tenant leaves after the client arrives, the admin must confirm.
- **Extending a stay** on a bed that has a reservation asks the admin to
  cancel that reservation first; the client returns to *Searching*.
- **Tenant History** keeps tenants who were checked out, removed or replaced
  for 30 days. The app deletes expired records automatically (at most once an
  hour while someone is signed in).

## Main workflows

- **Theme:** Use the moon/sun control on the sign-in screen or workspace header
  to switch between light and dark mode. The choice is saved in this browser.
- **Rooms and beds:** Add or edit a room from the Room Canvas or Hallway Layout.
  Room settings include gender, resident-group zoning, tenancy mode, capacity,
  AC status, and bed/resident details. The app prevents deleting occupied or
  reserved rooms and protects linked temporary-client assignments.
- **Shared views:** Room Canvas, Hallway Layout, Bed Matrix, Analytics,
  Checkout Schedule, and Reserved Clients share the live room KPIs and
  search/status/gender filters. The checkout schedule shows three months and
  filters by departure proximity.
- **Reservations:** Use **Reserve Clients** to record an incoming client,
  target check-in, resident group, and optional preferred bed. Confirm an
  eligible reservation from the matching checkout.
- **Temporary stays:** Use **Temporary Dorm Clients** to assign a compatible
  vacant bed. Check the guest out from the same tab to release it.
- **Transfers:** Use a resident's transfer action and select a compatible
  vacant bed. Transfers preserve resident and contract data and append an
  audit entry.
- **Hallway layout:** Unlock the layout before moving rooms. Add or edit
  facilities and walkways with the shape controls.

The Python assistant can answer questions about these existing features and
basic live counts. Its action support is deliberately limited to the action
types and fields accepted by `assistant.js`; unsupported or ambiguous requests
should be completed using the normal application interface.

## Project layout

`app.js` was split into smaller files in `js/`, loaded in this order by
`admin.html` (the order matters, and `99-main.js` must stay last):

| File | What it holds |
|---|---|
| `js/proof.js` | Shared code + password fingerprint helper (also used by the viewer page) |
| `js/01-state.js` | Shared settings and in-memory data |
| `js/02-auth-boot.js` | Start-up and sign-in state (no login screen: the front page signs in) |
| `js/03-clock-and-sync.js` | Live clock and data sync (SQL polling) |
| `js/04-helpers.js` | Date parsing, bed status, vacancy and matching rules |
| `js/05-dashboard.js` | Original room dashboard rendering |
| `js/06-rooms.js` | Add / edit / delete rooms |
| `js/07-transfers.js` | Resident transfers |
| `js/08-temporary-clients.js` | Bed pickers and temporary dorm clients |
| `js/09-hallway.js` | Hallway layout |
| `js/10-analytics-calendar.js` | Original analytics, matrix, checkout calendar rendering |
| `js/11-reservations.js` | Reserve Clients tab |
| `js/12-overdue-history.js` | Overdue reminders, check-out, extend stay, tenant history |
| `js/13-viewer-access.js` | Admin side of viewer access |
| `js/14-canvas-tabs.js` | Active Room Canvas, Bed Matrix, Analytics and Checkout Schedule views |
| `js/99-main.js` | Tabs, button wiring, `boot()` |

The old `app.js` is no longer used. Delete it from your project folder.

## Viewer access (read-only vacancy page)

1. Sign in as the admin and open the **Viewer Access** tab.
2. Choose a **dorm code** and a **password** (8+ characters) and turn it on.
3. Give viewers the link to `viewer.html`, the code and the password.
4. A viewer opens the page, signs in with the generated username and password, enters
   the code and password, and sees a read-only vacancy list, hallway layout, and summary
   analytics. The viewer asks for the dorm code and password again on each visit. It never receives
   resident names, personal details, or checkout dates: the admin app publishes
   name-free room counts to `dorms/{code}/vacancy` and sanitized hallway data
   to `dorms/{code}/layout/public`.
5. In the same tab the admin can see everyone who joined, **Remove** a viewer
   (they lose access immediately and cannot rejoin until you choose
   **Allow again**), pause access, change the password (this removes all
   current viewers) or turn viewer access off completely.

Notes:

- Vacancy counts and hallway layout are updated while an admin has the app open. If nobody has
  it open, viewers see the last published state.
- Pausing access stops new joins and new page loads. A viewer who already has
  the page open may keep seeing live data until they reload it.
- The password is never stored. Only a one-way fingerprint is kept, and only
  the admin account can read it. Choose a long password and a code that is
  hard to guess; anyone who knows both can join.
- Each admin account has one dorm code. The code can be 4-30 characters
  (letters, numbers, dashes) and must be unused.
- Viewers sign in with the shared username/password login, then enter the
  dorm code and password on the read-only viewer page.
- Dorm owners see a viewer's generated username only, never their original
  email.

## Testing access control

Authorization lives in `server/rules.py` and is covered by
`python -m pytest server/tests` (plus `node server/tests/client_test.mjs`
against a test server). After deploying, with two accounts (one admin, one viewer):

1. Viewer with the wrong password cannot join.
2. Viewer with the right password joins and sees the room list.
3. Viewer cannot read another user's records (the API returns "denied").
4. Admin removes the viewer: the viewer page shows "Access ended" and joining
   again fails. **Allow again** restores access.
5. Viewer cannot edit rooms or the hallway.
