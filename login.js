/* login.js — the ONE sign-in of Vecancy Tracker (login.html). Shown inside the front page as a large panel
   (login.html?embed=1), or on its own when an app page sends a signed-out visitor here (login.html?next=<page>).

   GET STARTED (feedback A-0095): How did you hear about us? → What's hard right now? → a short "solved" moment →
     create the account (email + password). The answers are saved with the new account. Then the Log in view opens
     with the new account remembered, so you only choose your role and press Log in.
   LOG IN (A-0097): the four roles are listed one under the other; choosing one opens its explanation under it.
     The account remembered on this computer is shown (email, or Google in hosted mode) with "Or choose another
     account". Press Log in to open the role. It never opens a page by itself.

   LOCAL MODE (run_local.py / START-LOCAL.bat, and the sandbox): the email is the login key. The server
     (POST /api/local/login) checks the password (stored only as a salted hash) and returns a signed session token.
     Nothing goes to Firebase. The token (never the password) is kept in localStorage so every page and tab shares it.
   HOSTED MODE (no local server): the existing Vecancy sign-in panel (auth-ui.js) is used for the account part. */
(function(){
"use strict";
const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
const EMBED = params.get("embed") === "1";
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
const ROLES = {"admin.html":"Branch Admin", "viewer.html":"Dormitory Viewer", "superadmin.html":"Super Admin", "marketing.html":"Marketing Directory"};
const SAMPLES = window.VT_SANDBOX
  ? [["sample.one@example.com","Sample1234","Branch Admin"],["boss.demo@example.com","Sample1234","Super Admin"],["viewer.demo@example.com","Sample1234","Viewer"]]
  : [["sample.one@example.com","Sample1234","sample"],["sample.two@example.com","Sample5678","sample"]];
const FIXES = {
  free_beds:     ["Knowing which beds are free", "Every bed is coloured live: green means free. Filter by gender or group in a second."],
  double_booking:["Two people booked for the same bed", "A reservation locks the bed for its dates, so it can't be given twice."],
  checkouts:     ["Keeping track of check-outs", "Check-out reminders list who leaves this week, and overdue tenants turn red the same day."],
  agents_asking: ["Agents keep asking what's available", "Give agents a view-only page that updates by itself."],
  paper_records: ["Records on paper or spreadsheets", "Rooms, tenants, history and emergency contacts in one place, kept for two years."],
  head_office:   ["Reporting to head office", "Head office sees live numbers for every branch, no month-end counting."],
  other:         ["Something else", "Tell us after you sign in — the assistant and the tutorial on every page can help too."]
};
const esc = t => String(t).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

let role = "", local = false, signedIn = null, useOther = false, pending = "", sawSignedOut = false, method = "email";
const survey = {source:"", sourceOther:"", problems:[], problemOther:""};

/* ---------- small things ---------- */
$("themeBtn").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try{ localStorage.setItem("vtLandingTheme", next); }catch(e){}
});
$("closeBtn").addEventListener("click", close);
addEventListener("keydown", e => { if (e.key === "Escape") close(); });
function close(){ if (EMBED) parent.postMessage({vt:"close"}, location.origin); else location.href = "index.html"; }
if (!EMBED){ $("closeBtn").setAttribute("aria-label", "Back to the front page"); $("closeBtn").title = "Back to the front page"; }
document.querySelectorAll("[data-show]").forEach(b => b.addEventListener("click", () => {
  const i = $(b.dataset.show); i.type = i.type === "password" ? "text" : "password"; b.textContent = i.type === "password" ? "Show" : "Hide";
}));
function go(target){
  try{ sessionStorage.setItem("vtEnter", "1"); }catch(e){}
  if (EMBED){ parent.postMessage({vt:"go", to:target}, location.origin); return; }
  document.documentElement.classList.add("leaving");
  setTimeout(() => { location.href = target; }, calm ? 0 : 450);
}
function say(id, text, kind){ const m = $(id); m.textContent = text || ""; m.className = "msg" + (kind ? " " + kind : ""); }

