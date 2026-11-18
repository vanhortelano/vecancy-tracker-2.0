/* entrance.js — a short cinematic intro when a page opens (Branch Admin, Viewer, Super Admin, Marketing).
   Put it right after <body>:  <script src="entrance.js" data-title="Branch Admin" data-sub="..."></script>
   Full length (about 1.7 s) when you arrive from the front page; a quicker version on a reload.
   It is skipped when nobody is signed in (the page is about to send you to the front page), it can be skipped
   with a click or the Escape key, and it is reduced to a quick fade when the device asks for less motion.
   It only shows text; it never touches data or the sign-in. */
(function(){
  "use strict";
  var me = document.currentScript;
  var title = (me && me.getAttribute("data-title")) || document.title;
  var sub = (me && me.getAttribute("data-sub")) || "";

  var fromFront = false, who = "";
  try{
    fromFront = sessionStorage.getItem("vtEnter") === "1";
    sessionStorage.removeItem("vtEnter");
    var s = JSON.parse(sessionStorage.getItem("vtLocalSession") || localStorage.getItem("vtLocalSession") || "null");
    if (s && s.exp * 1000 > Date.now()) who = (sessionStorage.getItem("vtFrontEmail") || localStorage.getItem("vtFrontEmail")) || String(s.username || "");
  }catch(e){}
  if (!fromFront && !who) return;          // not signed in: no intro, the page goes to the front page

  // light or dark, the same as the page the person is opening (Super Admin and Marketing keep their own choice)
  var dark = false;
  try{
    if (/superadmin|marketing/i.test(location.pathname)){
      var ct = localStorage.getItem("centralTheme");
      dark = ct ? ct === "dark" : !!(window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
    } else dark = localStorage.getItem("loginTheme") === "dark";
  }catch(e){}

  var esc = function(t){ return String(t).replace(/[&<>"]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); };
  var el = document.createElement("div");
  el.id = "vtEntrance";
  el.setAttribute("aria-hidden", "true");
  el.className = (fromFront ? "" : "short ") + (dark ? "dark" : "light");
  el.innerHTML =
    // the title sits on the top half and the details on the bottom half, so they leave with the curtain
    '<div class="vte-half vte-top"><div class="vte-up"><div class="vte-mark"><img src="assets/brand/mark-' + (dark ? "dark" : "light") + '.webp" alt=""></div>' +
    '<span class="vte-title"><span>' + esc(title) + '</span></span></div></div>' +
    '<div class="vte-half vte-bot"><div class="vte-down">' + (sub ? '<p class="vte-sub">' + esc(sub) + '</p>' : '') +
    '<span class="vte-who">' + (who ? "Signed in as " + esc(who) : "") + '</span></div></div>' +
    '<div class="vte-seam"></div>' +
    '<button class="vte-skip" type="button" tabindex="-1">Skip</button>';
  (document.body || document.documentElement).appendChild(el);

  var hold = fromFront ? 1150 : 650, done = false, timers = [];
  function open(){
    if (done) return; done = true;
    timers.forEach(clearTimeout);
    el.classList.add("go", "open");
    setTimeout(function(){ if (el.parentNode) el.parentNode.removeChild(el); }, 900);
    document.removeEventListener("keydown", onKey);
  }
  function onKey(e){ if (e.key === "Escape" || e.key === "Enter" || e.key === " ") open(); }
  el.addEventListener("click", open);
  document.addEventListener("keydown", onKey);
  // two frames so the starting state is painted before the animation begins
  requestAnimationFrame(function(){ requestAnimationFrame(function(){
    el.classList.add("go");
    timers.push(setTimeout(open, hold));
  }); });
  timers.push(setTimeout(open, 4000));      // safety: never stay on screen
})();
