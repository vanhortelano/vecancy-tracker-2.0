/* Viewer page: shared sign-in -> dorm code + password -> read-only views. */
(function(){
  const $ = id => document.getElementById(id);
  const SECTIONS = ["vConfigWarning","vSignIn","vJoin","vMessage","vBoard"];
  function show(name){
    SECTIONS.forEach(id=>{ $(id).hidden = id !== name; });
    $("vAuthShell").hidden = name !== "vSignIn" && name !== "vJoin";
  }
  function applyTheme(dark){
    document.body.classList.toggle("v-dark", dark);
    const label = dark ? "Switch to light mode" : "Switch to dark mode";
    $("vThemeToggle").setAttribute("aria-label", label);
    $("vThemeToggle").title = label;
    $("vThemeIcon").className = dark ? "fa-solid fa-sun" : "fa-solid fa-moon";
  }
  try{ applyTheme(localStorage.getItem("loginTheme") === "dark"); }
  catch(error){ applyTheme(false); }
  $("vThemeToggle").addEventListener("click", ()=>{
    const dark = !document.body.classList.contains("v-dark");
    applyTheme(dark);
    try{ localStorage.setItem("loginTheme", dark ? "dark" : "light"); }
    catch(error){ console.error("Could not save viewer theme", error); }
  });
  $("vPasswordToggle").addEventListener("click", ()=>{
    const input = $("vPassword");
    const visible = input.type === "password";
    input.type = visible ? "text" : "password";
    $("vPasswordToggle").setAttribute("aria-label", visible ? "Hide password" : "Show password");
    $("vPasswordToggle").innerHTML = `<i class="fa-regular ${visible ? "fa-eye-slash" : "fa-eye"}"></i>`;
  });
  const cfg = window.FIREBASE_CONFIG;
  if (!window.VT_LOCAL_MODE && (!cfg || cfg.apiKey === "YOUR_API_KEY")){ show("vConfigWarning"); return; }
  // Same app + tab-session storage as marketing.html, so a marketing viewer is already signed in here.
  const viaMarketing = new URLSearchParams(location.search).get("via") === "marketing";
  // Opened by a Super Admin with "View dorm": the Branch Admin approved "Room status & dorm view", so no dorm code
  // or password is needed. The server only returns the rooms to the Super Admin who sent that request.
  const branchUid = new URLSearchParams(location.search).get("branch");
  // One shared sign-in for every page (auth-ui.js); data comes from the SQL-backed API.
  let auth = null;
  const db = SQLSTORE.db;
  SQLSTORE.setTokenProvider(()=>VecancyAuth.token());
  if (viaMarketing){ $("vSignOut").hidden = true; $("vBackViewers").hidden = false; }

  let unsubViewerDoc = null, unsubVacancy = null, unsubLayout = null;
  let vacancyRooms = [];
  let selectedRoomId = null, activeView = "hallway", currentCode = null;
  let hallwayShapes = [], hallwayFloors = [], viewerFloor = null;   // floors: read-only floor view (feedback A-0022)
  let currentUser = null;
  let authStateGeneration = 0;

  function stopListening(){
    if (unsubViewerDoc) unsubViewerDoc();
    if (unsubVacancy) unsubVacancy();
    if (unsubLayout) unsubLayout();
    unsubViewerDoc = null;
    unsubVacancy = null;
    unsubLayout = null;
    vacancyRooms = [];
    hallwayShapes = []; hallwayFloors = []; viewerFloor = null;
    selectedRoomId = null;
    if (window.resetAssistantForUserChange && !currentUser) resetAssistantForUserChange();
  }

  function showEnded(title, text){
    stopListening();
    $("vMessageTitle").textContent = title;
    $("vMessageText").textContent = text;
    show("vMessage");
  }

  /* ---------------- sign in (shared login, see auth-ui.js) ---------------- */
  $("vSignOut").addEventListener("click", ()=>VecancyAuth.signOut());
  $("vSwitchServer").addEventListener("click",()=>{
    stopListening();
    $("vCode").value = "";
    $("vPassword").value = "";
    $("vJoinError").textContent = "";
    $("vJoin").querySelector("h2").textContent = "Switch server";
    $("vJoin").querySelector(":scope > p").textContent = "Enter the dorm code and password for another server you have access to.";
    show("vJoin");
    $("vCode").focus();
  });
  $("vBackToSignIn").addEventListener("click", ()=>VecancyAuth.signOut());
  $("vTryAgainBtn").addEventListener("click", ()=>{
    $("vJoinError").textContent = "";
    show("vJoin");
  });
  ["vCode","vPassword"].forEach(id=>{
    $(id).addEventListener("keydown", event=>{
      if (event.key === "Enter") $("vJoinBtn").click();
    });
  });

  VecancyAuth.init({
    mount: "#authMount",
    onSignedOut: ()=>{
      ++authStateGeneration;
      stopListening();
      currentUser = null;
      $("vUser").hidden = true;
      $("vSwitchServer").hidden = true;
      show("vSignIn");
    },
    onUser: user=>{
      const generation = ++authStateGeneration;
      stopListening();
      currentUser = user;
      $("vUser").hidden = false;
      $("vSwitchServer").hidden = false;
      $("vUserName").textContent = user.displayName || user.email || "";
      if (branchUid && /^[A-Za-z0-9_.\-]{1,64}$/.test(branchUid)){ $("vSwitchServer").hidden = true; startBranchBoard(user, branchUid); return; }
      // Opened from the Marketing Directory: the server already added this account as a viewer of that dorm.
      const directCode = viaMarketing ? normalizeDormCode(new URLSearchParams(location.search).get("code") || "") : "";
      if (directCode && isValidDormCode(directCode)){ $("vSignOut").hidden = true; startBoard(user, directCode); return; }
      if (generation === authStateGeneration && auth && auth.currentUser && auth.currentUser.uid === user.uid) show("vJoin");
      if (viaMarketing) $("vSignOut").hidden = true;
      // Coming from the marketing page: its pop-up already collected the dorm code + password.
      let pending = null;
      try{ pending = JSON.parse(sessionStorage.getItem("dormJoin") || "null"); sessionStorage.removeItem("dormJoin"); }catch(e){}
      if (viaMarketing && pending && pending.code && pending.password){
        $("vCode").value = pending.code; $("vPassword").value = pending.password;
        $("vJoinBtn").click();
      }
    }
  });
  auth = VecancyAuth.auth;

  /* ---------------- join ---------------- */
  $("vJoinBtn").addEventListener("click", async ()=>{
    const user = auth.currentUser;
    const error = $("vJoinError");
    error.textContent = "";
    if (!user) return;
    const code = normalizeDormCode($("vCode").value);
    const password = $("vPassword").value;
    if (!isValidDormCode(code) || !password){
      error.textContent = !code || !password
        ? "Enter the dorm code and password."
        : "Dorm codes must be 4–30 characters using letters, numbers, and dashes.";
      return;
    }
    const button = $("vJoinBtn");
    button.disabled = true;
    try{
      const viewerRef = db.collection("dorms").doc(code).collection("viewers").doc(user.uid);
      const proof = await viewerProof(code, password);
      if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
      const existing = await viewerRef.get();
      if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
      if (existing.exists && existing.data().proof !== proof){
        error.textContent = "That dorm code and password do not match. Check them with your administrator.";
        return;
      }
      if (!existing || !existing.exists){
        if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
        await viewerRef.set({
          proof,
          name: user.displayName || "",
          email: user.email || "",
          joinedAt: sqlServerTimestamp()
        });
      }
      if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
      $("vPassword").value = "";
      $("vJoin").querySelector("h2").textContent = "Enter your dorm details";
      $("vJoin").querySelector(":scope > p").textContent = "Use the exact code and password shared by your dorm administrator.";
      startBoard(user, code);
    }catch(err){
      if (err.code === "permission-denied"){
        // Not a dorm code: it may be a Super Admin server code. Join it and open the directory.
        try{
          const proof2 = await viewerProof(code, password);
          const ref = db.collection("centralAccess").doc(code).collection("viewers").doc(user.uid);
          const ex = await ref.get();
          if (!(ex.exists && ex.data().proof === proof2)){
            await ref.set({proof:proof2, name:user.displayName||"", email:user.email||"", joinedAt:sqlServerTimestamp()});
          }
          sessionStorage.setItem("centralCode", code);
          location.href = "marketing.html";
          return;
        }catch(e2){ /* wrong code/password for both server types */ }
      }
      console.error("Join failed", err);
      error.textContent = err.code === "permission-denied"
        ? "Could not join with those details. Check the code and password, or ask your admin if viewer access is enabled."
        : "Could not join: " + err.message;
    }finally{
      button.disabled = false;
    }
  });

  /* ---------------- vacancy board ---------------- */
  function startBoard(user, code){
    stopListening();
    show("vBoard");
    currentCode = code;
    let tab = "hallway";
    try{ tab = sessionStorage.getItem("vtViewerTab") || "hallway"; }catch(e){}
    setView(["vacancies","hallway","analytics"].includes(tab) ? tab : "hallway");   // land on the hallway map by default
    const dorm = db.collection("dorms").doc(code);
    unsubViewerDoc = dorm.collection("viewers").doc(user.uid).onSnapshot(snap=>{
      if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
      if (!snap.exists) showEnded("Access ended", "The admin removed your access. Ask them if you think this is a mistake.");
    }, ()=>{
      if (auth.currentUser && auth.currentUser.uid === user.uid) showEnded("Access ended", "You no longer have access to this dorm.");
    });
    unsubVacancy = dorm.collection("vacancy").onSnapshot(snap=>{
      if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
      vacancyRooms = snap.docs.map(d=>({id:d.id, ...d.data()}));
      renderBoard();
    }, err=>{
      if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
      if (err.code === "permission-denied") showEnded("Access ended", "The admin turned off viewer access or removed you.");
      else console.error("Vacancy listener failed", err);
    });
    unsubLayout = dorm.collection("layout").doc("public").onSnapshot(snap=>{
      if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
      hallwayShapes = snap.exists && Array.isArray(snap.data().shapes) ? snap.data().shapes : [];
      hallwayFloors = snap.exists && Array.isArray(snap.data().floors) ? snap.data().floors.filter(f=>f && f.id && f.name) : [];
      renderHallway();
    }, err=>{
      if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
      if (err.code === "permission-denied") showEnded("Access ended", "The admin turned off viewer access or removed you.");
      else console.error("Hallway layout listener failed", err);
    });
  }

  function startBranchBoard(user, uid){
    stopListening();
    show("vBoard");
    currentCode = null;
    setView("hallway");
    const branch = db.collection("branches").doc(uid);
    unsubViewerDoc = branch.onSnapshot(snap=>{
      if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
      const d = snap.exists ? snap.data() : null;
      if (!d || d.roomStatus !== "approved") return showEnded("Access ended", "The Branch Admin has not approved (or has revoked) Room status & dorm view for your Super Admin account.");
      document.title = (d.dormName || "Dormitory") + " — Dormitory Viewer";
      const bar = $("vSuperBar") || (()=>{ const el = document.createElement("div"); el.id = "vSuperBar"; el.className = "v-super-bar"; $("vBoard").prepend(el); return el; })();
      bar.innerHTML = '<i class="fa-solid fa-user-shield"></i> Super Admin view · <b></b> · read-only';
      bar.querySelector("b").textContent = d.dormName || "Dormitory";
    }, ()=>showEnded("Access ended", "You can't open this dormitory. Only the Super Admin it approved can, while Room status is approved."));
    unsubVacancy = branch.collection("rooms").onSnapshot(snap=>{
      if (!auth.currentUser || auth.currentUser.uid !== user.uid) return;
      const list = []; let layout = null;
      snap.docs.forEach(d=>{ let r = {}; try{ r = JSON.parse(d.data().room || "{}"); }catch(e){}
        if (d.id === "__layout") layout = r; else list.push({id:d.id, ...r, beds:(r.bedInfo || []).map(b=>VTCore.bedStatus(b, {tenancyMode:r.tenancyMode, beds:r.bedInfo}))}); });
      vacancyRooms = list;
      hallwayShapes = layout && Array.isArray(layout.shapes) ? layout.shapes : [];
      hallwayFloors = layout && Array.isArray(layout.floors) ? layout.floors.filter(f=>f && f.id && f.name) : [];
      renderBoard(); renderHallway();
    }, err=>{
      if (err.code === "permission-denied") showEnded("Access ended", "The Branch Admin has not approved (or has revoked) Room status & dorm view.");
      else console.error("Room status listener failed", err);
    });
  }

  /* ---------------- shared filter + statistics (vacancy-core.js) ----------------
     One filter state drives every view: Vacancies, Hallway, Analytics, the sticky statistics panel and the
     assistant. Every count comes from VTCore, the same rules the Branch Admin uses. */
  const FILTER_IDS = {status:"vFilterStatus", gender:"vFilterGender", demographic:"vFilterDemographic", room:"vFilterRoom", search:"vFilterSearch"};
  function filters(){
    const f = {};
    Object.entries(FILTER_IDS).forEach(([k,id])=>{ f[k] = k === "search" ? $(id).value.trim() : $(id).value; });
    return f;
  }
  function saveFilters(){ try{ sessionStorage.setItem("vtViewerFilters", JSON.stringify(filters())); }catch(e){} }
  function restoreFilters(){
    try{
      const f = JSON.parse(sessionStorage.getItem("vtViewerFilters") || "null");
      if (f) Object.entries(FILTER_IDS).forEach(([k,id])=>{ if (f[k] !== undefined && k !== "room") $(id).value = f[k]; });
      restoreFilters.room = f && f.room;
    }catch(e){}
  }
  const sortRooms = list => list.slice().sort((a,b)=>String(a.room).localeCompare(String(b.room), undefined, {numeric:true}));
  function roomInfo(room){ const beds = VTCore.bedStates(room); return {room, beds, sum:VTCore.summarize(beds)}; }
  function filteredRooms(){
    const f = filters();
    return sortRooms(vacancyRooms).filter(room=>{
      if (!VTCore.roomMatches(room, f)) return false;
      const s = VTCore.summarize(VTCore.bedStates(room));
      if (f.status === "vacant") return s.vacant > 0;
      if (f.status === "full") return s.vacant === 0;
      if (f.status === "upcoming") return s.upcoming > 0;
      return true;
    });
  }

  const pct = n => (Math.round(n * 10) / 10) + "%";
  function legendHtml(){
    return VTCore.ORDER.map(k=>`<span><i class="${k}"></i>${esc(VTCore.STATUS[k].label)}</span>`).join("") +
      `<span><i class="upcoming"></i>Upcoming vacancy (check-out within ${VTCore.UPCOMING_DAYS} days, still occupied)</span>`;
  }
  function bedRowHtml(b){
    const dates = [];
    if (b.status === "reserved" && b.reservedFrom) dates.push(`<span>Reserved from: ${esc(VTCore.fmtDate(b.reservedFrom))}</span>`);
    if (b.start) dates.push(`<span>Check-in: ${esc(VTCore.fmtDate(b.start))}</span>`);
    if (b.end) dates.push(`<span>${b.upcoming ? "Current check-out" : "Check-out"}: ${esc(VTCore.fmtDate(b.end))}</span>`);
    return `<li class="v-bed status-${b.status}${b.upcoming ? " is-upcoming" : ""}">
      <div class="v-bed-top"><b>${esc(b.slot)}</b><span class="v-bed-pill ${b.status}">${esc(VTCore.STATUS[b.status].label)}</span>${b.upcoming ? `<span class="v-bed-pill upcoming">Upcoming vacancy</span>` : ""}</div>
      ${dates.length ? `<div class="v-bed-dates">${dates.join("")}</div>` : ""}</li>`;
  }
  function roomCardHtml(info, opts={}){
    const {room, beds, sum} = info;
    return `<article class="v-room ${sum.vacant ? "has-vacancy" : "is-full"}${opts.side ? " v-room-side" : ""}" data-room-id="${esc(room.id)}">
      <header class="v-room-head"><h3>ROOM ${esc(room.room)}</h3>${opts.side ? `<button type="button" class="v-side-close" data-side-close aria-label="Close room information">&times;</button>` : `<span class="v-pill ${sum.vacant ? "vacant" : "full"}">${sum.vacant ? sum.vacant + " vacant" : "Full"}</span>`}</header>
      <div class="v-meta">${room.floor ? `<span class="v-floor-tag"><i class="fa-solid fa-layer-group" aria-hidden="true"></i> ${esc(room.floor)}</span>` : ""}${esc(room.gender || "Mixed")} · ${esc(room.demographic || "Mixed")}${room.tenancyMode === "Whole Room" ? " · Whole room" : ""}</div>
      <dl class="v-room-sum">
        <div><dt>Total beds</dt><dd>${sum.total}</dd></div>
        <div class="occupied"><dt>Occupied</dt><dd>${sum.occupied}</dd></div>
        <div class="vacant"><dt>Vacant</dt><dd>${sum.vacant}</dd></div>
        ${sum.upcoming ? `<div class="upcoming"><dt>Upcoming vacancies</dt><dd>${sum.upcoming}</dd></div>` : ""}
        ${sum.reserved ? `<div class="reserved"><dt>Reserved</dt><dd>${sum.reserved}</dd></div>` : ""}
        ${sum.overdue ? `<div class="overdue"><dt>Overdue</dt><dd>${sum.overdue}</dd></div>` : ""}
      </dl>
      <h4 class="v-beds-title">${opts.side ? "INDIVIDUAL BEDS" : "Beds"}</h4>
      <ul class="v-beds">${beds.map(bedRowHtml).join("") || `<li class="v-bed"><span class="v-meta">No beds published.</span></li>`}</ul>
    </article>`;
  }

  function renderSticky(f, st){
    const label = VTCore.scopeLabel(f, vacancyRooms);
    $("vSticky").innerHTML = `<div class="v-sticky-scope"><span>CURRENT STATISTICS</span><b>${esc(label.toUpperCase())}</b></div>
      <div class="v-sticky-nums">
        <span><b>${st.total}</b>Total beds</span>
        <span class="occupied"><b>${st.occupied}</b>Occupied</span>
        <span class="vacant"><b>${st.vacant}</b>Vacant</span>
        <span class="upcoming"><b>${st.upcoming}</b>Upcoming vacancies</span>
        ${st.reserved ? `<span class="reserved"><b>${st.reserved}</b>Reserved</span>` : ""}
        ${st.overdue ? `<span class="overdue"><b>${st.overdue}</b>Overdue</span>` : ""}
        <span><b>${pct(st.occupancyRate)}</b>Occupancy</span>
      </div>`;
    $("vFilterReset").hidden = label === "All";
  }

  function renderBoard(){
    const sorted = sortRooms(vacancyRooms);
    // room filter options follow the published rooms
    const roomSel = $("vFilterRoom"), want = roomSel.value !== "all" ? roomSel.value : (restoreFilters.room || "all");
    roomSel.innerHTML = `<option value="all">Every room</option>` + sorted.map(r=>`<option value="${esc(r.id)}">Room ${esc(r.room)}</option>`).join("");
    roomSel.value = sorted.some(r=>r.id === want) ? want : "all";
    if (sorted.length) restoreFilters.room = null;
    const f = filters(), st = VTCore.stats(vacancyRooms, f);
    renderSticky(f, st);
    $("vLegend").innerHTML = legendHtml();
    $("vSummary").innerHTML =
      `<div class="v-stat good"><b>${st.vacant}</b><span>Vacant beds</span></div>` +
      `<div class="v-stat good"><b>${st.roomsWithSpace}</b><span>Rooms with space</span></div>` +
      `<div class="v-stat"><b>${st.rooms - st.roomsWithSpace}</b><span>Full rooms</span></div>`;
    const list = filteredRooms();
    $("vGrid").innerHTML = list.length ? list.map(r=>roomCardHtml(roomInfo(r))).join("")
      : `<div class="v-empty">${vacancyRooms.length ? "No rooms match this filter." : "The admin hasn't published any rooms yet."}</div>`;
    renderHallway();
    renderAnalytics(list, st);
    renderSide();
    $("vUpdated").textContent = "Live — updates automatically when the admin changes a room. Statuses are recalculated every minute.";
    saveFilters();
  }

  function renderHallway(){
    // Same geometry and bed colours as the Branch Admin Hallway Layout (118x70 tiles). Filters dim, never hide, tiles.
    const canvas = $("vHallwayCanvas");
    // floors: one map per floor, like the Branch Admin (read-only here)
    const floorIds = hallwayFloors.map(f=>f.id), roomFloor = r=>floorIds.includes(r.floorId) ? r.floorId : "__none";
    if (hallwayFloors.length && (!viewerFloor || (viewerFloor !== "__none" && !floorIds.includes(viewerFloor)))) viewerFloor = hallwayFloors[0].id;
    if (!hallwayFloors.length) viewerFloor = null;
    const bar = $("vFloorBar");
    if (bar){
      const none = vacancyRooms.filter(r=>roomFloor(r) === "__none").length;
      bar.hidden = !hallwayFloors.length;
      bar.innerHTML = hallwayFloors.length ? `<span class="v-floor-lbl"><i class="fa-solid fa-layer-group" aria-hidden="true"></i> Floor</span>` + hallwayFloors.map(f=>{
        const n = vacancyRooms.filter(r=>r.floorId === f.id).length;
        return `<button type="button" class="v-floor-chip${viewerFloor === f.id ? " on" : ""}" data-vfloor="${esc(f.id)}" aria-pressed="${viewerFloor === f.id}">${esc(f.name)} <small>${n} room${n === 1 ? "" : "s"}</small></button>`;
      }).join("") + (none ? `<button type="button" class="v-floor-chip${viewerFloor === "__none" ? " on" : ""}" data-vfloor="__none">No floor <small>${none}</small></button>` : "") : "";
    }
    const onFloor = item=>!viewerFloor || (floorIds.includes(item.floorId) ? item.floorId : "__none") === viewerFloor;
    const rooms = vacancyRooms.filter(onFloor);
    const shown = new Set(filteredRooms().map(r=>r.id));
    const roomWidth = 118, roomHeight = 70;
    const shapes = hallwayShapes.filter(shape=>shape && typeof shape.label === "string" && onFloor(shape)).map(shape=>{
      const geometry = ["rectangle","circle","triangle"].includes(shape.geometry) ? shape.geometry : "rectangle";
      let w = safeSize(shape.width,160), h = safeSize(shape.height,100);
      if (geometry === "circle") w = h = Math.max(w,h);
      return {...shape, geometry, w, h};
    });
    const maxX = Math.max(800,...rooms.map(r=>safePosition(r.x)+roomWidth+24),...shapes.map(s=>safePosition(s.x)+s.w+24));
    const maxY = Math.max(420,...rooms.map(r=>safePosition(r.y)+roomHeight+24),...shapes.map(s=>safePosition(s.y)+s.h+24));
    canvas.style.width = `${Math.min(maxX,5000)}px`;
    canvas.style.height = `${Math.min(maxY,3000)}px`;
    const roomTiles = rooms.map(room=>{
      const {beds, sum} = roomInfo(room);
      const dots = beds.map(b=>`<span class="${b.status}${b.upcoming ? " upcoming" : ""}"></span>`).join("");
      const sel = room.id === selectedRoomId;
      return `<div class="v-hall-room ${sum.vacant ? "has-vacancy" : "is-full"}${shown.has(room.id) ? "" : " filtered-out"}${sel ? " is-selected" : ""}" data-hall-room="${esc(room.id)}" tabindex="0" role="button" aria-pressed="${sel}" style="left:${safePosition(room.x)}px;top:${safePosition(room.y)}px" aria-label="Room ${esc(room.room)}, ${sum.vacant} vacant. Show room information">
        <strong>${esc(room.room)}</strong>
        <em>${esc(room.gender||"Mixed")} · ${sum.vacant} vacant</em>
        <div class="v-hall-dots">${dots}</div>
      </div>`;
    }).join("");
    const shapeTiles = shapes.map(shape=>{
      const kind = shape.kind === "walkway" ? "walkway" : "facility";
      const color = /^#[0-9a-f]{6}$/i.test(shape.color||"") ? shape.color : "#dce8e4";
      const rotation = Number.isFinite(Number(shape.labelRotation)) ? Number(shape.labelRotation) : 0;
      return `<div class="v-hall-shape ${kind} geometry-${shape.geometry}" style="left:${safePosition(shape.x)}px;top:${safePosition(shape.y)}px;width:${shape.w}px;height:${shape.h}px;--shape-color:${color}" aria-label="${esc(shape.label)}"><span style="transform:rotate(${rotation}deg)">${esc(shape.label)}</span></div>`;
    }).join("");
    canvas.innerHTML = roomTiles + shapeTiles || `<p class="v-empty">The admin hasn't published a hallway layout yet.</p>`;
  }

  document.addEventListener("click", e=>{
    const b = e.target.closest && e.target.closest("[data-vfloor]"); if (!b) return;
    viewerFloor = b.dataset.vfloor; renderHallway();
  });
  // Side room-information card (hallway map). Same card and the same data as the Vacancies section.
  function renderSide(){
    const side = $("vSide");
    const room = selectedRoomId && vacancyRooms.find(r=>r.id === selectedRoomId);
    if (!room || activeView !== "hallway"){ side.hidden = true; side.innerHTML = ""; $("vHallwayView").classList.remove("with-side"); return; }
    side.innerHTML = `<p class="v-side-eyebrow">ROOM INFORMATION</p>` + roomCardHtml(roomInfo(room), {side:true});
    side.hidden = false;
    $("vHallwayView").classList.add("with-side");
  }
  function selectRoom(id){
    selectedRoomId = id && id !== selectedRoomId ? id : null;     // same room again = hide
    document.querySelectorAll("[data-hall-room]").forEach(t=>{ const on = t.dataset.hallRoom === selectedRoomId; t.classList.toggle("is-selected", on); t.setAttribute("aria-pressed", String(on)); });
    renderSide();
  }
  $("vHallwayCanvas").addEventListener("click", e=>{
    const tile = e.target.closest("[data-hall-room]");
    if (tile) selectRoom(tile.dataset.hallRoom);
    else if (selectedRoomId) selectRoom(null);                   // empty part of the map closes the card
  });
  $("vHallwayCanvas").addEventListener("keydown", e=>{
    const tile = e.target.closest && e.target.closest("[data-hall-room]");
    if (tile && (e.key === "Enter" || e.key === " ")){ e.preventDefault(); selectRoom(tile.dataset.hallRoom); }
  });
  $("vSide").addEventListener("click", e=>{ if (e.target.closest("[data-side-close]")) selectRoom(null); });
  document.addEventListener("keydown", e=>{ if (e.key === "Escape" && selectedRoomId && !document.querySelector("#assistantPanel:not([hidden])")) selectRoom(null); });
  document.addEventListener("click", e=>{
    if (!selectedRoomId || activeView !== "hallway") return;
    if (e.target.closest("#vSide,#vHallwayCanvas,.assistant-widget,.v-filters,.v-board-tabs,.v-top")) return;
    selectRoom(null);
  });

  function barRows(entries){
    // entries: [[label, {vacant, occupied, reserved, total}]] -> stacked status bars
    const max = Math.max(1, ...entries.map(([,c])=>c.total));
    return entries.map(([label,c])=>`<div class="v-bar-row v-stack"><span>${esc(label)}</span><div style="width:${c.total / max * 100}%">${
      [["occupied",c.occupied],["reserved",c.reserved],["vacant",c.vacant]].filter(([,n])=>n>0).map(([k,n])=>`<i class="${k}" style="flex:${n}" title="${VTCore.STATUS[k].label}: ${n}"></i>`).join("")}</div><b>${c.total}</b></div>`).join("");
  }
  function renderAnalytics(list, st){
    $("vAnalyticsStats").innerHTML =
      `<div class="v-stat"><b>${pct(st.occupancyRate)}</b><span>Occupancy rate</span></div>`+
      `<div class="v-stat"><b>${st.total}</b><span>Total beds</span></div>`+
      `<div class="v-stat occupied"><b>${st.occupied}</b><span>Occupied beds</span></div>`+
      `<div class="v-stat good"><b>${st.vacant}</b><span>Vacant beds</span></div>`+
      `<div class="v-stat upcoming"><b>${st.upcoming}</b><span>Upcoming vacancies (${VTCore.UPCOMING_DAYS} days)</span></div>`+
      `<div class="v-stat reserved"><b>${st.reserved}</b><span>Reserved beds</span></div>`;
    const infos = list.map(roomInfo);
    // status bar for the whole scope
    const parts = VTCore.ORDER.map(k=>[k, infos.reduce((n,i)=>n + i.beds.filter(b=>b.status === k).length, 0)]).filter(([,n])=>n);
    $("vStatusBar").innerHTML = st.total ? `<div class="v-statusbar">${parts.map(([k,n])=>`<i class="${k}" style="flex:${n}" title="${VTCore.STATUS[k].label}: ${n}"></i>`).join("")}</div>
      <div class="v-statusbar-key">${parts.map(([k,n])=>`<span><i class="${k}"></i>${esc(VTCore.STATUS[k].label)} <b>${n}</b> (${pct(n / st.total * 100)})</span>`).join("")}</div>` : `<p class="v-empty">No beds in this scope.</p>`;
    // upcoming vacancies + scheduled check-ins (dates only, no names)
    const now = Date.now();
    const ups = infos.flatMap(i=>i.beds.filter(b=>["occupied","soon","temporary"].includes(b.status) && b.end && VTCore.parseDate(b.end, true) > now).map(b=>({room:i.room.room, slot:b.slot, at:VTCore.parseDate(b.end, true), raw:b.end, upcoming:b.upcoming})))
      .sort((a,b)=>a.at - b.at);
    $("vUpcomingList").innerHTML = ups.length ? `<ul class="v-datelist">${ups.slice(0,12).map(u=>`<li class="${u.upcoming ? "upcoming" : ""}"><b>${esc(VTCore.fmtDate(u.raw))}</b><span>Room ${esc(u.room)} · ${esc(u.slot)}${u.upcoming ? " · within " + VTCore.UPCOMING_DAYS + " days" : ""}</span></li>`).join("")}</ul>${ups.length > 12 ? `<p class="v-meta">and ${ups.length - 12} more later.</p>` : ""}` : `<p class="v-empty">No scheduled check-outs in this scope.</p>`;
    const ins = infos.flatMap(i=>i.beds.filter(b=>b.status === "reserved").map(b=>({room:i.room.room, slot:b.slot, raw:b.reservedFrom || b.start}))).filter(x=>x.raw).sort((a,b)=>VTCore.parseDate(a.raw) - VTCore.parseDate(b.raw));
    $("vCheckinList").innerHTML = ins.length ? `<ul class="v-datelist">${ins.slice(0,12).map(u=>`<li class="reserved"><b>${esc(VTCore.fmtDate(u.raw))}</b><span>Room ${esc(u.room)} · ${esc(u.slot)}</span></li>`).join("")}</ul>` : `<p class="v-empty">No reserved check-ins in this scope.</p>`;
    // vacant beds by room
    const vacByRoom = infos.filter(i=>i.sum.vacant > 0).sort((a,b)=>b.sum.vacant - a.sum.vacant);
    const maxV = Math.max(1, ...vacByRoom.map(i=>i.sum.vacant));
    $("vVacancyBars").innerHTML = vacByRoom.length ? vacByRoom.map(i=>`<div class="v-bar-row"><span>Room ${esc(i.room.room)}</span><div><i class="vacant" style="width:${i.sum.vacant / maxV * 100}%"></i></div><b>${i.sum.vacant}</b></div>`).join("")
      : `<p class="v-empty">No vacant beds in this scope.</p>`;
    const group = key=>{ const m = {}; infos.forEach(i=>{ const k = i.room[key] || "Mixed"; m[k] = m[k] || {vacant:0, occupied:0, reserved:0, total:0}; ["vacant","occupied","reserved","total"].forEach(x=>m[k][x] += i.sum[x]); }); return Object.entries(m); };
    $("vGenderBars").innerHTML = infos.length ? barRows(group("gender")) : `<p class="v-empty">No rooms in this scope.</p>`;
    $("vDemographicBars").innerHTML = infos.length ? barRows(group("demographic")) : `<p class="v-empty">No rooms in this scope.</p>`;
    // next 30 days: occupied beds at noon of each day, from the published check-in / check-out dates
    const days = Array.from({length:30}, (_,d)=>{ const t = new Date(); t.setHours(12,0,0,0); t.setDate(t.getDate() + d); return t.getTime(); });
    const occAt = t=>infos.reduce((n,i)=>n + (Array.isArray(i.room.bedInfo) && i.room.bedInfo.length
      ? i.room.bedInfo.filter(b=>VTCore.occupiedAt(b, t)).length : i.sum.occupied), 0);
    const series = days.map(t=>({t, n:occAt(t)})), maxO = Math.max(1, st.total);
    $("vTimeline").innerHTML = st.total ? `<div class="v-timeline">${series.map(p=>`<span title="${new Date(p.t).toLocaleDateString([], {month:"short", day:"numeric"})}: ${p.n} occupied, ${st.total - p.n} free of ${st.total}"><i class="vacant" style="flex:${st.total - p.n}"></i><i class="occupied" style="flex:${p.n}"></i></span>`).join("")}</div>
      <div class="v-statusbar-key"><span><i class="occupied"></i>Occupied (scheduled)</span><span><i class="vacant"></i>Free</span></div>
      <div class="v-timeline-axis"><span>Today</span><span>${new Date(days[29]).toLocaleDateString([], {month:"short", day:"numeric"})}</span></div>
      <p class="v-meta">Uses only scheduled dates: a bed stays occupied until its check-out date; reservations count from their check-in date. Tenants who stay past check-out are still counted until the admin checks them out.</p>` : "";
  }

  function safePosition(value){
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0,Math.min(5000,number)) : 20;
  }

  function safeSize(value,fallback){
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(36,Math.min(2000,number)) : fallback;
  }

  function safeCount(value){
    const number = Number(value);
    return Number.isFinite(number) ? Math.max(0,number) : 0;
  }

  function esc(value){
    return String(value==null?"":value).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  }

  ["vFilterStatus","vFilterGender","vFilterDemographic","vFilterRoom"].forEach(id=>$(id).addEventListener("change",renderBoard));
  $("vFilterSearch").addEventListener("input",renderBoard);
  $("vFilterReset").addEventListener("click",()=>{ Object.values(FILTER_IDS).forEach(id=>{ $(id).value = id === "vFilterSearch" ? "" : "all"; }); renderBoard(); });
  restoreFilters();
  setInterval(()=>{ if (!$("vBoard").hidden && vacancyRooms.length) renderBoard(); }, 60000);   // "soon" / "overdue" / upcoming follow the clock
  function setView(view){
    activeView = view;
    document.querySelectorAll("[data-v-view]").forEach(tab=>{
      const active = tab.dataset.vView === view;
      tab.classList.toggle("active",active);
      tab.setAttribute("aria-pressed",String(active));
    });
    $("vVacanciesView").hidden = view !== "vacancies";
    $("vHallwayView").hidden = view !== "hallway";
    $("vAnalyticsView").hidden = view !== "analytics";
    renderSide();
    try{ sessionStorage.setItem("vtViewerTab", view); }catch(e){}
  }
  document.querySelectorAll("[data-v-view]").forEach(button=>button.addEventListener("click",()=>setView(button.dataset.vView)));

  /* ---------------- assistant (same widget as the admin pages; never on the sign-in / Home screen) ---------------- */
  const VIEW_LABEL = {vacancies:"Vacancies", hallway:"Hallway layout", analytics:"Analytics"};
  window.VT_AI_PAGE = {page:"viewer", uid:()=>currentUser && currentUser.uid, token:()=>VecancyAuth.token(),
    tab:()=>activeView, tabLabel:()=>{ const r = selectedRoomId && vacancyRooms.find(x=>x.id === selectedRoomId); return "Viewer · " + VIEW_LABEL[activeView] + (r ? " · Room " + r.room : "") + " · " + VTCore.scopeLabel(filters(), vacancyRooms); },
    tips:["How many beds are vacant?","Show upcoming vacancies","Compare male and female rooms"],
    visible:()=>!!currentUser && !$("vBoard").hidden,
    context:()=>({code:currentCode, roomId:selectedRoomId, filters:filters()}),
    onNav:nav=>{
      if (nav.view && VIEW_LABEL[nav.view]) setView(nav.view);
      if (nav.filters){ Object.entries(nav.filters).forEach(([k,v])=>{ if (FILTER_IDS[k]) $(FILTER_IDS[k]).value = v; }); renderBoard(); }
      if (nav.roomId){ setView("hallway"); selectedRoomId = null; selectRoom(nav.roomId);
        const tile = document.querySelector(`[data-hall-room="${CSS.escape(nav.roomId)}"]`); if (tile) tile.scrollIntoView({block:"center", inline:"center", behavior:"smooth"}); }
    }};
  setTimeout(initializeAssistantWidget, 0);
})();