/* ---------- views ---------- */
const VIEWS = ["vSource", "vProblem", "vSolved", "vCreate", "vLogin"];
const CRUMB = {vSource:"Get started · 1 of 4", vProblem:"Get started · 2 of 4", vSolved:"Get started · 3 of 4", vCreate:"Get started · 4 of 4", vLogin:"Log in"};
function show(id){
  if (id === "login") id = "vLogin";
  VIEWS.forEach(v => { $(v).hidden = v !== id; });
  $("crumb").textContent = CRUMB[id];
  $("scroll").scrollTop = 0;
  if (id === "vSolved") playSolved();
  if (id === "vCreate") setupCreate();
  if (id === "vLogin") renderLogin();
  const h = $(id).querySelector("h1"); setTimeout(() => h && h.focus({preventScroll:true}), 40);
}
document.addEventListener("click", e => {
  const g = e.target.closest("[data-goto]"); if (g){ show(g.dataset.goto); return; }
  const b = e.target.closest("[data-back]"); if (b){ show(b.dataset.back); return; }
  const k = e.target.closest("[data-skip]"); if (k){ show(k.dataset.skip); }
});

/* ---------- survey ---------- */
function pick(groupId, multi, onChange){
  $(groupId).addEventListener("click", e => {
    const c = e.target.closest(".choice"); if (!c) return;
    if (!multi) $(groupId).querySelectorAll(".choice").forEach(x => x.setAttribute("aria-pressed", String(x === c)));
    else c.setAttribute("aria-pressed", String(c.getAttribute("aria-pressed") !== "true"));
    onChange(Array.from($(groupId).querySelectorAll('.choice[aria-pressed="true"]')).map(x => x.dataset.v));
  });
}
pick("srcChoices", false, v => {
  survey.source = v[0] || ""; $("srcNext").disabled = !survey.source;
  $("srcOtherWrap").hidden = survey.source !== "other"; if (survey.source === "other") $("srcOther").focus();
});
pick("probChoices", true, v => {
  survey.problems = v; $("probNext").disabled = !v.length;
  $("probOtherWrap").hidden = !v.includes("other");
});
$("srcNext").addEventListener("click", () => { survey.sourceOther = $("srcOther").value.trim(); show("vProblem"); });
$("probNext").addEventListener("click", () => { survey.problemOther = $("probOther").value.trim(); show("vSolved"); });

function playSolved(){
  const face = $("face"), mouth = $("mouth");
  face.classList.remove("happy"); mouth.setAttribute("d", "M38 90 Q60 74 82 90");
  const list = (survey.problems.length ? survey.problems : ["free_beds", "checkouts", "agents_asking"]);
  $("solvedLead").textContent = survey.problems.length ? "Here is what Vecancy Tracker does about each one." : "Here is what most dorms fix first.";
  $("fixes").innerHTML = list.map((k, i) => { const f = FIXES[k] || FIXES.other;
    return `<li style="animation-delay:${(0.6 + i * 0.22).toFixed(2)}s"><span class="tick">✓</span><div><s>${esc(f[0])}</s><b>${esc(f[1])}</b></div></li>`; }).join("");
  setTimeout(() => {
    face.classList.add("happy"); mouth.setAttribute("d", "M34 76 Q60 106 86 76");
    $("tSolved").textContent = "Problems solved.";
    if (!calm) confetti();
  }, calm ? 0 : 500);
}
function confetti(){
  const box = $("confetti"), colors = ["#34d399", "#a78bfa", "#60a5fa", "#facc15", "#fb7185"];
  box.innerHTML = Array.from({length:46}, (_, i) => `<i style="left:${Math.random() * 100}%;background:${colors[i % 5]};animation-delay:${(Math.random() * .5).toFixed(2)}s;animation-duration:${(1.6 + Math.random()).toFixed(2)}s"></i>`).join("");
  setTimeout(() => { box.innerHTML = ""; }, 3200);
}

