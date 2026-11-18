# UX Audit: Vecancy Tracker (before the redesign)

Date: 17 Nov 2026. **No code has been changed yet.** Only this file was added.

- **Backup:** the whole project was copied to `..\backup-before-redesign\` (this folder isn't a git repository). The copy matches the original file for file.
- **How I checked:** I ran `python run_local.py`, signed in as `sample.one@example.com`, and opened every page and every Branch Admin tab at **375 px, 768 px and 1280 px**, in **light and dark mode**, using headless Chrome. A script also measured, on every screen:
  - sideways scrolling
  - tap targets smaller than 44 px
  - inputs with no label
  - images with no alt text
  - clickable elements that are not real buttons
  - text contrast (WCAG AA)
  - browser console errors
- **Screenshots:** `..\_uxtools\before\` (named `page-tab-width-theme.png`; `-full` = the whole scrolled page). The automatic check results are in `..\_uxtools\before\checks.json`.
- **Not complete yet:** the run was stopped because the computer ran low on memory. See §7 for what is covered and what is missing.

Priority: **High** = slows down or confuses the main job (find a bed, check in, reserve, check out) or breaks a required rule. **Medium** = noticeable friction. **Low** = polish.
Risk: how likely the fix is to break something. **Low** = text or CSS only. **Medium** = changes HTML structure that JavaScript uses. **High** = touches logic.

---

## 1. Top 10 fixes

| # | Fix | Page / files | Principle | Priority | Risk |
|---|---|---|---|---|---|
| 1 | **Group the 14 Branch Admin tabs into 7 menu items**, with sub-tabs inside each group (e.g. *Rooms · Floor Map · Bed List*). Keep every `data-tab`. | admin.html, menu.css, menu.js, js/14-canvas-tabs.js | Hick | High | Medium |
| 2 | **Rename confusing names** (Room Canvas, Bed Matrix, Central Link…) using the list in §3. Use the same name in tabs, headings, messages, tutorial and AI replies. The AI keeps understanding the old names too. | all pages, tutorial.js, server/agent.py, intents.json, SETUP-GUIDE.md | Jakob, Cognitive load | High | Low–Medium |
| 3 | **Stop showing the 9 number cards and 4 filters on top of every tab.** On a phone they fill the whole first screen (see `admin-reserve-375-light.png`), so the real content starts below the fold. Show 4 key numbers (Vacant, Occupied, Reserved, Overdue), put the rest behind "More numbers", and show the filters only on tabs that use them. | admin.html `.shared-overview`, styles.css | Miller, Cognitive load | High | Medium |
| 4 | **One "Occupied" number everywhere.** On the same data, the cards say **74**, the legend says **67** and Reports says **58** (see `admin-dashboard-768-light.png` and `admin-analytics-768-light.png`). They count different things but are all called "Occupied". Label them clearly, e.g. "Occupied (incl. reserved & short stay) 74", "Staying now 67". | js/04-helpers.js / stat strip, legend, analytics | Cognitive load | High | Medium (labels only, no maths change) |
| 5 | **Make "Check in" the clear main action on a free bed** and move "Remove bed" into *Edit room*. Right now every vacant bed shows **Check in** and **Remove bed** at the same size, one above the other, so a wrong tap is easy. | js/14-canvas-tabs.js, styles.css | Fitts, Hick | High | Low |
| 6 | **Friendly messages instead of browser pop-ups.** There are about **67** `alert()` / `confirm()` calls. They show technical text (e.g. "Transfer failed: <raw error>", "This room's zoning conflicts with a confirmed reservation."). Replace them with in-page messages that say what happened and what to do next, and add success messages with a next step ("Ana Reyes is checked in to Room S-105, Bed 2. [Back to Rooms] [Check in another]"). | js/*.js | Peak-End | High | alert: Low · confirm: **Medium–High** (see §6) |
| 7 | **Floating buttons cover content on phones.** The tutorial "?", the "How can I assist you?" bubble and the AI button sit on top of cards, links and status badges (Reservations, Share with Viewers, Tenants). Put them into one bottom-right stack, hide the bubble after the first visit, and add bottom space so nothing is hidden. | ai-chat.css, tutorial.css, assistant.js | Fitts | High | Low |
| 8 | **Design tokens.** The CSS has about **1,000 hard-coded hex colours, 450 rgba() colours and 3,900 px sizes**, and 5 files each define their own palette. Create `tokens.css` (light + dark) and use it on all six pages, so buttons, inputs, cards, chips, tabs and alerts look the same. | all CSS | Consistency | High | Medium (visual only, but big) |
| 9 | **Add room form in 2 short steps** ("Step 1 of 2: Room", "Step 2 of 2: Who can stay"), with plain labels ("How do you rent it?" instead of "Tenancy mode: Bedspace"). The reserve and short-stay wizards already have steps: add "Step 2 of 5" text and plain button names. | js/06-rooms.js, js/18-wizard.js, admin.html | Cognitive load | Medium | Medium |
| 10 | **Long lists need search, groups or "show more".** On a phone, Rooms is about 17,000 px tall and Bed List about 27,000 px tall. Add status chips (Vacant / Leaving soon / Overdue) that filter in one tap, a "Jump to room" search, and collapse full rooms by default. | admin Rooms, Bed List, Past Tenants | Miller, Fitts | Medium | Low–Medium |

---

## 2. Questions for you before I start

1. **Spelling of the name.** The footer, the front page title, the login title and the account usernames (`@vecancy.tracker`) say **"Vecancy"**. The logo image, the Branch Admin tab title, the hero text and SETUP-GUIDE.md say **"Vacancy"**. Which one is right? I won't change the logo image either way.
2. **"Vacant" or "Free"?** Your goals say "free bed", but the app says "Vacant" everywhere, and "vacant" is well known in the Philippines. My suggestion: keep the status name **Vacant** and use "free" only in action buttons ("Find a free bed"). OK?
3. **"Checkout Reminders" → I suggest "Overdue", not "Leaving Soon".** This tab only lists tenants *past* their check-out date ("Tenants past their check-out date"). "Leaving Soon" would suggest the wrong thing. The red badge stays.
4. **Role names on the login page.** Should the *roles* also be renamed ("Dormitory Viewer" → "Bed Availability", "Marketing Directory" → "Find a Dorm"), or only the page headers? I suggest renaming both, with the old name as small grey hint text for a while ("Bed Availability · was Dormitory Viewer").
5. **Browser `confirm()` pop-ups** (e.g. "Delete room?") stop the code until you answer. Replacing them with nicer in-page dialogs means changing about 25 places in the code to wait for the answer. I suggest doing that **only for the delete and check-out questions** and leaving the rest. OK?

---

## 3. Final rename list (only the visible text changes)

Element ids, `data-tab` values, classes, function names and saved data keys stay the same.

### Branch Admin tabs and headings
| Now (tab / heading) | New | Hint text under the heading |
|---|---|---|
| Room Canvas | **Rooms** | All rooms and beds, live. |
| Hallway Layout | **Floor Map** | Where each room is on the floor. |
| Bed Matrix / "Occupancy Matrix" (the tab and the heading use different names now) | **Bed List** | One line per bed. |
| Analytics | **Reports** | |
| Checkout Reminders | **Overdue** (see question 3) | Tenants past their check-out date. |
| Checkout Schedule | **Check-out Calendar** | |
| Reserved Clients / "Reserve Clients" (tab and heading differ now) | **Reservations** | |
| Temporary Dorm Clients | **Short Stays** | |
| Tenant Information | **Tenants** | |
| Tenant History | **Past Tenants** | Kept for 2 years. |
| Viewer Access | **Share with Viewers** | Let people see free beds. No names are shown. |
| Central Link | **Connect to Head Office** | Share with your Super Admin. |
| Data Transfer | **Hand Over Account** | Move this dormitory to a new account. |
| Inbox | Inbox | |

### Buttons
| Now | New |
|---|---|
| + Add reserve client / Add reserve client | **Reserve a bed** |
| + Add temporary client / Add temporary client | **Add short-stay guest** |
| Transfer resident | **Move to another bed** |
| Scan for vacancies | **Find a free bed** |
| Scan for temporary rooms | **Find a bed for a short stay** |
| Scan permanent rooms to move to | **Find a bed to move to** |
| Save new checkout | **Save new check-out date** |
| + Add Facility / Shape | **Add hallway, stairs or facility** |
| Add floors / assign rooms | **Floors** |
| Layout locked / unlocked | **Edit map** / **Done editing** |
| Save room | Save room (no change) |
| Check in / Check out / Extend | no change. "Checkout" as a word becomes **check-out** everywhere |
| Log in (login page) vs Sign in (front page) | **Sign in** everywhere |

### Form labels and options
| Now | New |
|---|---|
| Tenancy mode: Bedspace | **How do you rent it?** → **Shared room (rent per bed)** |
| Private room (whole room) | **Whole room (rent the room)** |
| Resident group / Resident group zoning | **Student or Reviewee** |
| Students / Reviewees / Mixed (options) | Students / Reviewees / **Both** |
| Gender assignment | **Who can stay: Male / Female / Mixed** |
| Target check-in / Target check-out (optional) | **Check-in date** / **Check-out date (optional)** |
| Client name | **Full name** |
| Room number / name | Room number (e.g. 220) |

### Bed status names (the colours do not change)
| Now | New |
|---|---|
| Vacant | Vacant (see question 2) |
| Occupied | Occupied |
| Reserved | Reserved: *counts as occupied* |
| Temporary | **Short stay**: *counts as occupied* |
| Overdue | Overdue |
| Checkout soon | **Leaving in 2 days** |
| Upcoming vacant / Has upcoming vacancy (7 days) | **Free within 7 days** |

### Other pages
| Now | New |
|---|---|
| Dormitory Viewer (page name) | **Bed Availability** |
| Viewer tabs: Vacancies / Hallway layout / Analytics | **Free Beds** / **Floor Map** / **Reports** |
| Marketing Directory / Dormitory Directory (page name) | **Find a Dorm** |
| Super Admin: Analytics | **Trends** |
| Super Admin: Server Details | **Connection Details** |
| Super Admin: Overview, Dormitories, Inbox, Accounts, Security | no change |
| Browser tab titles (now 6 different patterns) | "<Page name> · Vecancy Tracker" |

### Where the new names must also go
Counts below are how often the old names appear now.
- **tutorial.js**: about 30 step texts. The targets are CSS selectors (ids) and won't change.
- **server/agent.py** `ADMIN_TABS` and `SUPER_TABS`: change the label and **add** the new words to the patterns. For example, Bed List keeps `matrix` and adds `bed list`; Floor Map keeps `hallway|layout` and adds `floor map`.
- **server/agent_nlu.py, expert.py, answers.py, pages.py**, about 250 mentions in reply text. Only the reply text changes. Old words stay in the patterns.
- **intents.json**: about 100 mentions in responses. New patterns are added next to the old ones ("open reservations" and "open reserved clients").
- **assistant.js**: suggestion chips. **SETUP-GUIDE.md**: about 70 mentions.
- **server/tests**: some tests may check the old reply text. I will run them and update only expected reply text, never the behaviour.

---

## 4. New Branch Admin menu (7 items, all 14 tabs still reachable)

```
Rooms ▸        Rooms · Floor Map · Bed List            (data-tab: dashboard, hallway, matrix)
Bookings ▸     Reservations · Short Stays              (reserve, temporary)
Check-outs ▸   Overdue (red badge) · Check-out Calendar (reminders, calendar)
Tenants ▸      Tenants · Past Tenants                  (tenants, history)
Reports                                                (analytics)
Inbox (badge)                                          (inbox)
Sharing ▸      Share with Viewers · Connect to Head Office · Hand Over Account
                                                       (viewers, central, transfer)
