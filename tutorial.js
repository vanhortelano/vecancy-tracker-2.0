/* tutorial.js — hands-on tutorials ("learning by doing") for every page (feedback A-0030 … A-0033).
   A round "?" button sits just below the Sign out button. It starts the tutorial for the tab you are on:
   - everything except the part being explained is dimmed and slightly blurred;
   - an animated arrow points at it;
   - captions appear like a film (black bars, text typed out);
   - when a step says "Try it", the tutorial waits until you really click / type / choose there — clicking anywhere
     else does nothing; plain explanation steps have a Next button;
   - Skip (bottom right) or Esc ends it at any time.
   - "Watch" steps (feedback A-0018 … A-0065) show an example: a pretend mouse pointer opens forms, types, switches
     floors or months and draws a preview of the result. Use Replay to see it again.
   The tutorial never saves, deletes or checks anybody out: demos close every form they open, and previews disappear. */
(function(){
"use strict";
const $ = (s, r)=>(r || document).querySelector(s);
const esc = s=>String(s == null ? "" : s).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
// "visible" also means not faded out: a closed pop-up that is only see-through (opacity 0) does not count (fix for A-0001:
// after the calendar demo the tutorial kept pointing at the closed calendar box and showed an empty frame)
const visible = el=>{
  if (!el || !el.isConnected) return false;
  const r = el.getBoundingClientRect(); if (r.width <= 2 || r.height <= 2) return false;
  if (el.checkVisibility) return el.checkVisibility({opacityProperty:true, visibilityProperty:true});
  for (let n = el; n && n.nodeType === 1; n = n.parentElement){ const cs = getComputedStyle(n); if (cs.visibility === "hidden" || cs.display === "none" || Number(cs.opacity) < 0.05) return false; }
  return true;
};
const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ------------------------------------------------------------------ tours, per page */
const S = (sel, title, text, act, extra)=>Object.assign({sel, title, text, act:act || null}, extra || {});

/* ---------- helpers used by the Branch Admin demos (they only open/close screens; nothing is saved) ---------- */
const vis = sel=>Array.from(document.querySelectorAll(sel)).find(visible) || null;
const clickIf = sel=>{ const e = vis(sel); if (e) e.click(); return !!e; };
const isOpen = id=>{ const m = document.getElementById(id); return !!(m && m.classList.contains("open")); };
const setVal = (sel, v, evt)=>{ const e = $(sel); if (e && e.value !== v){ e.value = v; e.dispatchEvent(new Event(evt || "change", {bubbles:true})); } };
function resetFilters(){
  ["#filterGender", "#filterVacancy", "#filterDemographic"].forEach(s=>setVal(s, "all"));
  setVal("#filterSearch", "", "input");
}
function closeRoomForm(){ if (isOpen("roomModalBackdrop")) clickIf("#cancelRoomModal") || clickIf("#closeRoomModal"); }
function closeSide(){ clickIf("#tiSidePanel [data-ti-close]"); }
function closeAssistant(){ const l = $("#assistantLauncher"); if (l && l.getAttribute("aria-expanded") === "true") l.click(); }
function closeRecord(){ clickIf('#recordModal [data-rec="cancel"]'); }
function closeExtend(){ if (isOpen("extendModalBackdrop")) clickIf("#closeExtendModal"); }
function closeShape(){ if (isOpen("shapeModalBackdrop")) clickIf("#closeShapeModal"); }
function closeFloors(){ if (isOpen("floorsModalBackdrop")) clickIf("#floorsModalBackdrop [data-fl-close]"); }
function closeWizard(){ if (document.querySelector(".wz-overlay.open")) clickIf('.wz-overlay.open [data-wz="cancel"]') || clickIf(".wz-overlay.open .wz-x"); }
function closeCalendar(){ clickIf('.co-modal.open [data-cm="cancel"]'); }
function lockLayout(){ const b = $("#layoutLockBtn"); if (b && typeof layoutLocked !== "undefined" && !layoutLocked) b.click(); }
const firstBed = ()=>vis("#roomGrid article[data-canvas-drag]");
const freeBed = ()=>vis("#roomGrid article[data-canvas-drop]");

const ADMIN = {
  signOut:"#signOutBtn",
  below:"header.topbar",      // A-0002 / A-0017: fixed just below the top bar ("No. 1"), on the right, never over other parts
  tab:()=>{ const b = $("nav.tabs button.active"); return b ? b.dataset.tab : "dashboard"; },
  label:k=>{ const b = $('nav.tabs button[data-tab="' + k + '"] .nav-txt'); return b ? b.textContent.trim() : k; },
  go:k=>{ if (typeof switchTab === "function") switchTab(k); document.body.classList.remove("menu-open"); },
  cleanup:()=>{ closeRoomForm(); closeSide(); closeAssistant(); closeRecord(); closeExtend(); closeShape(); closeFloors(); closeWizard(); closeCalendar(); lockLayout(); resetFilters(); },
  tours:{
    dashboard:[
      S("header.topbar", "No. 1 — the top bar", "Menu, the page you are on, the clock, your account, light/dark mode and Sign out. It stays at the top while you scroll. This “?” button always sits just below it."),
      S(".shared-overview .ov-row1", "Your beds at a glance", "These six cards count your beds right now: vacant, occupied, leaving soon, reserved, temporary and overdue. They stay at the top on every tab."),
      S(".shared-overview .ov-row2", "Totals", "Rooms, bed capacity and how full the dorm is. This row folds away when you scroll down."),
      S("#view-dashboard [data-live-legend]", "The colour legend", "Each colour is a bed status, with how many beds have it and what it means."),
      S("#roomGrid", "Your rooms", "Each card is one room with its beds. Green = vacant, blue = occupied, red = overdue, violet = reserved."),
      // A-0018 / A-0019: the Add room form and Save room
      S("#addRoomBtn", "Example: add a room", "Watch: this opens the Add room form. (The tutorial never saves anything.)", null,
        {demo:async D=>{ await D.click("#addRoomBtn"); }}),
      S("#roomModalBackdrop .modal-body", "The room form", "Type the room number, choose Room or Bedspacer, gender, resident group, aircon and how many beds. Watch the example.", null,
        {before:()=>{ if (!isOpen("roomModalBackdrop")) clickIf("#addRoomBtn"); },
         demo:async D=>{ await D.type("#rmRoomNumber", "DEMO-101"); await D.choose("#rmType", "Bedspacer"); await D.wait(400); await D.choose("#rmType", "Room"); }}),
      S("#saveRoomBtn", "Save room", "Save room adds the room and its beds to every tab at once. This time the tutorial only points at it, then closes the form without saving.", null,
        {before:()=>{ if (!isOpen("roomModalBackdrop")) clickIf("#addRoomBtn"); }, demo:async D=>{ await D.move("#saveRoomBtn"); await D.wait(700); }, after:closeRoomForm}),
      // A-0024 … A-0028: the buttons on a room and its beds
      S("#roomGrid .canvas-room-head [title='Edit room']", "✎ Edit room", "Change the room's number, type, gender, resident group, aircon or number of beds."),
      S("#roomGrid .canvas-room-head [data-canvas-action='delete-room']", "🗑 Delete room", "Deletes the room. You are asked first, and a room with tenants can't be deleted by accident."),
      S("#roomGrid article[data-canvas-drag] [data-canvas-action='edit-room']", "Edit (a tenant's bed)", "Change this tenant's name, dates, resident type and other details."),
      S("#roomGrid article[data-canvas-drag] [data-canvas-action='checkout']", "Check out", "Ends the stay. You are first asked whether the tenant had a good or bad record; the stay then goes to Tenant History."),
      S("#roomGrid article[data-canvas-drop] [data-canvas-action='edit-room']", "Check in (a vacant bed)", "Put a new tenant in this free bed: name, dates and resident type."),
      S("#roomGrid article[data-canvas-drop] button[onclick^='removeBed']", "Remove bed", "Removes an empty bed from the room, for example when a bed is taken out."),
      // A-0022 / A-0029: Move, and dragging a bed
      S("#roomGrid article[data-canvas-drag] [data-canvas-action='move']", "Example: move a tenant", "Move sends a tenant to another free bed. You can also DRAG the tenant's bed card and drop it on a vacant bed. Watch the example (a preview only — nobody really moves).", null,
        {demo:async D=>{ const a = firstBed(), b = freeBed(); await D.move(a && a.querySelector("[data-canvas-action='move']")); if (a && b) await D.drag(a, b, "Drop here to move"); }}),
      // A-0020: emergency card
      S("#roomGrid .canvas-bed-name[data-ec]", "Example: the emergency card", "Click a tenant's name to open their emergency card. Watch.", null,
        {demo:async D=>{ await D.click("#roomGrid .canvas-bed-name[data-ec]"); }}),
      S("#tiSidePanel", "Tenant emergency card", "Contact number, address and emergency contacts of the tenant, beside the canvas. Close it with ×.", null,
        {before:()=>{ if (!vis("#tiSidePanel")) clickIf("#roomGrid .canvas-bed-name[data-ec]"); }, after:closeSide}),
      // A-0021: the assistant
      S("#assistantLauncher", "Example: the dorm assistant", "Ask questions in plain words: “Which rooms are free for a female student?”, “Open Room S-101”. Watch it open and close.", null,
        {demo:async D=>{ await D.click("#assistantLauncher"); await D.wait(1200); await D.click("#assistantLauncher"); }, after:closeAssistant}),
      // filters (try them yourself; they are reset when the tutorial ends)
      S("#filterVacancy", "Try it: filter the rooms", "Pick a status in this list, for example “Vacant”. Every tab follows these filters.", "change"),
      S("#filterSearch", "Try it: search", "Type a room number or a tenant's name here.", "input", {after:resetFilters}),
      S("#app .menu-btn[data-menu-toggle]", "The menu", "All the other tabs are in the menu. A red “!” on it means something inside needs you, for example overdue tenants.")
    ],
    reminders:[
      // A-0031 / A-0032: the notification
      S("#app .menu-btn[data-menu-toggle]", "Notifications", "When a tenant is overdue, the Menu button shows a red “!” and the Checkout Reminders tab shows a red number, so you notice it on any tab."),
      S("#view-reminders .view-title", "Checkout Reminders", "Tenants whose check-out date has passed appear here, so nobody is forgotten."),
      S("#overduePanel", "Overdue tenants", "For each one: Extend the stay, or Check out."),
      // A-0034: extend
      S("#overduePanel .overdue-row .btn-outline", "Example: extend a stay", "Extend sets a new check-out date. Watch it open.", null,
        {demo:async D=>{ await D.click("#overduePanel .overdue-row .btn-outline"); }}),
      S("#extendModalBackdrop .modal", "Extend stay", "Pick the new check-out date and time. If someone reserved the bed, you are warned and can cancel that reservation. The tutorial closes it without saving.", null,
        {before:()=>{ if (!isOpen("extendModalBackdrop")) clickIf("#overduePanel .overdue-row .btn-outline"); },
         demo:async D=>{ await D.move("#extendNewEnd"); await D.wait(500); await D.move("#saveExtendBtn"); await D.wait(500); }, after:closeExtend}),
      // A-0033: check out with a record
      S("#overduePanel .overdue-row .btn-primary", "Example: check out", "Check out first asks how the stay went. Watch.", null,
        {demo:async D=>{ await D.click("#overduePanel .overdue-row .btn-primary"); }}),
      S("#recordModal .modal", "Good or bad record", "Choose Good, or Bad and write the reason. The record is kept in Tenant History. The tutorial picks Good to show you, then presses Cancel — nobody is checked out.", null,
        {before:()=>{ if (!vis("#recordModal .modal")) clickIf("#overduePanel .overdue-row .btn-primary"); },
         demo:async D=>{ await D.click('#recordModal [data-rec="good"]'); await D.wait(400); await D.click('#recordModal [data-rec="bad"]'); await D.type("#recReason", "Example: unpaid balance"); await D.wait(500); await D.move('#recordModal [data-rec="ok"]'); await D.wait(500); },
         after:closeRecord})
    ],
    inbox:[
      S("#view-inbox .view-title", "Inbox", "Every request that needs your answer comes here. The red number on the Inbox tab counts what is waiting."),
      S("#inboxPanel", "Requests", "Super Admin permission requests, data-transfer requests and answers to your own requests. Approve, Reject or Revoke each one.")
    ],
    hallway:[
      S("#hallwayCanvas", "Hallway Layout", "A map of your floor. Green cards still have a free bed; blue cards are full. The dots are the beds in their status colours."),
      S("#hallFloorTag", "The floor you are on", "The name of the floor this map shows."),
      // A-0041: floors bar
      S("#floorBar", "Example: switch floors", "Each floor has its own map. Watch: the tutorial switches floor and back.", null,
        {demo:async D=>{ const chips = Array.from(document.querySelectorAll("#floorBar .floor-chip")); const on = chips.find(c=>c.classList.contains("on")); const other = chips.find(c=>!c.classList.contains("on"));
          if (other){ await D.click(other); await D.wait(900); D.focus("#hallwayCanvas"); await D.wait(800); D.focus("#floorBar"); if (on){ const back = Array.from(document.querySelectorAll("#floorBar .floor-chip")).find(c=>c.dataset.floor === on.dataset.floor); await D.click(back); } } }}),
      // A-0044: filters make other rooms transparent
      S(".shared-overview", "Example: filters on the map", "Choose a status, gender or resident group above. Rooms that don't match become see-through, so the matching ones stand out. Watch.", null,
        {demo:async D=>{ await D.choose("#filterVacancy", "vacant"); D.focus("#hallwayCanvas"); await D.wait(1800); D.focus(".shared-overview"); await D.choose("#filterVacancy", "all"); }, after:resetFilters}),
      S("#hallwayCanvas .room-tile", "Try it: open a room", "Click this room to see its beds and tenants beside the map.", "click", {after:closeSide}),
      // A-0035: lock / unlock
      S("#layoutLockBtn", "Example: unlock the layout", "Unlock to drag rooms and facilities to their real places; lock again when done. Watch: the tutorial unlocks, shows a drag (preview only, nothing moves), then locks again.", null,
        {demo:async D=>{ await D.click("#layoutLockBtn"); await D.wait(400); const t = vis("#hallwayCanvas .room-tile"); if (t) await D.drag(t, {dx:140, dy:90}, "Drag to place it"); await D.click("#layoutLockBtn"); }, after:lockLayout}),
      // A-0036 / A-0042: add a facility, then remove it
      S("#addShapeBtn", "Example: add a facility", "Add stairs, a comfort room, a lobby or a walkway to the map. Watch the form.", null,
        {demo:async D=>{ await D.click("#addShapeBtn"); }}),
      S("#shapeModalBackdrop .modal", "The facility form", "Give it a label, choose where the label sits, the type (facility or walkway), the shape and its size and colour.", null,
        {before:()=>{ if (!isOpen("shapeModalBackdrop")) clickIf("#addShapeBtn"); },
         demo:async D=>{ await D.type("#shapeLabel", "Stairs"); await D.choose("#shapeLabelRotation", "90"); await D.wait(300); await D.choose("#shapeLabelRotation", "0"); }, after:closeShape}),
      S("#hallwayCanvas", "Example: the facility on the map, then removing it", "After saving it appears on the map (this is a preview). To remove one: unlock the layout, click the shape, then Edit → Delete. Watch the preview being removed.", null,
        {before:closeShape,
         demo:async D=>{ const g = D.ghostOn("#hallwayCanvas", '<div class="vt-demo-shape">Stairs <small>preview</small></div>', {x:0.62, y:0.55}); await D.wait(900); await D.move(g); await D.wait(500); D.say("Removed: in real use, unlock → click the shape → Edit → Delete."); g.classList.add("vt-out"); await D.wait(700); }}),
      // A-0037 / A-0043: floors
      S("#manageFloorsBtn", "Example: add floors", "Add a floor, name it, then tick the rooms that are on it. Watch.", null,
        {demo:async D=>{ await D.click("#manageFloorsBtn"); }}),
      S("#floorsModalBackdrop .modal", "The floors form", "Type a floor name and press Add, choose a floor on the left, then tick its rooms. Save floors makes one map per floor. The tutorial closes it without saving.", null,
        {before:()=>{ if (!isOpen("floorsModalBackdrop") && typeof openFloorsModal === "function") openFloorsModal(); },
         demo:async D=>{ await D.type("#floorNewName", "Third floor"); await D.wait(500); }, after:closeFloors})
    ],
    analytics:[
      S("#analyticsContent .an-dist", "Bed occupancy distribution", "Every bed is counted once: occupied, upcoming vacant (glowing), temporary, overdue, reserved or vacant."),
      S("#analyticsContent .an-extra", "Clients", "Reserved clients waiting, temporary clients and beds that will be vacant within 7 days."),
      S("#analyticsContent .an-sum", "Room capacities", "The whole dorm in one bar, then every room below it with its own bar and summary.")
    ],
    matrix:[
      S("#matrixTable", "Bed Matrix", "One row per bed: tenant, dates, room details and actions. Good for finding one bed or person quickly."),
      S("#filterSearch", "Try it: find a bed", "Type a tenant's name or a room number. The table shows only matching beds.", "input", {after:resetFilters})
    ],
    calendar:[
      // A-0045 / A-0046
      S("#coStage", "Checkout Schedule", "Each card is a month with the tenants leaving in it. The card in front is the month you are looking at."),
      S("#coStage", "Example: slide the months", "Press anywhere on the cards and SLIDE left for the next month or right for the previous one — with the mouse or your finger. Let go and the nearest month snaps to the front. Watch.", null,
        {demo:async D=>{ await D.slide("#coStage", -1); await D.wait(900); D.say("Slid left: the next month came to the front. Now sliding right to go back."); await D.slide("#coStage", 1); await D.wait(900); D.say("You can slide several months in one go; the buttons of the front card come back as soon as it stops."); await D.slide("#coStage", -2); await D.wait(900); await D.click('#coStage [data-canvas-action="checkout-active"]'); }}),
      S('#coStage [data-canvas-action="checkout-nav"][data-delta="1"]', "Example: ‹ › buttons", "The arrows turn one month at a time. Watch.", null,
        {demo:async D=>{ await D.click('#coStage [data-canvas-action="checkout-nav"][data-delta="1"]'); await D.wait(700); await D.click('#coStage [data-canvas-action="checkout-nav"][data-delta="-1"]'); await D.wait(400); }}),
      S('#coStage [data-canvas-action="checkout-active"]', "Jump to Active", "Brings you back to the current month."),
      S('#coStage [data-canvas-action="checkout-filter"]', "Near · Moderate · Far", "Near = overdue or leaving within 3 days, Moderate = 4–10 days, Far = 11 days or more. Click one to show only those."),
      S('#coStage [data-canvas-action="checkout-picker"]', "Example: the calendar", "Pick a day to see who leaves then. Watch.", null,
        {demo:async D=>{ await D.click('#coStage [data-canvas-action="checkout-picker"]'); await D.wait(500); const day = vis(".co-modal.open #coGrid button i") ? vis(".co-modal.open #coGrid button i").parentElement : vis(".co-modal.open #coGrid button"); if (day){ D.focus(".co-modal.open .co-modal-card"); await D.click(day); await D.wait(1200); } await D.click('.co-modal.open [data-cm="cancel"]'); }, after:closeCalendar}),
      S("#coLive .co-guest .co-actions, #coStage .co-card.is-active .co-actions", "A tenant's buttons", "Edit their details, Extend the stay, Check out, or Inspect to jump to their bed on the Room Canvas.")
    ],
    reserve:[
      // A-0047 / A-0048: single and group
      S("#openReserveWizard", "Example 1: reserve for one person", "Watch the wizard: Single → name → details → it lists the free beds that fit. The tutorial stops before adding.", null,
        {demo:async D=>{ await D.click("#openReserveWizard"); }}),
      S(".wz-overlay.open .wz-card", "Single", "", null,
        {before:()=>{ if (!document.querySelector(".wz-overlay.open")) clickIf("#openReserveWizard"); },
         text:"Single is for one person. Watch: name, details, then the free beds that fit.",
         demo:async D=>{ await D.click('.wz-card [data-mode="single"]'); await D.type('.wz-card [data-name="0"]', "Demo Client"); await D.click('.wz-card [data-wz="next"]'); await D.wait(500);
           await D.click('.wz-card [data-wz="next"]'); await D.wait(900); D.say("These are the beds that fit this client's gender, group and dates. You would pick one and press Add. The tutorial does not add anything."); await D.wait(1600); }}),
      S("#roomGrid", "The result on the Room Canvas", "After adding, the bed turns violet (Reserved) on the Room Canvas and shows the client's name and check-in date. This is a preview of how it looks.", null,
        {before:()=>{ closeWizard(); ADMIN.go("dashboard"); },
         demo:async D=>{ const b = freeBed(); if (b){ await D.move(b); D.ghostOn(b, '<div class="vt-demo-badge">Reserved · Demo Client<small>preview — not saved</small></div>', {x:0.5, y:0.5}); await D.wait(2200); } },
         after:()=>{ ADMIN.go("reserve"); }}),
      S("#openReserveWizard", "Example 2: reserve for a group", "A group is several people who stay together. Watch.", null,
        {demo:async D=>{ await D.click("#openReserveWizard"); }}),
      S(".wz-overlay.open .wz-card", "Group", "Group asks how many people, then each name. The wizard looks for beds next to each other that fit everyone.", null,
        {before:()=>{ if (!document.querySelector(".wz-overlay.open")) clickIf("#openReserveWizard"); },
         demo:async D=>{ await D.click('.wz-card [data-mode="group"]'); await D.type("#wzCount", "3"); await D.click('.wz-card [data-wz="next"]'); await D.type('.wz-card [data-name="0"]', "Ana"); await D.type('.wz-card [data-name="1"]', "Bea"); await D.type('.wz-card [data-name="2"]', "Cara"); await D.wait(500); D.say("Next would show the details and the free beds for all three. The tutorial closes it without adding."); await D.wait(1500); },
         after:closeWizard}),
      S("#prospectList", "Reserved clients", "Everyone waiting to move in, with the bed reserved for them."),
      // A-0049 / A-0051 / A-0050
      S("#prospectList .prospect-card .match-box .btn-outline", "Undo", "Undo cancels the bed reservation but keeps the client in the list, so you can pick another bed."),
      S("#prospectList .prospect-card .match-box.choose", "Reserve this bed", "When no bed is reserved yet, choose one from the list and press Reserve this bed."),
      S("#prospectList .prospect-card .icon-btn", "🗑 Delete", "Removes the client and frees any bed held for them. You are asked first.")
    ],
    temporary:[
      // A-0052
      S("#openTempWizard", "Example: a temporary stay", "Same steps as a reservation: Single or Group, names, dates, then rooms with a free bed for those dates. Watch.", null,
        {demo:async D=>{ await D.click("#openTempWizard"); }}),
      S(".wz-overlay.open .wz-card", "Temporary stay", "Choose Single or Group. Watch the single example; the tutorial closes before adding.", null,
        {before:()=>{ if (!document.querySelector(".wz-overlay.open")) clickIf("#openTempWizard"); },
         demo:async D=>{ await D.click('.wz-card [data-mode="single"]'); await D.type('.wz-card [data-name="0"]', "Short Stay Guest"); await D.click('.wz-card [data-wz="next"]'); await D.wait(500); await D.click('.wz-card [data-wz="next"]'); await D.wait(1200); D.say("These rooms have a free bed for the dates. After adding, the bed turns brown (Temporary) on the Room Canvas."); await D.wait(1500); },
         after:closeWizard}),
      // A-0053
      S("#tempRemTab", "Example: Reminders", "When a temporary stay ends, it appears in Reminders and asks: has the guest moved out or transferred? Watch.", null,
        {demo:async D=>{ await D.click("#tempRemTab"); D.focus("#tempRemBox"); await D.wait(1600); D.focus("#tempRemTab"); await D.click('[data-tsub="clients"]'); }}),
      S("#temporaryList", "Current temporary clients", "Each card shows the room, bed and dates. Brown is the temporary colour everywhere.")
    ],
    history:[
      S("#historyList", "Tenant History", "Everyone who checked out, kept for 2 years, with how long they stayed and why they left."),
      // A-0054
      S("#historyList .rec-cell", "Record", "✓ = good record, ✗ = bad record, chosen at check-out. Click a ✗ to read the reason. It helps you decide before accepting the same person again."),
      // A-0055
      S("#filterSearch", "Example: search past tenants", "Type a name to find a past tenant. Watch.", null,
        {demo:async D=>{ const n = vis("#historyList tbody tr td:nth-child(1)") || vis("#historyList tr td"); const name = n ? n.textContent.trim().split(/\s+/)[0] : "Santos"; await D.type("#filterSearch", name.slice(0, 12)); D.focus("#historyList"); await D.wait(1500); D.focus("#filterSearch"); await D.type("#filterSearch", ""); }, after:resetFilters})
    ],
    tenants:[
      S("#tenantInfoPanel .ti-left", "Rooms and tenants", "Pick a room, then a tenant. This list scrolls on its own."),
      // A-0056 / A-0057
      // A-0091: why the emergency card matters
      S(null, "Why the emergency card matters — watch", "A tenant gets sick at night. The Branch Admin opens the emergency card and calls the parent right away, without searching through papers.", null,
        {media:"emergency", demo:async D=>{ await D.playMedia(12500); }}),
      S("#tenantInfoPanel .ti-left", "Example: open a tenant", "Watch: open a room folder, then pick a tenant.", null,
        {demo:async D=>{ if (!vis("#tenantInfoPanel .ti-card")) await D.click("#tenantInfoPanel .ti-folder"); D.focus("#tenantInfoPanel .ti-right"); await D.wait(500); await D.click("#tenantInfoPanel .ti-card"); await D.wait(500); }}),
      S("#tenantInfoPanel .ti-right", "The tenant's page", "Everything about the selected tenant on one side: photo, details and Edit."),
      S("#tenantInfoPanel .ti-right .ec-card", "Emergency card", "Contact number, address, school or work, and the people to call in an emergency. Edit them here; the card on the Room Canvas shows the same.",
        null, {before:()=>{ if (!vis("#tenantInfoPanel .ec-card")){ if (!vis("#tenantInfoPanel .ti-card")) clickIf("#tenantInfoPanel .ti-folder"); setTimeout(()=>clickIf("#tenantInfoPanel .ti-card"), 120); } }})
    ],
    viewers:[
      // A-0058 … A-0060
      S("#viewerAccessPanel .va-card", "Viewer Access", "Your dorm code, the viewer page link and the password. Viewers see only free and taken beds, never names."),
      // A-0084: how a viewer gets in, and how a password change works when you are linked to a Super Admin
      S(null, "How viewers get in — watch", "The Branch Admin gives the link, dorm code and password; the viewer types them and sees the live board. Every check-in shows up on their page by itself.", null,
        {media:"viewers", demo:async D=>{ await D.playMedia(11500); }}),
      S(null, "Changing the password when linked to a Super Admin — watch", "You write a reason, the button shows Pending, the Super Admin approves in their Inbox, and the new password is set by itself. Everyone who joined must type the new password.", null,
        {media:"viewerpw", demo:async D=>{ await D.playMedia(13000); }}),
      S("#viewerAccessPanel .va-actions", "Change password — read this", "Changing the password removes everyone who joined; they must type the new password. If you are connected to a Super Admin, the change first needs their OK (you'll see a request), because their dorm view uses it."),
      S('#viewerAccessPanel [data-vasub="viewers"]', "Viewers", "Everyone who joined with the code and password. You can remove any of them."),
      // A-0087: watching who joined, blocking, and the Blocked list
      S(null, "Watching and blocking viewers — watch", "New viewers appear in the Viewers list with the time they joined. Block someone and they lose access at once and move to the Blocked list; Unblock lets them join again.", null,
        {media:"monitor", demo:async D=>{ await D.playMedia(11000); }}),
      S('#viewerAccessPanel [data-vasub="blocked"]', "Example: Blocked list", "People you removed and blocked can't join again until you unblock them. Watch.", null,
        {demo:async D=>{ await D.click('#viewerAccessPanel [data-vasub="blocked"]'); await D.wait(1200); await D.click('#viewerAccessPanel [data-vasub="viewers"]'); }})
    ],
    central:[
      S("#centralLinkPanel", "Central Link", "Connect your dorm to a Super Admin. Each permission is approved separately in the Inbox."),
      // A-0061 … A-0063
      S("#centralLinkPanel .cl-perm-row", "Permissions", "Directory = your dorm appears in their directory. Analytics = they see your occupancy over time. Room status = they can open your dorm view. Each one can be revoked any time."),
      S("#centralLinkPanel .cl-photo", "Dormitory picture", "Upload a photo of your dorm. It is shown on your card in the Super Admin dashboard."),
      S('#centralLinkPanel [data-cl="disconnect"]', "Disconnect", "Stops sharing everything with this Super Admin at once. You are asked first.")
    ],
    transfer:[
      // A-0064 / A-0065
      S("#transferPanel .panel", "Transfer my data", "For when someone takes over your dorm: write why, then Generate transfer code and give the code to the new account."),
      S("#transferPanel .panel + .panel, #transferPanel .panel:last-child", "Receive data", "The new account types the code here and presses Request transfer."),
      S(null, "How a transfer works — two accounts", "Watch the short animation: the old account on the left, the new account on the right.", null,
        {media:"transfer", demo:async D=>{ await D.playMedia(); }})
    ]
  },
  intro:{title:"Welcome to the Branch Admin", text:"A short, hands-on tour of this tab. “Watch” steps show an example on your screen without saving anything; “Try it” steps wait for you."}
};

const SUPER = {
  signOut:"#outBtn",
  below:".shell header.bar",   // same place as on Branch Admin: just below the top bar, on the right
  tab:()=>{ const b = $("#nav button.on"); return b ? b.dataset.tab : "overview"; },
  label:k=>{ const b = $('#nav button[data-tab="' + k + '"]'); return b ? b.textContent.replace(/\d+$/, "").trim() : k; },
  go:k=>{ const b = $('#nav button[data-tab="' + k + '"]'); if (b) b.click(); document.body.classList.remove("menu-open"); },
  tours:{
    overview:[
      S("#tab-overview .ov-stats", "Network totals", "All your connected dormitories added together. This row stays at the top while you scroll."),
      S("#tab-overview .ds-card", "One card per dormitory", "Its picture, the colour bar (blue occupied, green vacant, violet reserved, brown temporary, red overdue) and the summaries below it."),
      S("#tab-overview [data-up]", "Try it: upcoming vacancies", "Click this button to list the beds that will become vacant soon, with each tenant and check-out date.", "click"),
      S(".up-modal", "Upcoming vacancies", "Rooms and beds that empty within 7 days, with the room's details."),
      S(".up-modal [data-x]", "Try it: close", "Close this list to continue.", "click"),
      S('#tab-overview a[href^="viewer.html?branch"]', "View dorm", "Opens the dormitory as a read-only Dormitory Viewer — no dorm code or password needed, once its Branch Admin approved Room status.")
    ],
    dorms:[
      S("#reqName", "Your name", "The Branch Admin sees this name on the request: “by …”."),
      S("#pairCode", "Pairing code", "The Branch Admin creates this code in Central Link and gives it to you."),
      S("#connectBtn", "Send the request", "Sends a connection request. The Branch Admin approves Directory, Analytics and Room status separately."),
      S("#cards", "Connected dormitories", "Every dormitory you connected and the state of each permission.")
    ],
    trading:[
      S("#trMetric", "Try it: what to chart", "Choose what the chart shows, for example Vacant beds or Occupancy rate.", "change"),
      S("#trTf", "Time range", "1H to ALL: how far back to look. Custom picks your own dates."),
      S("#trRisk .risk-list", "Dormitory cards", "Each card is a dormitory with its risk level in plain words. Click a card to show only it; double-click to add more."),
      S("#trRisk [data-rc]", "Try it: pick a card", "Click this card. The chart now shows it.", "click"),
      S("#trKey", "Safe · Moderate · Risk", "Show every dormitory at one risk level with a single click."),
      S("#tab-trading .chartwrap", "The chart", "Left of NOW is what really happened; right of NOW is the forecast. The strip on the left is green Safe, yellow Normal, red Risk."),
      S("#tab-trading .tr-toolbar", "Move around", "Zoom, jump to a date, switch between line and candles."),
      S("#trHelp", "Try it: help", "Click the question mark for a full, simple explanation of this panel.", "click"),
      S(".hlp-modal [data-x]", "Try it: close", "Close the help to finish.", "click")
    ],
    inbox:[ S("#tab-inbox", "Inbox", "Branch Admins' answers and change requests arrive here.") ],
    accounts:[ S("#tab-accounts", "Accounts", "Super Admin accounts and Branch Admin requests.") ],
    server:[ S("#tab-server", "Server Details", "Your directory server: its code and password for Marketing viewers, who joined, and Remove / Block.") ],
    security:[ S("#tab-security", "Security", "A log of approvals, revocations and viewer changes.") ]
  },
  intro:{title:"Welcome, Super Admin", text:"A short hands-on tour of this tab. When a step says “Try it”, do it yourself to continue."}
};

const VIEWER = {
  signOut:"#vSignOut, #vBackViewers, #vThemeToggle",
  below:"header.v-top",       // same place as on Branch Admin: just below the top bar, on the right (A-0001)   // opened from the Marketing page there is no Sign out: use the next button
  single:true,   // one tutorial for the whole viewer (few tabs)
  tab:()=>"all", label:()=>"Dormitory Viewer", go:()=>{},
  tours:{all:[
    S("#vSticky", "Current statistics", "The live numbers for what you are looking at. They stay at the top while you scroll."),
    S(".v-filters", "Filters", "Narrow the rooms by status, room, gender, resident group or a search."),
    S("#vFilterStatus", "Try it: filter", "Choose a status, for example Vacant.", "change"),
    S('[data-v-view="vacancies"]', "Try it: Vacancies", "Click Vacancies to see every room as a card.", "click"),
    S("#vGrid .v-room", "Room cards", "Green cards still have space; blue cards are full. Each card lists its beds and dates, and its floor."),
    S('[data-v-view="hallway"]', "Try it: Hallway layout", "Click Hallway layout to see the floor map.", "click"),
    S("#vFloorBar", "Floors", "Switch floors here. Each floor has its own map."),
    S("#vHallwayCanvas .v-hall-room", "Try it: open a room", "Click a room on the map to see its beds.", "click"),
    S("#vSide", "Room information", "The same details as the room card. Click the room again or × to hide it."),
    S('[data-v-view="analytics"]', "Try it: Analytics", "Click Analytics for charts of the dorm's occupancy.", "click"),
    S("#vAnalyticsView", "Analytics", "How full the dorm is and what's coming up. Everything here is read-only.")
  ]},
  intro:{title:"Welcome to the Dormitory Viewer", text:"One quick hands-on tour of all three tabs. You can't change anything here, so try whatever you like."}
};

const MARKET = {
  signOut:"#outBtn",
  single:true,
  tab:()=>"all", label:()=>"Dormitory Directory", go:()=>{},
  tours:{all:[
    S("#stats", "The directory", "How many dormitories are listed, how many beds are free and in how many places. It stays at the top while you scroll."),
    S("#q", "Try it: search", "Type a dormitory name or a city.", "input"),
    S("#sort", "Try it: sort", "Sort by most vacancies or by name.", "change"),
    S("#filters", "Filters", "Show only dorms with free beds for men, women, students, reviewees, aircon and more."),
    S("#list .dc", "A dormitory", "Its location and free beds."),
    S("#list [data-open]", "Open it", "Opens the dormitory's live viewer page directly, no dorm code or password needed.")
  ]},
  intro:{title:"Welcome to the Dormitory Directory", text:"A quick hands-on tour. Steps marked “Try it” wait for you to do them."}
};

function pageConfig(){
  if ($("nav.tabs") && $("#signOutBtn")) return ADMIN;
  if ($("#trCanvas")) return SUPER;
  if ($(".v-board-tabs")) return VIEWER;
  if ($("#mkFreeze")) return MARKET;
  return null;
}

/* ------------------------------------------------------------------ the "?" button */
let fab = null;
function placeFab(){
  const cfg = pageConfig(), so = cfg && Array.from(document.querySelectorAll(cfg.signOut)).find(visible);
  if (!fab){
    fab = document.createElement("button");
    fab.type = "button"; fab.className = "vt-help-fab"; fab.textContent = "?";
    fab.setAttribute("aria-label", "Tutorial: learn this page step by step"); fab.title = "Tutorial — learn this page step by step";
    fab.addEventListener("click", ()=>start());
    document.body.appendChild(fab);
  }
  const ok = so && visible(so) && !run;
  fab.hidden = !ok;
  document.body.classList.toggle("vt-fab-below-bar", !!(ok && cfg.below));
  if (!ok) return;
  if (document.documentElement.clientWidth <= 640){
    // phone: bottom right, just above the assistant button, so it never covers the page's cards
    document.body.classList.remove("vt-fab-below-bar");
    fab.style.top = Math.round(innerHeight - 34 - 170) + "px";
    fab.style.left = Math.round(document.documentElement.clientWidth - 34 - 28) + "px";
    return;
  }
  const bar = cfg.below && document.querySelector(cfg.below);
  if (bar && visible(bar)){
    // frozen in place under the top bar: the strip below the top bar keeps an empty space on the right for it
    const b = bar.getBoundingClientRect();
    fab.style.top = Math.round(Math.max(0, b.bottom) + 14) + "px";
    fab.style.left = Math.round(document.documentElement.clientWidth - 34 - 18) + "px";
    return;
  }
  const r = so.getBoundingClientRect();
  fab.style.top = Math.round(r.bottom + 8) + "px";
  fab.style.left = Math.round(r.left + r.width / 2 - 17) + "px";
}
setInterval(placeFab, 600);
// A-0007 watchdog: if the tutorial window was removed or lost its caption, end the tutorial cleanly so the page is usable
setInterval(()=>{
  if (!run){ document.querySelectorAll(".vt-tut.out").forEach(n=>setTimeout(()=>n.remove(), 600)); return; }
  if (!document.body.contains(run.root)){ const r = run; run = null; try{ if (r.cfg.cleanup) r.cfg.cleanup(); }catch(e){} placeFab(); return; }
  const cap = run.root.querySelector(".vt-cap"), r = cap.getBoundingClientRect();
  if (r.bottom < 40 || r.top > innerHeight - 40){ cap.dataset.spot = "center"; }
  // a "Try it" step whose part disappeared: show Next so you can go on
  if (run.waiting && run.cleanup && !run.root.querySelector(".vt-try").hidden && run.root.classList.contains("no-target-now")){
    run.root.querySelector(".vt-next").hidden = false;
  }
}, 1000);
window.addEventListener("resize", placeFab);
window.addEventListener("scroll", placeFab, {passive:true});

/* ------------------------------------------------------------------ the tutorial itself */
let run = null;
/* ------------------------------------------------------------------ voice (text to speech)
   Every tutorial step is read aloud with the browser's own voice (free, no account): "Google US English" when the
   browser has it, the same voice the assistant uses. The speaker button in the tutorial box turns it off and on;
   the choice is remembered on this device. */
const tutVoice = (function(){
  const synth = window.speechSynthesis, KEY = "vtTutorialVoice", WANT = "Google US English";
  const can = !!(synth && window.SpeechSynthesisUtterance);
  let turn = 0;
  const on = ()=>{ try{ return localStorage.getItem(KEY) !== "off"; }catch(e){ return true; } };
  function pick(){                            // most human-sounding first: Edge "Natural", Google, then any US English
    const all = synth.getVoices(), en = v=>/^en[-_]US$/i.test(v.lang);
    return all.find(v=>en(v) && /natural/i.test(v.name) && /aria|jenny|ava|emma|michelle/i.test(v.name)) ||
      all.find(v=>en(v) && /natural/i.test(v.name)) ||
      all.find(v=>v.name === WANT) || all.find(v=>/google/i.test(v.name) && en(v)) ||
      all.find(v=>en(v) && /zira|samantha|female/i.test(v.name)) ||
      all.find(en) || all.find(v=>/^en/i.test(v.lang)) || null;
  }
  function ready(done){                       // Chrome adds its Google voices a moment after the page opens
    if (window.assistantVoice && window.assistantVoice.ready) return window.assistantVoice.ready(done);   // same voice as the assistant
    const v = pick();
    const chrome = /Chrome\//.test(navigator.userAgent) && !/Edg\//.test(navigator.userAgent) && !/Android/.test(navigator.userAgent);
    if ((v && v.name === WANT) || !chrome) return done(v);
    let finished = false;
    const fin = ()=>{ if (finished) return; finished = true; synth.removeEventListener("voiceschanged", fin); done(pick()); };
    synth.addEventListener("voiceschanged", fin); setTimeout(fin, 1500);
  }
  // The text as a person would say it: symbols become words, ranges and signs are read out, and nothing is
  // spelled letter by letter. The text on screen is not changed.
  const clean = t=>String(t || "")
    .replace(/\s*(→|->|⇒)\s*/g, ", then ")                       // "Single → name → details"
    .replace(/(\d+)\s*[–-]\s*(\d+)/g, "$1 to $2")                 // "4–10 days"
    .replace(/✓/g, " a check mark ").replace(/[✗✕×]/g, " a cross ")
    .replace(/\s+=\s+/g, " means ").replace(/≤/g, "within ").replace(/≥/g, "at least ")
    .replace(/‹\s*›/g, "arrow").replace(/[‹›]/g, " ")
    .replace(/(\d+(?:\.\d+)?)\s*%/g, "$1 percent").replace(/\s&\s/g, " and ")
    .replace(/\be\.g\.\s*/gi, "for example ").replace(/\bvs\.?(?=\s)/gi, "versus").replace(/\betc\./gi, "and so on.")
    .replace(/\b([A-Z]{4,})\b/g, w=>w.toLowerCase())             // "SLIDE" is said as a word, not spelled out
    .replace(/\b([A-Z])-(\d+)/g, "$1 $2")
    .replace(/[\u2190-\u21ff\u2600-\u27bf\u{1F300}-\u{1FAFF}]/gu, " ")
    .replace(/[“”"]/g, "").replace(/\s*(·|•|—|–)\s*/g, ", ")
    .replace(/\s*\(\s*/g, ", ").replace(/\s*\)\s*/g, " ")       // brackets become a short pause
    .replace(/\s+([.,;:!?])/g, "$1").replace(/([.,;:!?])\s*,/g, "$1").replace(/^[,\s]+/, "")
    .replace(/\s+/g, " ").trim();
  // a warm, clear pace close to normal speech (it was 1.2, which sounded rushed); the step title a touch slower and
  // brighter so it sounds like a heading; questions and exclamations lift a little at the end
  function tune(u, i, voice, titled){
    const natural = voice && /natural|google/i.test(voice.name);
    const heading = titled && i === 0;
    const q = /\?\s*$/.test(u.text), ex = /!\s*$/.test(u.text);
    u.rate = (natural ? 1.04 : 1.08) - (heading ? 0.06 : 0);
    u.pitch = (natural ? 1.06 : 1.14) + (heading ? 0.06 : 0) + (ex ? 0.06 : q ? 0.04 : 0);
    u.volume = 1;
  }
  function parts(text){                       // short pieces: Chrome's online voices stop after about 15 seconds
    const out = []; let cur = "";
    for (const p of text.split(/(?<=[.!?;:])\s+/)){ if ((cur + " " + p).length > 180 && cur){ out.push(cur); cur = p; } else cur = cur ? cur + " " + p : p; }
    if (cur) out.push(cur);
    return out.flatMap(c=>c.length > 220 ? c.match(/.{1,200}(\s|$)/g) : [c]);
  }
  return {
    can, on,
    stop(){ turn++; if (!can) return; if (window.VTSpeech) window.VTSpeech.stop(); else synth.cancel(); },
    set(v){ try{ localStorage.setItem(KEY, v ? "on" : "off"); }catch(e){} if (!v) this.stop(); },
    // title (optional) is said on its own first, like a heading, then the text
    speak(text, title){
      if (!can) return;
      this.stop();
      const my = turn;
      const head = clean(title).replace(/[.:!?]*$/, "");
      if (!on() || (!text && !head)) return;
      ready(v=>{
        if (my !== turn) return;
        const list = (head ? [head + (/[!?]$/.test(String(title).trim()) ? String(title).trim().slice(-1) : ".")] : []).concat(parts(clean(text)));
        const titled = !!head;
        const tuneIt = (u, i, voice)=>tune(u, i, voice, titled);
        if (window.VTSpeech) return window.VTSpeech.play(list, v, tuneIt, false);   // shared player (assistant.js)
        setTimeout(()=>{                                        // never speak() in the same moment as cancel()
          if (my !== turn) return;
          for (const part of list){
            const u = new SpeechSynthesisUtterance(part);
            if (v){ u.voice = v; u.lang = v.lang; } else u.lang = "en-US";
            tune(u); synth.speak(u);
          }
        }, 100);
      });
    }
  };
})();
const VOICE_ICON = {
  on:'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
  off:'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4z"/><path d="m16 9 6 6M22 9l-6 6"/></svg>'};
function paintVoiceBtn(root){
  const b = root.querySelector(".vt-voice"); if (!b) return;
  const on = tutVoice.on();
  b.innerHTML = VOICE_ICON[on ? "on" : "off"];
  b.setAttribute("aria-pressed", String(on));
  b.title = on ? "Voice is on. Click to turn the tutorial voice off" : "Voice is off. Click to hear the tutorial read aloud";
  b.setAttribute("aria-label", on ? "Turn the tutorial voice off" : "Turn the tutorial voice on");
}
// what the current step says, for the voice (title, then the text)
function speakStep(title, text){ tutVoice.speak(text || "", title); }

function build(){
  const root = document.createElement("div");
  root.className = "vt-tut"; root.setAttribute("role", "dialog"); root.setAttribute("aria-modal", "true"); root.setAttribute("aria-labelledby", "vtTutTitle");
  root.innerHTML = `<div class="vt-shade" data-p="t"></div><div class="vt-shade" data-p="l"></div><div class="vt-shade" data-p="r"></div><div class="vt-shade" data-p="b"></div>
    <div class="vt-ring"></div><div class="vt-block" title="During the tutorial only the part marked “Try it” can be used"></div>
    <svg class="vt-arrow" viewBox="0 0 64 64" aria-hidden="true"><path d="M32 4v44M14 30l18 20 18-20" fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/></svg>
    <div class="vt-ghosts"></div>
    <div class="vt-cursor" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 2l15 10-6.5 1.4L9.5 20z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg><i></i></div>
    <div class="vt-bar top"></div><div class="vt-bar bottom"></div>
    <div class="vt-cap"><div class="vt-cap-top"><span class="vt-step"></span><span class="vt-try" hidden>Try it</span><span class="vt-grow"></span><button type="button" class="vt-voice" hidden></button></div>
      <h3 id="vtTutTitle"></h3><p class="vt-text" aria-live="polite"></p><div class="vt-media" hidden></div>
      <div class="vt-cap-act"><button type="button" class="vt-back">Back</button><span class="vt-wait" hidden>Waiting for you…</span><button type="button" class="vt-replay" hidden>↻ Replay</button><button type="button" class="vt-skipstep" hidden>Skip this step</button><button type="button" class="vt-next">Next</button></div></div>
    <button type="button" class="vt-skip">Skip tutorial ›</button>`;
  document.body.appendChild(root);
  requestAnimationFrame(()=>root.classList.add("in"));
  root.querySelector(".vt-skip").onclick = ()=>stop();
  root.querySelector(".vt-next").onclick = ()=>next();
  root.querySelector(".vt-back").onclick = ()=>go(run.i - 1, -1);
  root.querySelector(".vt-replay").onclick = ()=>go(run.i, 1);
  root.querySelector(".vt-skipstep").onclick = ()=>next();
  const vb = root.querySelector(".vt-voice");
  vb.hidden = !tutVoice.can;
  paintVoiceBtn(root);
  vb.onclick = ()=>{
    tutVoice.set(!tutVoice.on()); paintVoiceBtn(root);
    if (tutVoice.on()) speakStep(root.querySelector("#vtTutTitle").textContent, root.querySelector(".vt-text").dataset.full || root.querySelector(".vt-text").textContent);
  };
  // clicks on the dimmed part do nothing (only the highlighted part and the caption react)
  // clicking outside shakes the tutorial box to point at it. The shake uses its own animation (the "translate"
  // property), so it never replaces the animation that keeps the box visible (that made the text vanish).
  root.querySelectorAll(".vt-shade").forEach(s=>s.addEventListener("click", e=>{
    e.stopPropagation();
    const cap = root.querySelector(".vt-cap");
    if (!cap || reduce || !cap.animate) return;
    cap.animate([{translate:"0 0"}, {translate:"-7px 0"}, {translate:"7px 0"}, {translate:"0 0"}], {duration:350, easing:"ease"});
  }));
  return root;
}
function start(key){
  const cfg = pageConfig(); if (!cfg || run) return;
  const k = key || cfg.tab();
  let steps = cfg.tours[k];
  if (!steps) steps = [S(null, cfg.label(k), "There is no tutorial for this tab yet.")];
  if (key && !cfg.single && key !== cfg.tab()) cfg.go(key);
  document.body.classList.remove("menu-open");
  run = {cfg, key:k, steps:[S(null, cfg.intro.title, cfg.intro.text + (cfg.single ? "" : " Tab: " + cfg.label(k) + "."))].concat(steps || []), i:-1, root:build(), cleanup:null, leave:null, raf:0, token:0, focusEl:null};
  placeFab();
  document.addEventListener("keydown", onKey, true);
  setTimeout(()=>go(0, 1), reduce ? 0 : 450);
}
function stop(){
  if (!run) return;
  const r = run;
  tutVoice.stop();
  r.token++;
  if (r.cleanup) r.cleanup();
  if (r.leave) try{ r.leave(); }catch(e){}
  cancelAnimationFrame(r.raf);
  run = null;
  try{ if (r.cfg.cleanup) r.cfg.cleanup(); }catch(e){}         // close anything a demo opened, reset filters
  const root = r.root; root.classList.remove("in"); root.classList.add("out");
  setTimeout(()=>root.remove(), reduce ? 0 : 400);
  document.removeEventListener("keydown", onKey, true);
  placeFab();
}
function onKey(e){
  if (!run) return;
  if (e.key === "Escape"){ e.preventDefault(); stop(); }
  else if (e.key === "Enter" && !run.waiting && document.activeElement && document.activeElement.closest && document.activeElement.closest(".vt-cap")){ e.preventDefault(); next(); }
}
function next(){ go(run.i + 1, 1); }
// A-0006: no scrolling or touching by hand while the tutorial runs (the tutorial scrolls for you); the caption still works
const inCap = t=>!!(t && t.closest && t.closest(".vt-cap, .vt-skip"));
const SCROLL_KEYS = ["ArrowUp","ArrowDown","PageUp","PageDown","Home","End"," ","Spacebar"];
window.addEventListener("wheel", e=>{ if (run && !inCap(e.target)) e.preventDefault(); }, {passive:false});
window.addEventListener("touchmove", e=>{ if (run && !inCap(e.target) && !(run.root.classList.contains("allow-hole") && !e.target.closest(".vt-tut"))) e.preventDefault(); }, {passive:false});
window.addEventListener("keydown", e=>{ if (run && SCROLL_KEYS.includes(e.key) && !inCap(e.target) && !(e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName))) e.preventDefault(); }, true);
function target(step){
  if (!step.sel) return null;
  const all = Array.from(document.querySelectorAll(step.sel));
  return all.find(visible) || null;
}
const pause = ms=>new Promise(r=>setTimeout(r, ms));
async function go(i, dir, again){        // again = the example is repeating: keep the text and the voice as they are
  if (!run) return;
  if (!again) tutVoice.stop();
  const token = ++run.token;
  if (run.cleanup){ run.cleanup(); run.cleanup = null; }
  if (run.leave){ const l = run.leave; run.leave = null; try{ l(); }catch(e){} }
  clearGhosts(); hideCursor(); run.focusEl = null;
  if (i < 0) i = 0;
  if (i >= run.steps.length) return finish();
  const step = run.steps[i];
  if (step.before){ try{ await step.before(); }catch(e){} await pause(reduce ? 60 : 380); if (!run || run.token !== token) return; }
  const el = target(step);
  if (step.sel && !el){ run.i = i; (run.skip = run.skip || new Set()).add(i); if (step.after) try{ step.after(); }catch(e){} return go(i + (dir || 1), dir || 1); }   // not on screen right now → skip it
  if (run.skip) run.skip.delete(i);
  run.i = i;
  if (step.after) run.leave = step.after;
  const root = run.root, cap = root.querySelector(".vt-cap");
  const shown = run.steps.slice(1).filter(s=>!s.sel || s.before || target(s)).length;
  const ord = i - (run.skip ? Array.from(run.skip).filter(k=>k < i).length : 0);
  run.total = Math.max(run.total || 0, shown - (run.skip ? run.skip.size : 0), ord);   // never jumps back down
  root.querySelector(".vt-step").textContent = i === 0 ? "Tutorial" : "Step " + ord + " of " + run.total;
  root.querySelector(".vt-back").hidden = i === 0;
  const act = step.act && el, watch = !!step.demo;
  root.classList.toggle("allow-hole", !!act);
  const tag = root.querySelector(".vt-try");
  tag.hidden = !(act || watch); tag.textContent = watch ? "Watch" : "Try it"; tag.classList.toggle("watch", watch);
  root.querySelector(".vt-next").hidden = !!act;          // on a "Watch" step Next is always there: the example repeats until it is pressed
  root.querySelector(".vt-replay").hidden = true;
  root.querySelector(".vt-wait").hidden = !(act || watch);
  root.querySelector(".vt-wait").textContent = watch ? "Example repeats until you press Next" : "Waiting for you…";
  cap.classList.toggle("compact", watch);                 // a smaller box, so it covers less of the example
  root.querySelector(".vt-next").textContent = i === run.steps.length - 1 ? "Finish" : i === 0 ? "Start" : "Next";
  root.querySelector(".vt-skipstep").hidden = !act;      // a "Try it" step can always be skipped
  root.querySelector("#vtTutTitle").textContent = step.title;
  root.classList.toggle("no-target", !el);
  const media = root.querySelector(".vt-media");
  media.hidden = !step.media; media.innerHTML = step.media ? MEDIA[step.media] || "" : "";
  cap.classList.toggle("wide", !!step.media);
  if (!again){
    cap.classList.remove("show"); void cap.offsetWidth; cap.classList.add("show");
    typeText(root.querySelector(".vt-text"), step.text);
    speakStep(step.title, step.text);
  }
  if (el){ el.scrollIntoView({block:"center", inline:"nearest", behavior:reduce ? "auto" : "smooth"}); }
  // follow the element while the page moves
  cancelAnimationFrame(run.raf);
  const loop = ()=>{ if (!run) return; const f = run.focusEl && visible(run.focusEl) ? run.focusEl : (el && visible(el) ? el : target(step)); run.root.classList.toggle("no-target-now", !!step.sel && !f); position(f); run.raf = requestAnimationFrame(loop); };
  loop();
  run.waiting = !!act;
  if (watch){
    const D = demoKit(token, !!again);
    if (!again) setTimeout(()=>{ const n = root.querySelector(".vt-next"); if (run && run.token === token && n && !n.hidden) n.focus({preventScroll:true}); }, 60);
    await pause(reduce ? 50 : 650);
    // a demo can never take longer than 25 seconds: after that Next appears anyway
    try{ if (run && run.token === token) await Promise.race([step.demo(D), pause(25000)]); }catch(e){ if (e && e.message !== "tut-stop") console.warn("tutorial demo", e); }
    if (!run || run.token !== token) return;
    hideCursor();
    run.focusEl = null;                     // back to the step's own part once the example is over
    // the example plays again and again until Next (or Back / Skip) is pressed
    await pause(reduce ? 2500 : 1600);
    if (!run || run.token !== token) return;
    return go(i, 1, true);
  } else if (act){
    const evt = step.act === "input" ? "input" : step.act === "change" ? "change" : "click";
    let t = null;
    const fire = ()=>{ clearTimeout(t); t = setTimeout(()=>{ if (run && run.i === i) next(); }, evt === "input" ? 900 : evt === "click" ? 450 : 350); };
    el.addEventListener(evt, fire, true);
    run.cleanup = ()=>{ el.removeEventListener(evt, fire, true); clearTimeout(t); };
  }else{
    setTimeout(()=>{ const n = root.querySelector(".vt-next"); if (run && n && !n.hidden) n.focus({preventScroll:true}); }, 60);
  }
}

/* ------------------------------------------------------------------ demos ("Watch" steps)
   A pretend mouse pointer moves, clicks and types on the real screen so you can see how it is done. Demos only
   open and close forms and switch views; they never press Save, Add, Delete or Check out. Previews of results are
   drawn on top of the page and disappear afterwards. */
function cursorEl(){ return run && run.root.querySelector(".vt-cursor"); }
function hideCursor(){ const c = cursorEl(); if (c) c.classList.remove("on"); }
function clearGhosts(){ if (run) run.root.querySelector(".vt-ghosts").innerHTML = ""; }
function demoKit(token, quiet){
  const alive = ()=>!!run && run.token === token;
  const chk = ()=>{ if (!alive()) throw new Error("tut-stop"); };
  const wait = ms=>pause(reduce ? Math.min(ms, 120) : ms).then(chk);
  const el = x=>!x ? null : typeof x === "string" ? (Array.from(document.querySelectorAll(x)).find(visible) || null) : x;
  const at = (x, y)=>{ const c = cursorEl(); if (!c) return; c.classList.add("on"); c.style.transform = "translate(" + Math.round(x) + "px," + Math.round(y) + "px)"; };
  const center = e=>{ const r = e.getBoundingClientRect(); return [r.left + Math.min(r.width / 2, 60), r.top + Math.min(r.height / 2, 22)]; };
  const ripple = ()=>{ const c = cursorEl(); if (!c) return; c.classList.remove("tap"); void c.offsetWidth; c.classList.add("tap"); };
  async function move(x){
    chk(); const e = el(x); if (!e) return null;
    const r0 = e.getBoundingClientRect();
    if (r0.top < 70 || r0.bottom > innerHeight - 40){ e.scrollIntoView({block:"center", behavior:reduce ? "auto" : "smooth"}); await wait(420); }
    at(...center(e)); await wait(620);
    return e;
  }
  async function click(x){ const e = await move(x); if (!e) return null; ripple(); await wait(160); e.click(); await wait(420); return e; }
  async function type(x, text){
    const e = await move(x); if (!e) return null; ripple(); e.focus({preventScroll:true}); e.value = "";
    e.dispatchEvent(new Event("input", {bubbles:true}));
    for (const ch of String(text)){ e.value += ch; e.dispatchEvent(new Event("input", {bubbles:true})); await wait(55); }
    e.dispatchEvent(new Event("change", {bubbles:true})); await wait(250); return e;
  }
  async function choose(x, value){
    const e = await move(x); if (!e) return null; ripple(); await wait(150);
    e.value = value; e.dispatchEvent(new Event("change", {bubbles:true})); e.dispatchEvent(new Event("input", {bubbles:true})); await wait(450); return e;
  }
  function focus(x){ if (run) run.focusEl = el(x); }
  function say(t){ if (run){ typeText(run.root.querySelector(".vt-text"), t); if (!quiet) tutVoice.speak(t); } }   // spoken the first time only
  // a preview card drawn over an element (removed when the step ends)
  function ghostOn(x, html, pos){
    const host = el(x); if (!host || !run) return null;
    const g = document.createElement("div"); g.className = "vt-ghost"; g.innerHTML = html;
    run.root.querySelector(".vt-ghosts").appendChild(g);
    const place = ()=>{ if (!g.isConnected) return; const r = host.getBoundingClientRect(); g.style.left = (r.left + r.width * (pos ? pos.x : 0.5)) + "px"; g.style.top = (r.top + r.height * (pos ? pos.y : 0.5)) + "px"; requestAnimationFrame(place); };
    place(); return g;
  }
  // a copy of an element glides to a place (another element, or dx/dy pixels) — a preview of dragging
  async function drag(from, to, label){
    const a = el(from); if (!a || !run) return;
    await move(a); ripple();
    const r = a.getBoundingClientRect();
    const g = a.cloneNode(true); g.removeAttribute("id"); g.className += " vt-drag-ghost";
    Object.assign(g.style, {left:r.left + "px", top:r.top + "px", width:r.width + "px", height:r.height + "px"});
    run.root.querySelector(".vt-ghosts").appendChild(g);
    let tx, ty, b = null;
    if (to && to.nodeType){ b = to; const rb = b.getBoundingClientRect(); tx = rb.left - r.left; ty = rb.top - r.top; b.classList.add("vt-drop-hint"); }
    else { tx = (to && to.dx) || 120; ty = (to && to.dy) || 60; }
    if (label){ const l = document.createElement("span"); l.className = "vt-drag-label"; l.textContent = label; g.appendChild(l); }
    await wait(120);
    g.style.transform = "translate(" + tx + "px," + ty + "px) rotate(-1.5deg)";
    at(...center(a).map((v, k)=>v + (k ? ty : tx)));
    await wait(1100);
    g.classList.add("vt-out"); if (b) b.classList.remove("vt-drop-hint");
    await wait(450);
  }
  // pretend to slide something left and right (the carousel)
  async function swipe(x){
    const e = await move(x); if (!e) return;
    const [cx, cy] = center(e); ripple();
    at(cx + 140, cy); await wait(500); at(cx - 140, cy); await wait(700); at(cx, cy); await wait(300);
  }
  async function slide(x, months){
    const e = el(x); if (!e) return;
    const r = e.getBoundingClientRect();
    const sx = r.left + r.width * (months < 0 ? 0.78 : 0.22), sy = r.top + r.height * 0.82;
    const step = Math.max(120, Math.min(190, e.clientWidth * 0.2)) * Math.abs(months) * (months < 0 ? -1 : 1);
    const fire = (type, px)=>e.dispatchEvent(new PointerEvent(type, {bubbles:true, cancelable:true, pointerId:77, pointerType:"mouse", button:0, buttons:type === "pointerup" ? 0 : 1, clientX:px, clientY:sy, isPrimary:true}));
    at(sx, sy); await wait(450); ripple();
    fire("pointerdown", sx);
    const n = 18;
    for (let k = 1; k <= n; k++){ const px = sx + step * k / n; fire("pointermove", px); at(px, sy); await pause(22); if (!alive()){ fire("pointerup", px); throw new Error("tut-stop"); } }
    fire("pointerup", sx + step);
    await wait(700);
  }
  async function playMedia(ms){
    const box = run && run.root.querySelector(".vt-media"); if (!box) return;
    const m = box.querySelector(".tr-anim");
    if (m){ m.classList.remove("play"); void m.offsetWidth; m.classList.add("play"); }
    // timed scenes: each [data-at] part appears at its second, [data-off] parts go away again
    const parts = Array.from(box.querySelectorAll("[data-at]"));
    parts.forEach(p=>p.classList.remove("on", "gone"));
    if (reduce){ parts.forEach(p=>{ if (!p.dataset.off) p.classList.add("on"); }); await wait(200); return; }
    const timers = [];
    parts.forEach(p=>{
      timers.push(setTimeout(()=>p.classList.add("on"), parseFloat(p.dataset.at) * 1000));
      if (p.dataset.off) timers.push(setTimeout(()=>p.classList.add("gone"), parseFloat(p.dataset.off) * 1000));
    });
    try{ await wait(ms || 9200); } finally { timers.forEach(clearTimeout); }
  }
  return {wait, move, click, type, choose, focus, say, ghostOn, drag, swipe, slide, playMedia, el, alive};
}

/* a short animation, shown inside the caption: how a data transfer works between two accounts (A-0065) */
const BEDS = (list)=>'<span class="md-beds">' + list.map(c=>'<i class="' + c + '"></i>').join("") + '</span>';
const MEDIA = {
  // A-0084 part 1: Branch Admin gives the code; the viewer joins and sees the board change live
  viewers:`<div class="md md-2">
    <div class="md-pane"><b>Branch Admin</b><small>Viewer Access</small>
      <div class="md-box" data-at="0.3">Dorm code <code>sample-dorm</code><br>Password <code>••••••••</code></div>
      <div class="md-msg" data-at="1.2">Sends link + code + password to the agent</div>
      <div class="md-box md-act" data-at="6.0">Checks in a new tenant: Room 203 · Bed 2</div></div>
    <div class="md-pane"><b>Viewer / marketing agent</b><small>viewer.html</small>
      <div class="md-input" data-at="2.4" data-off="5.0">Dorm code <span>sample-dorm</span></div>
      <div class="md-input" data-at="3.2" data-off="5.0">Password <span>••••••••</span></div>
      <div class="md-btn" data-at="3.9" data-off="5.0">Join</div>
      <div class="md-board" data-at="5.0">Room 203 ${BEDS(["o","v","o","o"])}</div>
      <div class="md-board md-upd" data-at="7.2">Room 203 ${BEDS(["o","o","o","o"])} <em>updated by itself</em></div>
      <div class="md-note" data-at="8.4">No names, no buttons — view only</div></div>
    <ol class="md-steps"><li data-at="0.3">Admin shares the code</li><li data-at="2.4">Viewer types it</li><li data-at="5.0">Live board opens</li><li data-at="6.0">Changes appear by themselves</li></ol></div>`,
  // A-0084 part 2: changing the password while linked to a Super Admin
  viewerpw:`<div class="md md-3">
    <div class="md-pane"><b>Branch Admin</b><small>Viewer Access</small>
      <div class="md-btn" data-at="0.3" data-off="2.4">Change password</div>
      <div class="md-box" data-at="1.0" data-off="3.4">Reason: <i>an agent left the company</i></div>
      <div class="md-btn md-wait" data-at="3.4" data-off="8.4">Pending approval…</div>
      <div class="md-box md-ok" data-at="8.4">New password set by itself ✓</div></div>
    <div class="md-pane"><b>Super Admin</b><small>Inbox</small>
      <div class="md-box" data-at="4.4">Sample Dorm wants to change the viewer password<br><i>Reason: an agent left the company</i></div>
      <div class="md-btn md-good" data-at="6.4">Accept</div></div>
    <div class="md-pane"><b>Viewer</b><small>viewer.html</small>
      <div class="md-board" data-at="0.3" data-off="9.2">Room 203 ${BEDS(["o","v","o","o"])}</div>
      <div class="md-box md-bad" data-at="9.2">Password changed — type the new one to join again</div></div>
    <ol class="md-steps"><li data-at="1.0">Write a reason</li><li data-at="3.4">Button shows Pending</li><li data-at="6.4">Super Admin accepts</li><li data-at="8.4">Done by itself</li></ol></div>`,
  // A-0087: monitoring and blocking
  monitor:`<div class="md md-2">
    <div class="md-pane"><b>Branch Admin</b><small>Viewers list</small>
      <div class="md-row" data-at="0.3">Ana Reyes <span>joined 9:02 AM</span></div>
      <div class="md-row" data-at="1.0" data-off="5.4">Unknown Person <span>joined 9:40 AM</span> <em class="md-btn md-mini" data-at="3.0">Block</em></div>
      <div class="md-row" data-at="1.6">Ben Cruz <span>joined 10:15 AM</span></div>
      <div class="md-tabs" data-at="5.8"><b>Blocked list (1)</b></div>
      <div class="md-row md-blocked" data-at="6.2">Unknown Person <em class="md-btn md-mini md-good" data-at="8.6">Unblock</em></div></div>
    <div class="md-pane"><b>The blocked person</b><small>viewer.html</small>
      <div class="md-board" data-at="0.3" data-off="5.4">Room 203 ${BEDS(["o","v","o","o"])}</div>
      <div class="md-box md-bad" data-at="5.4">Your access was removed by the dorm</div>
      <div class="md-note" data-at="6.6">They can't join again, even with the password</div>
      <div class="md-box md-ok" data-at="9.0">After Unblock they may join again</div></div>
    <ol class="md-steps"><li data-at="0.3">See who joined, and when</li><li data-at="3.0">Block a stranger</li><li data-at="5.8">They move to Blocked</li><li data-at="8.6">Unblock any time</li></ol></div>`,
  // A-0091: emergency
  emergency:`<div class="md md-2">
    <div class="md-pane"><b>11:40 PM</b><small>At the dorm</small>
      <div class="md-box md-bad" data-at="0.3">Luis (Room S-101, Bed 1) has a high fever</div>
      <div class="md-box" data-at="1.6">Staff takes him to the hospital</div>
      <div class="md-box md-ok" data-at="9.0">His mother is on the way to the hospital ✓</div></div>
    <div class="md-pane"><b>Branch Admin</b><small>Tenant Information</small>
      <div class="md-row" data-at="2.8">Room S-101 › <b>Luis Mercado</b></div>
      <div class="md-card" data-at="4.0"><b>Emergency card</b><span>Contact: 0919 962 3477</span><span>Home: 456 Bautista St., Iloilo City</span><span>Emergency: Maria Mercado (Mother) 0917 555 0142</span></div>
      <div class="md-call" data-at="6.0">📞 Calling Maria Mercado…</div></div>
    <ol class="md-steps"><li data-at="0.3">Something happens</li><li data-at="2.8">Open the tenant</li><li data-at="4.0">Emergency card</li><li data-at="6.0">Call the family</li></ol></div>`,
  transfer:`<div class="tr-anim" aria-label="Animation: the old account makes a code, the new account enters it, the old account approves, and the records move to the new account.">
    <div class="tr-acc old"><b>Old account</b><small>maria.old</small>
      <div class="tr-ui"><span class="tr-btn s1">Generate transfer code</span><span class="tr-code s2">K7QM-2XPA</span><span class="tr-req s4">Request from juan.new<em>Approve</em></span><span class="tr-done s6">Records sent ✓</span></div></div>
    <div class="tr-mid"><span class="tr-pack s5">24 rooms · 92 beds · history</span><span class="tr-codefly s3">K7QM-2XPA</span></div>
    <div class="tr-acc new"><b>New account</b><small>juan.new</small>
      <div class="tr-ui"><span class="tr-input s3">K7QM-2XPA</span><span class="tr-btn s3b">Request transfer</span><span class="tr-wait s4">Waiting for approval…</span><span class="tr-done s6">All data received ✓</span></div></div>
    <ol class="tr-steps"><li class="s1">Old account makes a code</li><li class="s3">New account types it</li><li class="s4">Old account approves</li><li class="s5">Everything moves over</li></ol>
  </div>`
};

let typing = 0;
function typeText(node, text){
  const my = ++typing;
  text = String(text || "");
  node.dataset.full = text;                    // the whole sentence, for the voice button
  if (reduce){ node.textContent = text; return; }
  node.textContent = ""; let k = 0;
  const tick = ()=>{ if (my !== typing) return; k = Math.min(text.length, k + 2); node.textContent = text.slice(0, k); if (k < text.length) setTimeout(tick, 16); };
  tick();
}
function position(el){
  const root = run.root, pad = 8, W = innerWidth, H = innerHeight;
  const sh = p=>root.querySelector('.vt-shade[data-p="' + p + '"]');
  const ring = root.querySelector(".vt-ring"), arrow = root.querySelector(".vt-arrow"), cap = root.querySelector(".vt-cap");
  if (!el || !visible(el)){
    Object.assign(sh("t").style, {left:0, top:0, width:W + "px", height:H + "px"});
    ["l","r","b"].forEach(p=>Object.assign(sh(p).style, {width:0, height:0}));
    ring.style.opacity = 0; arrow.style.opacity = 0;
    placeCap(cap, null);
    return;
  }
  const r = el.getBoundingClientRect();
  const x = Math.max(0, r.left - pad), y = Math.max(0, r.top - pad), x2 = Math.min(W, r.right + pad), y2 = Math.min(H, r.bottom + pad);
  Object.assign(sh("t").style, {left:0, top:0, width:W + "px", height:y + "px"});
  Object.assign(sh("b").style, {left:0, top:y2 + "px", width:W + "px", height:Math.max(0, H - y2) + "px"});
  Object.assign(sh("l").style, {left:0, top:y + "px", width:x + "px", height:Math.max(0, y2 - y) + "px"});
  Object.assign(sh("r").style, {left:x2 + "px", top:y + "px", width:Math.max(0, W - x2) + "px", height:Math.max(0, y2 - y) + "px"});
  Object.assign(ring.style, {left:x + "px", top:y + "px", width:(x2 - x) + "px", height:(y2 - y) + "px", opacity:1});
  Object.assign(root.querySelector(".vt-block").style, {left:x + "px", top:y + "px", width:(x2 - x) + "px", height:(y2 - y) + "px"});
  // arrow above the element (pointing down) or below it (pointing up); hidden for very big areas
  const above = y > 90, ax = Math.min(W - 40, Math.max(8, (x + x2) / 2 - 22));
  arrow.style.opacity = (y2 - y) > H * 0.7 ? 0 : 1;
  arrow.style.left = ax + "px";
  arrow.style.top = (above ? y - 62 : y2 + 10) + "px";
  arrow.classList.toggle("up", !above);
  placeCap(cap, {l:x, t:y, r:x2, b:y2});
}
/* The text box goes where it covers the least of what is being shown: the highlighted part, the pretend mouse pointer,
   the example previews and any open form. Eight places are tried (bottom, top, the four corners, left and right). */
const CAP_SPOTS = ["bottom", "top", "bl", "br", "tl", "tr", "ml", "mr"];
function placeCap(cap, hole){
  const W = innerWidth, H = innerHeight, root = run.root;
  const avoid = [];
  if (hole && (hole.r - hole.l) * (hole.b - hole.t) < W * H * 0.8) avoid.push(hole);
  const box = (e, grow)=>{ const q = e.getBoundingClientRect(); if (q.width > 1 && q.height > 1) avoid.push({l:q.left - grow, t:q.top - grow, r:q.right + grow, b:q.bottom + grow}); };
  const cur = root.querySelector(".vt-cursor.on"); if (cur) box(cur, 70);
  root.querySelectorAll(".vt-ghost").forEach(g=>box(g, 6));
  document.querySelectorAll(".modal-backdrop.open .modal, .wz-overlay.open .wz-card, .co-modal.open .co-card, #tiSidePanel.open").forEach(m=>{ if (!m.closest(".vt-tut")) box(m, 0); });
  if (!avoid.length){ setSpot(cap, hole ? "bottom" : "center"); return; }
  const cw = cap.offsetWidth || 520, ch = cap.offsetHeight || 190, m = 16, vy = Math.round(H * 0.055) + 18;
  const at = {bottom:[(W - cw) / 2, H - vy - ch], top:[(W - cw) / 2, vy], bl:[m, H - vy - ch], br:[W - m - cw, H - vy - ch], tl:[m, vy], tr:[W - m - cw, vy],
              ml:[m, (H - ch) / 2], mr:[W - m - cw, (H - ch) / 2]};
  const cost = k=>{ const [l, t] = at[k]; return avoid.reduce((sum, a)=>sum + Math.max(0, Math.min(l + cw, a.r) - Math.max(l, a.l)) * Math.max(0, Math.min(t + ch, a.b) - Math.max(t, a.t)), 0); };
  const now = cap.dataset.spot && at[cap.dataset.spot] ? cap.dataset.spot : null;
  let best = CAP_SPOTS[0], bc = Infinity;
  for (const k of (W < 760 ? ["bottom", "top"] : CAP_SPOTS)){ const c = cost(k); if (c < bc - 1){ best = k; bc = c; } }
  // stay where it is unless another place is clearly better (so the box does not jump around while the pointer moves)
  if (now && now !== best && cost(now) - bc < cw * ch * 0.12) best = now;
  setSpot(cap, best);
}
function setSpot(cap, spot){
  if (cap.dataset.spot === spot) return;
  cap.dataset.spot = spot;
}
function finish(){
  const cfg = run.cfg, root = run.root, cap = root.querySelector(".vt-cap");
  if (run.cleanup){ run.cleanup(); run.cleanup = null; }
  if (run.leave){ try{ run.leave(); }catch(e){} run.leave = null; }
  try{ if (cfg.cleanup) cfg.cleanup(); }catch(e){}
  clearGhosts(); hideCursor();
  cancelAnimationFrame(run.raf); position(null);
  run.i = run.steps.length; run.waiting = false;
  root.querySelector(".vt-step").textContent = "Done";
  root.querySelector(".vt-try").hidden = true;
  root.querySelector(".vt-media").hidden = true; cap.classList.remove("wide");
  root.querySelector("#vtTutTitle").textContent = "Well done!";
  const others = cfg.single ? [] : Object.keys(cfg.tours).filter(k=>k !== run.key);
  const doneText = cfg.single ? "You've seen everything on this page. Press ? any time to watch it again." : "You finished the " + cfg.label(run.key) + " tutorial. Pick another tab to learn, or close.";
  typeText(root.querySelector(".vt-text"), doneText);
  speakStep("Well done!", doneText);
  const act = root.querySelector(".vt-cap-act");
  act.innerHTML = (others.length ? `<div class="vt-more">${others.map(k=>`<button type="button" data-more="${esc(k)}">${esc(cfg.label(k))}</button>`).join("")}</div>` : "") + `<button type="button" class="vt-next vt-close">Close</button>`;
  act.querySelector(".vt-close").onclick = ()=>stop();
  act.querySelectorAll("[data-more]").forEach(b=>b.onclick = ()=>{ const k = b.dataset.more; stop(); setTimeout(()=>start(k), reduce ? 0 : 450); });
  cap.classList.remove("show"); void cap.offsetWidth; cap.classList.add("show");
}
window.VTTutorial = {start, stop};
})();