/* ---------- create the account ---------- */
function setupCreate(){
  $("createForm").hidden = !local;
  $("createHosted").hidden = local;
  if (!local){ $("createHosted").appendChild($("hostedMount")); }
  else setTimeout(() => $("cEmail").focus(), 60);
}
function apiPost(path, body){
  return fetch((window.VT_API_BASE || "") + "/api" + path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)})
    .then(res => res.json().catch(() => ({})).then(j => {
      if (!res.ok){ const e = new Error(j.message || "Something went wrong."); e.code = j.error || "error"; throw e; }
      return j;
    }));
}
function niceError(e){
  if (e && e.name === "TypeError") return "Can't reach the app server. Start it with START-LOCAL.bat (or the VS Code task “Start Vacancy Tracker”), keep that window open, then try again.";
  const c = e && e.code;
  if (c === "bad_login" || c === "auth/invalid-credential") return "The email or password is incorrect.";
  if (c === "email_has_account" || c === "name_taken") return "That email already has an account. Log in instead.";
  if (c === "rate_limited") return "Too many attempts. Wait a little while, then try again.";
  return (e && e.message) || "Something went wrong. Please try again.";
}
const validEmail = v => /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(v);
$("createForm").addEventListener("submit", e => {
  e.preventDefault();
  const email = $("cEmail").value.trim(), password = $("cPass").value;
  if (!validEmail(email)){ say("cMsg", "Enter a valid email address.", "bad"); $("cEmail").focus(); return; }
  if (email.toLowerCase().endsWith("@vecancy.tracker")){ say("cMsg", "Use your own email address.", "bad"); return; }
  if (password.length < 8){ say("cMsg", "The password needs at least 8 characters.", "bad"); $("cPass").focus(); return; }
  const btn = $("createBtn"); btn.disabled = true; say("cMsg", "Creating your account…");
  apiPost("/local/register", {username:"", email, password, survey})
    .then(() => { pending = "created:" + email; return VecancyAuth.auth.signInWithEmailAndPassword(email, password); })
    .catch(err => { pending = ""; say("cMsg", niceError(err), "bad"); })
    .then(() => { btn.disabled = false; });
});