```
- **Phone (375):** the hamburger opens the drawer with these 7 items. Groups open when you tap them, and the group you're in is already open. The overdue and inbox badges show on the group too.
- **Tablet and desktop (≥1024 px):** the same 7 items in a sidebar that is always visible, so you don't need the hamburger.
- **Inside a group:** a row of sub-tabs at the top of the page (e.g. `Rooms | Floor Map | Bed List`), so you can switch without opening the menu.
- **Account:** "Signed in as", the theme switch and **Sign out** go top-right on desktop and in the drawer footer on phones.
- **Logo:** top-left, linking home. The "Branch Admin" page label stays in the header.

---

## 5. Problems by principle

### Hick's Law: too many choices
| Page / file | Problem | Fix | Prio | Risk |
|---|---|---|---|---|
| admin.html `nav.tabs` | 14 tabs in one long drawer, with group labels that don't match the job ("Rooms & beds" contains Analytics and Checkout Schedule). The drawer is hidden even on a 1280 px screen. | §4 menu | High | Medium |
| admin Rooms | The main blue button is **+ Add room**, a rare task. The everyday task (find a free bed and check in) has no main button. | Main action = status chips + "Find a free bed". "Add room" becomes an outline button. | High | Low |
| admin Floor Map | 5 buttons with the same weight (Layout locked, Add Facility/Shape, Edit shape, Add room, Add floors). | Show only "Edit map". When editing, show the editing buttons; "Done editing" is the main one. | Medium | Low |
| admin, all tabs | Filters (gender, status, resident group, search) show on Sharing, Inbox and Reports, where they do nothing. | Show them only on Rooms, Bed List, Past Tenants and Tenants. | High | Medium |
| admin Tenants | **Two search boxes** on one screen (the general one and "Search tenant name or room number"). | Keep one. | Medium | Low |
| admin Short Stays | The old inline form (single/group, scan, step 2, step 3) is still in the page next to the wizard. | Keep the wizard as the only way in. Old fields stay hidden (the wizard needs them). | Low | Low |

### Jakob's Law: familiar patterns
| Page / file | Problem | Fix | Prio | Risk |
|---|---|---|---|---|
| admin header | At 375/768 px there is no visible logo, and the "Branch Admin" page label is hidden. A seconds clock (07:17:03 PM) takes a whole row on phones. | Logo top-left (links home), page label next to it. Clock: time only on desktop, hidden on phones. | Medium | Low |
| all pages | The theme choice is saved under 3 different keys (`loginTheme`, `centralTheme`, `vtLandingTheme`). Dark mode chosen on the front page is not used on Super Admin, and the other way round. | Small shared theme helper that reads and writes **all three** keys (keys stay as they are). | Medium | Low |
| admin search | Plain text box, no magnifying-glass icon, no clear button. | `type="search"` with an icon. | Low | Low |
| index ↔ login | The front page says "Sign in", the login page says "Log in". | "Sign in" everywhere. | Low | Low |

### Cognitive load
| Page / file | Problem | Fix | Prio | Risk |
|---|---|---|---|---|
| admin numbers | "Occupied" 74 / 67 / 58 on the same screen set (Top 10 #4). | Clear labels. | High | Medium |
| admin legend | 7 statuses; "Checkout soon" and "Upcoming vacant" overlap, and orange/brown/red look alike. | Plain names (§3). Legend folds into a "What the colours mean" button on phones. | Medium | Low |
| Add room / Edit room | 7 fields + capacity in one box, with jargon ("Resident group zoning", "Tenancy mode", "Bedspace"). | 2 steps, plain labels, hints. | Medium | Medium |
| Reserve / Short-stay wizard | A progress bar, but no "Step 2 of 5" text. Button names are system words ("Scan…"). | Add step text and rename. | Medium | Low |
| view sub-texts | Long sentences ("Layout starts locked to prevent accidental changes. Unlock to reposition rooms and shapes."). | One short line. | Low | Low |

### Miller's Law: chunking
| Page / file | Problem | Fix | Prio | Risk |
|---|---|---|---|---|
| admin stat strip | 9 number cards in one block. | 4 + "More numbers" (Top 10 #3). | High | Medium |
| admin Rooms / Bed List | Very long scrolling lists on a phone (17k and 27k px). | Status chips, jump-to-room, collapse full rooms (Top 10 #10). | Medium | Low–Medium |
| admin Tenants | 24 room folders, then tenants. OK, but no count of tenants at the top. | "81 tenants in 24 rooms" line and a single search. | Low | Low |
| phone numbers / codes | Shown as typed. | Show 0917 123 4567 and ABCD-1234 (display only; saved values don't change). | Low | Low |

### Fitts's Law: easy to tap
| Page / file | Problem | Fix | Prio | Risk |
|---|---|---|---|---|
| admin bed cards | "Check in" and "Remove bed" are the same size and next to each other. The edit (✎) and delete (🗑) icons on rooms are about 24 px. | Top 10 #5, 44 px icon buttons. | High | Low |
| floating buttons | They cover content on phones (Top 10 #7). | One stack, bottom padding. | High | Low |
| login, index | Theme and close buttons are 38 px; quick-account chips are 34 px high. | 44 px. | Low | Low |
| admin wizard / modals on phone | Main buttons are at the bottom of the dialog, which is good. Overdue cards use small "Extend" / "Check out" buttons (about 32 px). | 44 px; "Check out" is the main one. | Medium | Low |

### Peak-End Rule: key moments
| Page / file | Problem | Fix | Prio | Risk |
|---|---|---|---|---|
| js/*.js | About 67 browser pop-ups, technical wording, no next step (Top 10 #6). | In-page messages and success messages. | High | Low / Medium |
| Check-out dialog | This one is good: it asks for a good/bad record first and names the room and bed. | Keep. Add a success message ("Carlo Santos checked out. Room S-101, Bed 1 is now vacant."). | Medium | Low |
| empty states | Some exist ("No temporary dorm clients yet."), but there's no button to start. | "No short stays yet. [Add short-stay guest]" and the same on other tabs. | Medium | Low |
| index (front page) | Below the hero, sections only appear when you scroll to them. A full-page capture shows big empty blocks. That's normal for scroll animations, but with **Reduce motion** on they should show right away. | Respect `prefers-reduced-motion`. | Low | Low |

---

## 6. Risks I see
- **The menu change (#1)** moves buttons that `js/14-canvas-tabs.js`, `menu.js`, the tutorial and the AI (`nav` replies) click by `data-tab`. I'll keep the same 14 `<button data-tab>` elements and only wrap them in groups. The tutorial and AI then still work.
- **`confirm()` → in-page dialog** changes code flow. That's why I'm limiting it to delete and check-out (question 5).
- **Tokens (#8)** touch every CSS file. I'll do it file by file, with before/after screenshots at all 3 widths in both themes, and the contrast check from the audit script.
- **AI renames**: only reply text and extra patterns. I'll run `server/tests` before and after.

---

## 7. Automated check results (before)

**Status: not finished.** The computer ran low on memory and the screenshot run and the local server were stopped. What I have so far:

| Page | 375 | 768 | 1280 | Automatic checks |
|---|---|---|---|---|
| index.html (front page) | ✓ light/dark | ✓ | ✓ | ✓ No sideways scroll, no contrast failures, all images have alt text. 12–15 targets are under 44 px (nav links, theme button, "Sign in" 38 px). |
| login.html | ✓ | ✓ | ✓ | ✓ No sideways scroll, no contrast failures, all fields labelled. 7 small targets (theme 38 px, close 38 px, "Show" 32 px, quick-account chips 34 px). At 1280×800 the **Log in button is below the fold**. |
| admin.html (all 14 tabs) | ✓ light/dark | ✓ light/dark | ✓ light only | **Not saved**: the numbers are written at the end of the run. Screenshots only. |
| viewer.html (Bed Availability) | ✗ | ✗ | ✗ | not done |
| marketing.html (Find a Dorm) | ✗ | ✗ | ✗ | not done |
| superadmin.html | ✗ | ✗ | ✗ | not done |

Still to do: Bed Availability, Find a Dorm, Super Admin, admin at 1280 in dark mode, and the contrast, tap-target and label numbers for the logged-in pages.
