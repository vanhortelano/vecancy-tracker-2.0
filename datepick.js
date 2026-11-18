/* datepick.js — one calendar for the whole system. Replaces the browser's date / date-time pickers.
   Opens centered over a blurred page, in the colours of the current theme. Values keep the same format as the native inputs. */
(function(){
  const pad = n => String(n).padStart(2,"0");
  const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  let overlay, st = null;

  function parse(input){
    const v = input.value || "", d = new Date();
    let y = d.getFullYear(), m = d.getMonth(), day = null, hh = 12, mm = 0, ss = 0;
    const mt = v.match(/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?)?/);
    if (mt){ y = +mt[1]; m = +mt[2]-1; day = +mt[3]; if (mt[4] !== undefined){ hh = +mt[4]; mm = +mt[5]; ss = +(mt[6] || 0); } }
    return {vy:y, vm:m, sel:day ? {y, m, d:day} : null, hh, mm, ss};
  }
  function ensure(){
    if (overlay) return;
    overlay = document.createElement("div"); overlay.className = "dp-overlay";
    overlay.innerHTML = '<div class="dp-card" role="dialog" aria-modal="true" aria-label="Choose a date"></div>';
    overlay.addEventListener("mousedown", e=>{ if (e.target === overlay) close(); });
    document.body.appendChild(overlay);
    document.addEventListener("keydown", e=>{ if (e.key === "Escape" && st) close(); });
  }
  function close(){ if (overlay) overlay.classList.remove("open"); document.body.classList.remove("dp-open"); st = null; }
  // Time is typed: [hh] : [mm] (: [ss] when the field uses seconds) and AM / PM. 12-hour on screen,
  // saved exactly as before (24-hour "YYYY-MM-DDTHH:MM"), so nothing that reads these values changes.
  function readTime(){
    const card = overlay.firstElementChild, f = k => card.querySelector(`[data-t="${k}"]`);
    if (!f("h")) return true;
    const checks = [["h", 1, 12, "Hour must be 1 to 12."], ["m", 0, 59, "Minutes must be 00 to 59."]].concat(st.secs ? [["s", 0, 59, "Seconds must be 00 to 59."]] : []);
    let bad = null;
    const vals = {};
    checks.forEach(([k, lo, hi, msg])=>{
      const el = f(k), raw = el.value.trim();
      const n = raw === "" ? (k === "h" ? NaN : 0) : Number(raw);
      const ok = /^\d{0,2}$/.test(raw) && Number.isInteger(n) && n >= lo && n <= hi;
      el.classList.toggle("dp-bad", !ok);
      if (ok){ vals[k] = n; el.value = pad(n); } else if (!bad) bad = [el, msg];
    });
    const err = card.querySelector(".dp-terr");
    if (bad){ err.textContent = bad[1]; err.hidden = false; bad[0].focus(); bad[0].select(); return false; }
    err.hidden = true;
    st.hh = (vals.h % 12) + (st.pm ? 12 : 0); st.mm = vals.m; st.ss = vals.s || 0;
    return true;
  }
  function apply(){
    if (!st) return;
    if (st.time && st.sel && !readTime()) return;           // keep the picker open until the time is valid
    const {input, sel, hh, mm, ss, time, secs} = st;
    if (!sel) input.value = "";
    else { const ds = `${sel.y}-${pad(sel.m+1)}-${pad(sel.d)}`; input.value = time ? `${ds}T${pad(hh)}:${pad(mm)}${secs ? ":" + pad(ss) : ""}` : ds; }
    input.dispatchEvent(new Event("input", {bubbles:true})); input.dispatchEvent(new Event("change", {bubbles:true}));
    close();
  }
  function render(){
    const card = overlay.firstElementChild, {vy, vm, sel, time} = st;
    const lead = (new Date(vy, vm, 1).getDay() + 6) % 7, days = new Date(vy, vm+1, 0).getDate();
    const t = new Date(), isToday = d => t.getFullYear() === vy && t.getMonth() === vm && t.getDate() === d;
    let cells = ""; for (let i = 0; i < lead; i++) cells += "<i></i>";
    for (let d = 1; d <= days; d++){
      const on = sel && sel.y === vy && sel.m === vm && sel.d === d;
      cells += `<button type="button" data-d="${d}" class="${on ? "sel" : ""} ${isToday(d) ? "today" : ""}">${d}</button>`;
    }
    const h12 = (st.hh % 12) || 12;
    const tf = (k, v, label) => `<input type="text" inputmode="numeric" maxlength="2" autocomplete="off" data-t="${k}" value="${pad(v)}" aria-label="${label}">`;
    card.innerHTML = `
      <header><button type="button" data-nav="-1" aria-label="Previous month">‹</button><h3>${MONTHS[vm]}</h3><button type="button" data-nav="1" aria-label="Next month">›</button><span class="dp-sp"></span>
        <span class="dp-year"><button type="button" data-ynav="-1" aria-label="Previous year">«</button><input type="text" inputmode="numeric" maxlength="4" data-year value="${vy}" aria-label="Year (type 4 digits)"><button type="button" data-ynav="1" aria-label="Next year">»</button></span></header>
      <p class="dp-yerr" role="alert" hidden></p>
      <div class="dp-week"><span>M</span><span>T</span><span>W</span><span>T</span><span>F</span><span>S</span><span>S</span></div>
      <div class="dp-grid">${cells}</div>
      ${time ? `<div class="dp-time"><span>Time</span>${tf("h", h12, "Hour (1 to 12)")}<b>:</b>${tf("m", st.mm, "Minutes (00 to 59)")}${st.secs ? `<b>:</b>${tf("s", st.ss, "Seconds (00 to 59)")}` : ""}<span class="dp-ampm" role="group" aria-label="AM or PM"><button type="button" data-ampm="am" class="${st.pm ? "" : "on"}" aria-pressed="${!st.pm}">AM</button><button type="button" data-ampm="pm" class="${st.pm ? "on" : ""}" aria-pressed="${st.pm}">PM</button></span></div><p class="dp-terr" role="alert" hidden></p>` : ""}
      <footer><button type="button" data-act="clear">Clear</button><button type="button" data-act="today">Today</button><span class="dp-sp"></span><button type="button" data-act="done" class="dp-primary">Done</button></footer>`;
  }
  function keepTyped(){                 // carry typed hour/minute over a re-render, without judging them yet
    const card = overlay && overlay.firstElementChild; if (!card || !st || !st.time) return;
    const g = k => { const el = card.querySelector(`[data-t="${k}"]`); return el && /^\d{1,2}$/.test(el.value.trim()) ? Number(el.value) : null; };
    const h = g("h"), m = g("m"), s = g("s");
    if (h !== null && h >= 1 && h <= 12) st.hh = (h % 12) + (st.pm ? 12 : 0);
    if (m !== null && m <= 59) st.mm = m;
    if (s !== null && s <= 59) st.ss = s;
  }
  document.addEventListener("click", e=>{
    if (!st || !overlay.contains(e.target)) return;
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.ampm){ keepTyped(); st.pm = b.dataset.ampm === "pm"; st.hh = (st.hh % 12) + (st.pm ? 12 : 0);
      b.parentNode.querySelectorAll("button").forEach(x=>{ const on = x === b; x.classList.toggle("on", on); x.setAttribute("aria-pressed", String(on)); }); return; }
    if (b.dataset.nav || b.dataset.d || b.dataset.ynav) keepTyped();
    if (b.dataset.ynav){ goYear(st.vy + Number(b.dataset.ynav)); return; }
    if (b.dataset.nav){ st.vm += +b.dataset.nav; if (st.vm < 0){ st.vm = 11; st.vy--; } if (st.vm > 11){ st.vm = 0; st.vy++; } render(); }
    else if (b.dataset.d){ st.sel = {y:st.vy, m:st.vm, d:+b.dataset.d}; if (!st.time) apply(); else render(); }
    else if (b.dataset.act === "clear"){ st.sel = null; apply(); }
    else if (b.dataset.act === "today"){ const n = new Date(); st.vy = n.getFullYear(); st.vm = n.getMonth(); st.sel = {y:st.vy, m:st.vm, d:n.getDate()}; if (st.time){ st.hh = n.getHours(); st.mm = n.getMinutes(); st.ss = 0; st.pm = st.hh >= 12; render(); } else apply(); }
    else if (b.dataset.act === "done"){ if (!st.sel){ const n = new Date(); st.sel = {y:st.vy, m:st.vm, d:(n.getMonth() === st.vm && n.getFullYear() === st.vy) ? n.getDate() : 1}; } apply(); }
  });
  const YEAR_MIN = 1900, YEAR_MAX = 2200;
  function goYear(y){
    if (!Number.isInteger(y) || y < YEAR_MIN || y > YEAR_MAX) return false;
    st.vy = y;            // the chosen day stays chosen until another day is clicked
    render();
    return true;
  }
  document.addEventListener("input", e=>{
    const t = e.target; if (!st || !t.dataset || t.dataset.year === undefined || !overlay.contains(t)) return;
    const v = t.value.replace(/\D/g, "").slice(0, 4); if (v !== t.value) t.value = v;
    const err = overlay.querySelector(".dp-yerr");
    if (v.length === 4){
      const y = Number(v);
      if (y < YEAR_MIN || y > YEAR_MAX){ err.textContent = `Enter a year from ${YEAR_MIN} to ${YEAR_MAX}.`; err.hidden = false; t.classList.add("dp-bad"); return; }
      err.hidden = true; t.classList.remove("dp-bad");
      keepTyped(); goYear(y);
      const again = overlay.querySelector("[data-year]"); again.focus(); again.setSelectionRange(4, 4);
    } else { err.hidden = true; t.classList.remove("dp-bad"); }
  });
  document.addEventListener("keydown", e=>{
    const t = e.target; if (!st || !t.dataset || t.dataset.year === undefined || !overlay.contains(t)) return;
    if (e.key === "ArrowUp" || e.key === "ArrowDown"){ e.preventDefault(); keepTyped(); goYear(st.vy + (e.key === "ArrowUp" ? 1 : -1)); const i = overlay.querySelector("[data-year]"); i.focus(); }
    else if (e.key === "Enter"){ e.preventDefault(); if (t.value.length !== 4){ const err = overlay.querySelector(".dp-yerr"); err.textContent = "Type the year with 4 digits, e.g. 2035."; err.hidden = false; } }
    else if (e.key.length === 1 && !/\d/.test(e.key) && !e.ctrlKey && !e.metaKey) e.preventDefault();
  });
  document.addEventListener("focusout", e=>{   // leaving an unfinished year: show the year the calendar is on
    const t = e.target; if (!st || !t.dataset || t.dataset.year === undefined || !overlay.contains(t)) return;
    if (t.value.length !== 4 || Number(t.value) < YEAR_MIN || Number(t.value) > YEAR_MAX){ t.value = String(st.vy); t.classList.remove("dp-bad"); const err = overlay.querySelector(".dp-yerr"); if (err) err.hidden = true; }
  });
  // typing: digits only, two per box, jump to the next box when full; Enter = Done
  document.addEventListener("input", e=>{
    const t = e.target; if (!st || !t.dataset || !t.dataset.t || !overlay.contains(t)) return;
    const clean = t.value.replace(/\D/g, "").slice(0, 2); if (clean !== t.value) t.value = clean;
    t.classList.remove("dp-bad");
    if (clean.length === 2 || (t.dataset.t === "h" && /^[2-9]$/.test(clean))){
      const next = t.dataset.t === "h" ? "m" : t.dataset.t === "m" && st.secs ? "s" : null;
      const el = next && overlay.querySelector(`[data-t="${next}"]`); if (el){ el.focus(); el.select(); }
    }
  });
  document.addEventListener("focusin", e=>{ if (st && e.target.dataset && e.target.dataset.t && overlay.contains(e.target)) e.target.select(); });
  document.addEventListener("focusout", e=>{
    const t = e.target; if (!st || !t.dataset || !t.dataset.t || !overlay.contains(t)) return;
    const v = t.value.trim(); if (/^\d$/.test(v) && !(t.dataset.t === "h" && v === "0")) t.value = pad(+v);
  });
  document.addEventListener("keydown", e=>{
    const t = e.target; if (!st || !t.dataset || !t.dataset.t || !overlay.contains(t)) return;
    if (e.key === "Enter"){ e.preventDefault(); const done = overlay.querySelector('[data-act="done"]'); if (done) done.click(); }
    else if (e.key.length === 1 && !/\d/.test(e.key) && !e.ctrlKey && !e.metaKey) e.preventDefault();      // letters never get in
    else if (e.key === "ArrowUp" || e.key === "ArrowDown"){
      e.preventDefault();
      const [lo, hi] = t.dataset.t === "h" ? [1, 12] : [0, 59];
      let n = Number(t.value) || (t.dataset.t === "h" ? 12 : 0); n += e.key === "ArrowUp" ? 1 : -1;
      if (n > hi) n = lo; if (n < lo) n = hi; t.value = pad(n); t.classList.remove("dp-bad");
    }
  });
  function open(input){
    ensure();
    st = {input, time:input.dataset.dpType === "datetime-local", secs:Number(input.step) > 0 && Number(input.step) < 60, ...parse(input)};
    st.pm = st.hh >= 12;
    render(); overlay.classList.add("open"); document.body.classList.add("dp-open");
  }
  function wrap(input){
    if (input.dataset.dp) return;
    const type = input.type;
    if (type !== "date" && type !== "datetime-local") return;
    input.dataset.dp = "1"; input.dataset.dpType = type;
    const w = document.createElement("span"); w.className = "dp-wrap";
    input.parentNode.insertBefore(w, input); w.appendChild(input);
    const hit = document.createElement("button"); hit.type = "button"; hit.className = "dp-hit"; hit.tabIndex = -1; hit.setAttribute("aria-label", "Choose a date");
    hit.addEventListener("click", e=>{ e.preventDefault(); open(input); });
    w.appendChild(hit);
  }
  const scan = ()=>document.querySelectorAll('input[type="date"]:not([data-dp]),input[type="datetime-local"]:not([data-dp])').forEach(wrap);
  document.addEventListener("DOMContentLoaded", scan);
  new MutationObserver(scan).observe(document.documentElement, {childList:true, subtree:true});
})();