/* ---------- log in ---------- */
function recent(){ try{ return JSON.parse(localStorage.getItem("vtRecentEmails") || "[]").filter(x => typeof x === "string").slice(0, 4); }catch(e){ return []; } }
function remember(email){
  try{
    localStorage.setItem("vtRecentEmails", JSON.stringify([email].concat(recent().filter(x => x !== email)).slice(0, 4)));
    localStorage.setItem("vtFrontEmail", email); sessionStorage.setItem("vtFrontEmail", email);   // this tab's account
  }catch(e){}
}
function setRole(r){
  role = r;
  document.querySelectorAll(".role").forEach(x => {
    const on = x.dataset.role === String(r).split(/[?#]/)[0];
    x.classList.toggle("open", on); x.querySelector(".role-head").setAttribute("aria-checked", String(on));
  });
  updateLoginBtn();
}
$("roles").addEventListener("click", e => {
  const h = e.target.closest(".role-head"); if (!h) return;
  setRole(h.parentElement.dataset.role);
});
function updateLoginBtn(){
  const b = $("loginBtn"), name = ROLES[String(role).split(/[?#]/)[0]];
  b.disabled = !name;
  b.textContent = name ? "Log in" + (signedIn && !useOther ? " as " + signedIn.email : "") + " — " + name : "Choose a role first";
}
function renderLogin(){
  const me = signedIn && !useOther;
  $("paneMe").hidden = !me;
  $("paneMethod").hidden = me;
  document.querySelectorAll(".method").forEach(b => b.setAttribute("aria-checked", String(b.dataset.method === method)));
  $("googleNote").hidden = me || method !== "google" || !local;
  $("loginForm").hidden = me || !local || method !== "email";
  $("loginHosted").hidden = me || local;
  if (!local && !me) $("loginHosted").appendChild($("hostedMount"));
  if (signedIn){
    $("meName").textContent = signedIn.email;
    const google = !local && signedIn.google;
    $("meKind").textContent = (google ? "Google" : "Email") + " · remembered on this computer";
    $("meAv").innerHTML = google ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" d="M21 12.2c0-.7-.1-1.3-.2-1.9H12v3.6h5.1a4.4 4.4 0 0 1-1.9 2.9v2.4h3.1c1.8-1.7 2.7-4.1 2.7-7z"/><path fill="#fff" opacity=".8" d="M12 21c2.6 0 4.7-.9 6.3-2.3l-3.1-2.4c-.9.6-2 .9-3.2.9-2.5 0-4.6-1.7-5.3-3.9H3.5v2.5A9.5 9.5 0 0 0 12 21z"/></svg>' : esc((signedIn.email || "?")[0].toUpperCase());
  }
  if (local && !me){
    const list = recent().map(e => [e, "", "recent"]).concat(SAMPLES.filter(s => !recent().includes(s[0])));
    $("quick").innerHTML = list.map((x, i) => `<button type="button" data-i="${i}" title="${x[2] === "recent" ? "Recent account" : "Sample account · password " + (window.VT_SANDBOX ? "any" : x[1])}">${esc(x[0])}</button>`).join("");
    $("quick").onclick = ev => { const b = ev.target.closest("[data-i]"); if (!b) return; const x = list[+b.dataset.i];
      $("lEmail").value = x[0]; $("lPass").value = x[1] || ""; if (!x[1]) $("lPass").focus(); };
    if (!$("lEmail").value) $("lEmail").value = recent()[0] || "";
  }
  $("easyNote").hidden = !(local && window.VT_EASY_LOGIN);
  $("lPass").placeholder = window.VT_EASY_LOGIN ? "Any password works in test mode" : "Your password";
  updateLoginBtn();
}
$("otherBtn").addEventListener("click", () => { useOther = true; renderLogin(); $("lEmail").value = ""; if (method === "email") $("lEmail").focus(); });
// Google or email: on the hosted app the Vecancy panel (with Google) is shown; the local test server uses email
document.querySelectorAll(".method").forEach(b => b.addEventListener("click", () => { method = b.dataset.method; renderLogin(); if (method === "email" && local) $("lEmail").focus(); }));
$("loginForm").addEventListener("submit", e => { e.preventDefault(); $("loginBtn").click(); });
$("loginBtn").addEventListener("click", () => {
  if (!role) return;
  if (signedIn && !useOther){ go(role); return; }
  if (!local){ say("lMsg", "Sign in with the panel above first.", "bad"); return; }
  if (method === "google"){ say("lMsg", "Google sign-in isn't available on this computer's test server. Choose Continue with email.", "bad"); return; }
  const email = $("lEmail").value.trim(), password = $("lPass").value;
  if (!validEmail(email)){ say("lMsg", "Enter a valid email address.", "bad"); $("lEmail").focus(); return; }
  if (!window.VT_EASY_LOGIN && !password){ say("lMsg", "Enter your password.", "bad"); $("lPass").focus(); return; }
  const btn = $("loginBtn"); btn.disabled = true; say("lMsg", "Logging in…");
  pending = "login:" + email;
  const doIt = () => VecancyAuth.auth.signInWithEmailAndPassword(email, password || "x");
  // switching account: sign the old one out first (only on this computer)
  (signedIn ? Promise.resolve(VecancyAuth.signOut()).then(doIt) : doIt())
    .catch(err => { pending = ""; say("lMsg", niceError(err), "bad"); btn.disabled = false; });
});

/* ---------- start ---------- */
function start(){
  local = !!window.VT_LOCAL_MODE;
  const fileOrNoServer = !local && (location.protocol === "file:" || window.VT_API_BASE);
  const begin = () => VecancyAuth.init({
    mount: "#hostedMount",
    loginPage: true,
    onUser: user => {
      const p = pending; pending = "";
      let email = p ? p.split(":").slice(1).join(":") : "";
      if (!email){ try{ email = (sessionStorage.getItem("vtFrontEmail") || localStorage.getItem("vtFrontEmail")) || ""; }catch(e){} }
      email = email || user.email || "";
      remember(email);
      signedIn = {email, google:!!(user.providerData && user.providerData.some && user.providerData.some(x => x && x.providerId === "google.com"))};
      useOther = false;
      if (p.startsWith("created:")){                 // new account: go to Log in with it remembered (A-0095)
        show("vLogin"); say("lMsg", "Account created. Choose your role, then press Log in.", "good"); return;
      }
      if ((p.startsWith("login:") || (sawSignedOut && !local)) && role){ say("lMsg", "Opening " + ROLES[role.split(/[?#]/)[0]] + "…", "good"); go(role); return; }
      if (!$("vLogin").hidden) renderLogin();
    },
    onSignedOut: () => { signedIn = null; sawSignedOut = true; if (!$("vLogin").hidden) renderLogin(); }
  });
  if (local || fileOrNoServer) begin();
  else {
    // hosted mode only: the existing Vecancy sign-in needs Firebase Authentication (identity only; data stays in SQL)
    loadScripts(["https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js",
                 "https://www.gstatic.com/firebasejs/10.12.2/firebase-auth-compat.js", "firebase-config.js"]).then(begin, begin);
  }
  const n = params.get("next") || "";
  if (ROLES[n.split(/[?#]/)[0]]) setRole(n);
  show(params.get("mode") === "signup" && !n ? "vSource" : "vLogin");
}
function loadScripts(list){
  return list.reduce((p, src) => p.then(() => new Promise((ok, fail) => {
    const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = fail; document.head.appendChild(s);
  })), Promise.resolve());
}
start();
})();
