const ASSISTANT_ENDPOINT = (window.VT_API_BASE || "") + "/api/assistant";
// The same assistant runs on the Branch Admin page (admin.html) and the Super Admin page.
// Other pages describe themselves with window.VT_AI_PAGE = {page, uid(), token(), tab(), tabLabel(), tips, onNav(nav), visible()}.
// It is never shown on the Home page (the role portal / sign-in): only while a signed-in dashboard is on screen.
const aiPage = () => window.VT_AI_PAGE || null;
const aiIsAdmin = () => !aiPage();
function aiUid(){ return aiIsAdmin() ? (typeof currentUser !== "undefined" && currentUser ? currentUser.uid : null) : aiPage().uid(); }
async function aiToken(){ return aiIsAdmin() ? auth.currentUser.getIdToken() : aiPage().token(); }
async function aiPost(path, payload){
  const response = await fetch((window.VT_API_BASE || "") + path, {method:"POST",
    headers:{"Content-Type":"application/json","Authorization":"Bearer " + await aiToken()}, body:JSON.stringify(payload || {})});
  const data = await response.json().catch(()=>({}));
  if (!response.ok) throw new Error(data.error || "The assistant service returned HTTP " + response.status + ".");
  return data;
}
/* The assistant's own logo (feedback A-0024): a little dorm house with two eyes and a spark. */
const AI_LOGO = '<svg class="vt-ai-logo" viewBox="0 0 24 24" aria-hidden="true"><path d="M3.8 11.4 12 4.6l8.2 6.8v7.9a1.4 1.4 0 0 1-1.4 1.4h-4.1v-5h-5.4v5H5.2a1.4 1.4 0 0 1-1.4-1.4z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><circle cx="9.6" cy="12.2" r="1.15" fill="currentColor"/><circle cx="14.4" cy="12.2" r="1.15" fill="currentColor"/><path d="M19.2 1.6l.75 1.75 1.75.75-1.75.75-.75 1.75-.75-1.75-1.75-.75 1.75-.75z" fill="currentColor"/></svg>';
function assistantDefaultStatus(){
  return aiIsAdmin() ? "Type a question below, for example “Which rooms have vacant beds?”, “Who checks out this week?” or “Open the Bed Matrix”. I will always ask you before I change anything."
    : "Type a question below, for example “Which dorm has the most vacant beds?” or “Give me a vacancy report”.";
}
/* ---------------------------------------------------------------- voice (free, built into the browser)
   Reading aloud uses the browser's speech synthesis with the "Google US English" voice when the browser has it
   (Chrome; it is an online voice), otherwise another US English voice. Speaking uses the browser's speech
   recognition (Chrome and Edge; the browser sends the audio to its own speech service). No API key, no cost.
   Phone numbers are never read aloud. Both can be turned off; the choice is remembered on this device. */
const AI_ICON = (d)=>'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
const AI_ICONS = {
  speakerOn:AI_ICON('<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>'),
  speakerOff:AI_ICON('<path d="M11 5 6 9H3v6h3l5 4z"/><path d="m16 9 6 6M22 9l-6 6"/>'),
  mic:AI_ICON('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>'),
  send:AI_ICON('<path d="M12 19V5M5 12l7-7 7 7"/>'),
  busy:'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9"><animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur=".8s" repeatCount="indefinite"/></path></svg>'
};
/* One shared speech player for the assistant and the tutorial, built around Chrome's speech bugs:
   - parts are spoken one at a time, each started when the one before ends (Chrome drops long queues and
     utterances it no longer holds a reference to)
   - speak() is never called in the same moment as cancel() (Chrome silently ignores it)
   - a part that never starts (Chrome's online "Google" voice can hang without any error) is retried with a
     voice installed on the device, and then skipped, so speech can never get stuck
   - speech the browser blocks before the first click on the page ("not-allowed") is spoken at the next click or key */
const VTSpeech = (function(){
  const synth = window.speechSynthesis;
  const ok = !!(synth && window.SpeechSynthesisUtterance);
  let job = 0, queue = [], busy = false, current = null, tapJob = -1, waitingTap = false;
  const localVoice = ()=>{
    const all = synth.getVoices();
    return all.find(x=>x.localService && /^en[-_]US$/i.test(x.lang)) || all.find(x=>x.localService && /^en/i.test(x.lang)) || null;
  };
  function stop(){ job++; queue = []; busy = false; current = null; if (ok) synth.cancel(); }
  function next(my){
    if (my !== job) return;
    const item = queue.shift();
    if (!item){ busy = false; current = null; return; }
    say(item, my, item.voice, false);
  }
  function afterTap(my){
    tapJob = my;
    if (waitingTap) return;
    waitingTap = true;
    const evs = ["pointerdown", "keydown", "touchstart"];
    const go = ()=>{ waitingTap = false; evs.forEach(t=>window.removeEventListener(t, go, true)); if (tapJob === job) setTimeout(()=>next(job), 0); };
    evs.forEach(t=>window.addEventListener(t, go, true));
  }
  function say(item, my, voice, retried){
    const u = new SpeechSynthesisUtterance(item.text);
    if (voice){ u.voice = voice; u.lang = voice.lang; } else u.lang = "en-US";
    try{ if (item.tune) item.tune(u, item.i, voice); }catch(e){}
    let started = false, done = false, dog = 0;
    const end = ()=>{ done = true; clearTimeout(dog); };
    const fallback = ()=>{
      if (done) return; end();
      if (my !== job) return;
      const local = !retried && voice && !voice.localService ? localVoice() : null;
      if (local || (!retried && voice)){ synth.cancel(); setTimeout(()=>{ if (my === job) say(item, my, local, true); }, 80); }
      else next(my);                                              // give up on this part, keep going
    };
    u.onstart = ()=>{ started = true; clearTimeout(dog); };
    u.onend = ()=>{ if (done) return; end(); next(my); };
    u.onerror = e=>{
      if (done || my !== job) return;
      if (e.error === "not-allowed"){ end(); queue.unshift(item); afterTap(my); return; }
      if (e.error === "interrupted" || e.error === "canceled"){ end(); next(my); return; }
      fallback();
    };
    dog = setTimeout(()=>{ if (!started) fallback(); }, 3000);   // never started: the voice is stuck
    current = u;                                                  // keep a reference so Chrome doesn't drop it
    if (synth.paused) synth.resume();
    synth.speak(u);
  }
  return {
    ok, stop,
    // parts: short strings; voice: SpeechSynthesisVoice or null; tune(u, i, voice) sets rate/pitch;
    // append: add after what is already being said instead of replacing it
    play(parts, voice, tune, append){
      if (!ok || !parts || !parts.length) return;
      if (!append) stop();
      parts.forEach((text, i)=>queue.push({text, voice, tune, i}));
      if (busy) return;
      busy = true;
      const my = job;
      setTimeout(()=>{ if (my === job) next(my); }, 100);         // a moment after cancel(), or Chrome ignores it
    },
    get current(){ return current; }
  };
})();
window.VTSpeech = VTSpeech;

const assistantVoice = (function(){
  const synth = window.speechSynthesis;
  const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  const KEY = "vtAssistantVoice", LKEY = "vtAssistantMicLang", WANT = "Google US English";
  let rec = null, voice = null;
  const get = (k, d)=>{ try{ return localStorage.getItem(k) || d; }catch(e){ return d; } };
  const put = (k, v)=>{ try{ localStorage.setItem(k, v); }catch(e){} };
  // Chrome adds its online "Google …" voices a moment AFTER the page opens, so the choice is made again every time
  // it speaks (never cached), and the first reply waits briefly for the Google voice to appear.
  function pickVoice(){
    if (!synth) return null;
    const all = synth.getVoices();
    const en = v=>/^en[-_]US$/i.test(v.lang);
    // the most human-sounding voice the browser has: Edge's "Natural" voices (Aria, Jenny, Guy), then Chrome's
    // "Google US English", then any other US English voice
    voice = all.find(v=>en(v) && /natural/i.test(v.name) && /aria|jenny|ava|emma|michelle/i.test(v.name)) ||
      all.find(v=>en(v) && /natural/i.test(v.name)) ||
      all.find(v=>v.name === WANT) || all.find(v=>v.voiceURI === WANT) ||
      all.find(v=>/google/i.test(v.name) && en(v)) ||
      all.find(v=>en(v) && /zira|samantha|female/i.test(v.name)) ||
      all.find(en) || all.find(v=>/^en/i.test(v.lang)) || null;
    if (typeof document !== "undefined"){
      const b = document.getElementById("assistantVoiceBtn");
      if (b && voice) b.dataset.voice = voice.name;
    }
    return voice;
  }
  const isWanted = v=>!!v && (v.name === WANT || v.voiceURI === WANT || /natural/i.test(v.name));
  function whenVoicesReady(done){
    const v = pickVoice();
    const isChrome = /Chrome\//.test(navigator.userAgent) && !/Edg\//.test(navigator.userAgent) && !/Android/.test(navigator.userAgent);
    if (isWanted(v) || !isChrome) return done(v);
    let finished = false;
    const finish = ()=>{ if (finished) return; finished = true; synth.removeEventListener("voiceschanged", finish); done(pickVoice()); };
    synth.addEventListener("voiceschanged", finish);
    setTimeout(finish, 1500);                                 // never wait longer than this
  }
  if (synth){ pickVoice(); if ("onvoiceschanged" in synth) synth.addEventListener("voiceschanged", pickVoice); }
  function clean(text){
    return String(text || "")
      .replace(/(\+?63[\s-]?|0)9\d{2}[\s-]?\d{3}[\s-]?\d{4}/g, "the number shown on screen")   // never read phone numbers aloud
      .replace(/[\u2190-\u21ff\u2600-\u27bf\u{1F300}-\u{1FAFF}]/gu, " ")
      .replace(/\b([A-Z])-(\d+)/g, "$1 $2").replace(/·|•|—/g, ", ").replace(/\s+/g, " ").trim();
  }
  // Said the way a person would say it: bed-by-bed lists become counts, long lists are cut short (the screen
  // has them), and symbols are read as words. The text on screen is not changed.
  function spoken(text){
    let t = clean(text)
      .replace(/\((Bed [^()]*)\)/g, (_m, beds)=>{ const n = beds.split(",").length; return "(" + n + (n === 1 ? " bed" : " beds") + ")"; })
      .replace(/\s*…\s*\.?/g, ", and more. ").replace(/–/g, ", ").replace(/\bvs\.?(?=\s)/gi, "versus").replace(/\be\.g\.\s*/gi, "for example ")
      .replace(/\s*\(\s*/g, ", ").replace(/\s*\)\s*/g, " ")
      .replace(/(\d+(?:\.\d+)?)%/g, "$1 percent").replace(/\s+([.,;:!?])/g, "$1").replace(/,\s*,/g, ",").replace(/\s+/g, " ").trim();
    // lists of more than four items: say the first three, then "and N more"
    t = t.replace(/(?:[^.;:!?]+;\s*){4,}[^.;:!?]*/g, list=>{
      const items = list.split(/;\s*/).filter(s=>s.trim());
      return items.length > 4 ? items.slice(0, 3).join("; ") + "; and " + (items.length - 3) + " more" : list;
    });
    if (t.length > 520){                                       // a long report: the start, then point at the screen
      const cut = t.slice(0, 480);
      const end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("! "), cut.lastIndexOf("? "));
      t = (end > 200 ? cut.slice(0, end + 1) : cut.replace(/[,;]?\s+\S*$/, ".")) + " The rest is on your screen.";
    }
    return t.replace(/\s+/g, " ").trim();
  }
  // a little life at the start of an answer, not every time and never the same opener twice in a row
  const OPENERS = ["Alright!", "Okay!", "Sure thing!", "Got it!", "Here you go!", "Let's see."];
  let lastOpener = "";
  function lively(t){
    if (/^(hello|hi\b|hey|good (morning|afternoon|evening)|sorry|no\b|yes\b|i can't|i couldn't|i'm not|i'm |nothing|done|okay|alright|sure|which|what|who)/i.test(t)) return t;
    if (Math.random() < 0.45) return t;
    const choices = OPENERS.filter(o=>o !== lastOpener);
    lastOpener = choices[Math.floor(Math.random() * choices.length)];
    return lastOpener + " " + t;
  }
  function chunks(text){             // Chrome's online voices stop after ~15 seconds, so speak sentence by sentence
    const out = []; let cur = "";
    for (const part of text.split(/(?<=[.!?;:])\s+/)){
      if ((cur + " " + part).length > 180 && cur){ out.push(cur); cur = part; } else cur = cur ? cur + " " + part : part;
    }
    if (cur) out.push(cur);
    return out.flatMap(c=>c.length > 220 ? c.match(/.{1,200}(\s|$)/g) : [c]);
  }
  return {
    canSpeak:()=>!!(synth && window.SpeechSynthesisUtterance),
    canListen:()=>!!Rec,
    enabled:()=>get(KEY, "on") === "on",
    setEnabled:on=>{ put(KEY, on ? "on" : "off"); if (!on) VTSpeech.stop(); },
    listenLang:()=>get(LKEY, "en-US"),
    setListenLang:l=>put(LKEY, l),
    listening:()=>!!rec,
    // opts.lively: an answer (may start with a short "Alright!"); intros and warnings are read as they are
    speak(text, first, opts){
      if (!VTSpeech.ok || !this.enabled() || !text) return;
      // a reply that follows the intro (speak(intro, true) then speak(answer)) is added after it, not over it
      const append = !first && !!this._queued;
      this._queued = !!first;
      let said = spoken(text);
      if (opts && opts.lively) said = lively(said);
      const parts = chunks(said);
      if (!parts.length) return;
      if (!append){ this._token = (this._token || 0) + 1; VTSpeech.stop(); }   // the old reply goes quiet right away
      const token = this._token;
      whenVoicesReady(v=>{
        if (token !== this._token) return;                    // a newer reply already started
        // upbeat but clear: a bit faster and brighter than the flat default. Online voices already sound natural,
        // so they get a lighter touch; basic built-in voices get more lift so they sound less monotone.
        const tune = (u, i, voice)=>{
          const natural = voice && /natural|google/i.test(voice.name);
          const q = /\?\s*$/.test(u.text), ex = /!\s*$/.test(u.text);
          u.rate = (natural ? 1.06 : 1.1) + (i === 0 ? 0.02 : 0);
          u.pitch = (natural ? 1.08 : 1.18) + (ex ? 0.07 : q ? 0.05 : 0);
          u.volume = 1;
        };
        VTSpeech.play(parts, v, tune, append);
      });
    },
    voiceName:()=>{ const v = pickVoice(); return v ? v.name : "the browser's default voice"; },
    stop(){ VTSpeech.stop(); },
    spoken, lively,
    ready:whenVoicesReady,                 // the tutorial uses the same voice choice (tutorial.js)
    listen(h){
      if (!Rec || rec) return;
      if (synth) synth.cancel();                      // don't let the assistant's voice be heard as the question
      rec = new Rec();
      rec.lang = this.listenLang(); rec.interimResults = true; rec.maxAlternatives = 1; rec.continuous = false;
      let finalText = "", gotFinal = false;
      rec.onstart = ()=>h.onStart && h.onStart();
      rec.onresult = e=>{
        let interim = "";
        for (let i = e.resultIndex; i < e.results.length; i++){
          if (e.results[i].isFinal){ finalText += e.results[i][0].transcript; gotFinal = true; } else interim += e.results[i][0].transcript;
        }
        h.onText && h.onText((finalText + interim).trim(), false);
      };
      rec.onerror = e=>{
        const msg = {"not-allowed":"Microphone blocked. Allow microphone access for this site in the browser, then try again.",
          "service-not-allowed":"Microphone blocked. Allow microphone access for this site in the browser, then try again.",
          "no-speech":"I didn't hear anything. Click the microphone and speak again.",
          "audio-capture":"No microphone was found on this device.",
          "network":"Voice typing needs an internet connection."}[e.error] || ("Voice typing stopped (" + e.error + ").");
        if (e.error !== "aborted") h.onError && h.onError(msg);
      };
      rec.onend = ()=>{ rec = null; h.onEnd && h.onEnd(); if (gotFinal) h.onText && h.onText(finalText.trim(), true); };
      try{ rec.start(); }catch(err){ rec = null; h.onError && h.onError("Voice typing couldn't start: " + err.message); h.onEnd && h.onEnd(); }
    },
    stopListening(){ if (rec) rec.stop(); }
  };
})();
window.assistantVoice = assistantVoice;

// What is read aloud: the answer itself, and for a message with several questions, each part's answer too
// (they arrive as "subheading" + "text" blocks). Tables and lists stay on screen only.
function assistantSpeechText(answer){
  const parts = [String(answer.response || "")];
  const blocks = Array.isArray(answer.blocks) ? answer.blocks : [];
  if (blocks.some(b=>b && b.type === "subheading")){
    const texts = blocks.filter(b=>b && b.type === "text" && b.text).map(b=>String(b.text));
    const labels = {1:["Also,"], 2:["First,", "And second,"], 3:["First,", "Next,", "And finally,"], 4:["First,", "Second,", "Third,", "And finally,"]}[texts.length] ||
                   texts.map((_t, i)=>i === texts.length - 1 ? "And finally," : "Next,");
    texts.forEach((t, i)=>parts.push(labels[i] + " " + t.charAt(0).toLowerCase() + t.slice(1)));
  }
  return parts.join(" ").trim();
}

function ensureAssistantMarkup(){
  if (document.getElementById("assistantPanel")) return;
  const aside = document.createElement("aside");
  aside.className = "assistant-widget vtc-standalone";
  aside.setAttribute("aria-label", "Assistant");
  aside.innerHTML = `<section class="assistant-panel" id="assistantPanel" aria-labelledby="assistantTitle" hidden>
      <header class="assistant-header"><div class="assistant-avatar" aria-hidden="true">${AI_LOGO}</div>
        <div class="assistant-heading"><h2 id="assistantTitle">Vacancy Assistant</h2><span>Reports, navigation and answers from your approved data</span></div>
        <button class="assistant-close" id="assistantCloseBtn" type="button" aria-label="Close assistant">&times;</button></header>
      <div class="assistant-messages" id="assistantMessages" aria-live="polite" aria-relevant="additions">
        <div class="assistant-message"><span class="assistant-message-avatar" aria-hidden="true">${AI_LOGO}</span><p>Hi! Ask me for a vacancy report, which dormitory has the highest vacancy, or say “take me to the server”.</p></div>
        <p class="assistant-notice" id="assistantStatus"></p></div>
      <div class="assistant-suggestions" id="assistantSuggestions" aria-label="Suggested questions"></div>
      <form class="assistant-compose" id="assistantForm"><input type="text" id="assistantInput" aria-label="Message" placeholder="Ask about vacancy, risk or a dormitory…" autocomplete="off" required>
        <button type="submit" id="assistantSendBtn" aria-label="Send message">↑</button></form></section>
    <p class="assistant-greeting" id="assistantGreeting">How can I assist you?</p>
    <button class="assistant-launcher" id="assistantLauncher" type="button" aria-label="Open assistant" aria-expanded="false" aria-controls="assistantPanel">${AI_LOGO}</button>`;
  document.body.appendChild(aside);
}

let assistantPendingAction = null;
let assistantBusy = false;
let assistantRequestController = null;
let assistantConversationId = null;
let assistantRestoredFor = null;      // the account whose saved conversation is on screen
// What the person is looking at: the open tab (activeTab) and the room/bed they last clicked.
// Sent to the server only as a hint; the server re-checks every id against the user's own records.
const assistantFocus = {roomId:null, index:null};
const ASSISTANT_TAB_LABELS = {dashboard:"Room Canvas",reminders:"Checkout Reminders",hallway:"Hallway Layout",analytics:"Analytics",
  matrix:"Bed Matrix",calendar:"Checkout Schedule",reserve:"Reserved Clients",temporary:"Temporary Dorm Clients",
  history:"Tenant History",viewers:"Viewer Access",central:"Central Link",transfer:"Data Transfer"};
const ASSISTANT_TAB_TIPS = {dashboard:["Who is in this room?","Which rooms have vacant beds?","Explain this tab"],
  reminders:["Who is overdue?","Who leaves this week?"],calendar:["Who leaves this week?","Who leaves this month?"],
  reserve:["Show my reservations","Explain this tab"],temporary:["Show temporary guests","Explain this tab"],
  analytics:["Give me a summary","Which rooms are full?"],matrix:["Vacant beds for female students","Who leaves this week?"],
  hallway:["Explain this tab","Add a facility called Laundry"],history:["Explain this tab","Give me a summary"]};

function assistantLocalDate(){
  const now = new Date();
  return now.getFullYear() + "-" + String(now.getMonth()+1).padStart(2,"0") + "-" + String(now.getDate()).padStart(2,"0");
}

function assistantContextPayload(){
  const room = assistantFocus.roomId && typeof rooms !== "undefined" && rooms.find(item=>item.id===assistantFocus.roomId);
  const bed = room && Number.isInteger(assistantFocus.index) ? room.beds[assistantFocus.index] : null;
  if (!aiIsAdmin()) return {page:aiPage().page, tab:aiPage().tab(), roomId:null, slot:null, today:assistantLocalDate(),
    now:Date.now(), tzOffset:new Date().getTimezoneOffset(), ...(aiPage().context ? aiPage().context() : {})};
  return {page:"admin", tab:typeof activeTab === "string" ? activeTab : "", roomId:room ? room.id : null,
    slot:bed ? (bed.slot || "") : null, today:assistantLocalDate(), now:Date.now(), tzOffset:new Date().getTimezoneOffset()};
}

function renderAssistantContext(suggestions){
  const box = document.getElementById("assistantContext");
  const chips = document.getElementById("assistantSuggestions");
  if (!chips) return;
  const room = aiIsAdmin() && assistantFocus.roomId && typeof rooms !== "undefined" && rooms.find(item=>item.id===assistantFocus.roomId);
  const bed = room && Number.isInteger(assistantFocus.index) ? room.beds[assistantFocus.index] : null;
  const tab = aiIsAdmin() ? (ASSISTANT_TAB_LABELS[typeof activeTab === "string" ? activeTab : ""] || "") : aiPage().tabLabel();
  if (box){ box.innerHTML = "";
  if (tab || room){
    const label = document.createElement("span");
    label.textContent = "Looking at: " + [tab, room ? "Room " + room.room + (bed ? ", " + (bed.slot || "") : "") : ""].filter(Boolean).join(" · ");
    box.appendChild(label);
    if (room){
      const clear = document.createElement("button");
      clear.type = "button";
      clear.setAttribute("aria-label", "Forget the selected room");
      clear.textContent = "×";
      clear.addEventListener("click", ()=>{ assistantFocus.roomId = null; assistantFocus.index = null; renderAssistantContext(); });
      box.appendChild(clear);
    }
    box.hidden = false;
  }else box.hidden = true; }
  const defaults = aiIsAdmin() ? (ASSISTANT_TAB_TIPS[activeTab] || ["Report the vacancy","Who leaves this week?","Why did vacancy increase?"]) : (aiPage().tips || []);
  const tips = (Array.isArray(suggestions) && suggestions.length ? suggestions : defaults)
    .filter(tip=>room || !/\b(this room|here)\b/i.test(tip)).slice(0,3);
  chips.innerHTML = "";
  tips.forEach(tip=>{
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "assistant-chip";
    chip.textContent = tip;
    chip.addEventListener("click", ()=>{
      const input = document.getElementById("assistantInput");
      if (!input || input.disabled) return;
      input.value = tip;
      document.getElementById("assistantForm").requestSubmit();
    });
    chips.appendChild(chip);
  });
}

function trackAssistantFocus(event){
  const target = event.target && event.target.closest ? event.target : null;
  if (!target || target.closest("#assistantPanel") || !aiIsAdmin()) return;
  const el = target.closest("[data-bed],[data-room],.room-tile[data-id]");
  let roomId = null, index = null;
  if (el){
    if (el.dataset.bed){ try{ const pair = JSON.parse(el.dataset.bed); roomId = pair[0]; index = pair[1]; }catch(error){} }
    else if (el.dataset.room){ roomId = el.dataset.room; if (el.dataset.index !== undefined) index = Number(el.dataset.index); }
    else roomId = el.dataset.id;
  }
  if (roomId && typeof rooms !== "undefined" && rooms.some(item=>item.id===roomId)){
    assistantFocus.roomId = roomId;
    assistantFocus.index = Number.isInteger(index) ? index : null;
  }
  if (el || target.closest("nav.tabs")) setTimeout(()=>renderAssistantContext(), 0);
}

function resetAssistantForUserChange(){
  if (assistantRequestController) assistantRequestController.abort();
  assistantRequestController = null;
  assistantPendingAction = null;
  assistantBusy = false;
  assistantConversationId = null;
  assistantRestoredFor = null;
  assistantFocus.roomId = null;
  assistantFocus.index = null;
  const messages = document.getElementById("assistantMessages");
  if (messages){
    const greeting = messages.querySelector(".assistant-message:not(.user)");
    messages.querySelectorAll(".assistant-message,.assistant-action,.assistant-memory").forEach(message=>{
      if (message !== greeting) message.remove();
    });
  }
  const input = document.getElementById("assistantInput");
  if (input){
    input.value = "";
    input.disabled = false;
  }
  const sendButton = document.getElementById("assistantSendBtn");
  if (sendButton){
    sendButton.disabled = false;
    sendButton.innerHTML = AI_ICONS.send;
  }
  const status = document.getElementById("assistantStatus");
  if (status){
    status.textContent = assistantDefaultStatus();
    status.classList.remove("error");
  }
  const panel = document.getElementById("assistantPanel");
  const greeting = document.getElementById("assistantGreeting");
  const launcher = document.getElementById("assistantLauncher");
  if (panel) panel.hidden = true;
  if (greeting) greeting.hidden = false;
  if (launcher){
    launcher.setAttribute("aria-expanded", "false");
    launcher.setAttribute("aria-label", "Open dorm assistant");
  }
}

function initializeAssistantWidget(){
  ensureAssistantMarkup();
  const widget = document.querySelector(".assistant-widget");
  // Never on the Home page: visible only while a signed-in dashboard is on screen.
  const syncVisible = ()=>{
    const show = aiIsAdmin() ? !!(document.getElementById("app") && document.getElementById("app").classList.contains("visible") && aiUid())
      : !!aiPage().visible();
    if (widget.hidden !== !show) widget.hidden = !show;        // only on change (avoids re-triggering the observer)
    if (show && aiUid()) consumePendingNav();
  };
  syncVisible();
  let syncQueued = false;
  new MutationObserver(records=>{
    if (syncQueued || records.every(r=>widget.contains(r.target))) return;
    syncQueued = true;
    requestAnimationFrame(()=>{ syncQueued = false; syncVisible(); });
  }).observe(document.body, {attributes:true, subtree:true, attributeFilter:["class","hidden"]});
  const panel = document.getElementById("assistantPanel");
  const launcher = document.getElementById("assistantLauncher");
  const greeting = document.getElementById("assistantGreeting");
  const form = document.getElementById("assistantForm");
  const input = document.getElementById("assistantInput");
  const sendButton = document.getElementById("assistantSendBtn");
  const status = document.getElementById("assistantStatus");
  sendButton.innerHTML = AI_ICONS.send;
  const setOpen = isOpen=>{
    panel.hidden = !isOpen;
    greeting.hidden = isOpen;
    launcher.setAttribute("aria-expanded", String(isOpen));
    launcher.setAttribute("aria-label", isOpen ? "Close dorm assistant" : "Open dorm assistant");
    if (isOpen) input.focus();
  };
  launcher.addEventListener("click", ()=>{ if (panel.hidden){ renderAssistantContext(); restoreAssistantHistory(); } setOpen(panel.hidden); });
  // Memory: what the assistant remembers for THIS account (stored on the server per account).
  const header = panel.querySelector(".assistant-header");
  const memBtn = document.createElement("button");
  memBtn.type = "button"; memBtn.className = "assistant-memory-btn"; memBtn.id = "assistantMemoryBtn";
  memBtn.textContent = "Memory"; memBtn.setAttribute("aria-label", "Show what the assistant remembers for this account");
  header.insertBefore(memBtn, document.getElementById("assistantCloseBtn"));
  const wideBtn = document.createElement("button");
  wideBtn.type = "button"; wideBtn.className = "assistant-expand-btn"; wideBtn.id = "assistantExpandBtn";
  wideBtn.textContent = "⤢"; wideBtn.setAttribute("aria-label", "Make the assistant larger"); wideBtn.title = "Expand / shrink";
  header.insertBefore(wideBtn, document.getElementById("assistantCloseBtn"));
  wideBtn.addEventListener("click", ()=>{ const wide = panel.classList.toggle("wide"); wideBtn.setAttribute("aria-label", wide ? "Make the assistant smaller" : "Make the assistant larger"); });
  memBtn.addEventListener("click", ()=>showAssistantMemory().catch(error=>setAssistantStatus("Couldn't load memory: " + error.message, true)));
  // Voice: every reply is read aloud (browser voice, free) and the microphone turns speech into text.
  const voiceBtn = document.createElement("button");
  voiceBtn.type = "button"; voiceBtn.className = "assistant-expand-btn assistant-voice-btn"; voiceBtn.id = "assistantVoiceBtn";
  header.insertBefore(voiceBtn, memBtn);
  const syncVoiceBtn = ()=>{
    const on = assistantVoice.enabled();
    voiceBtn.innerHTML = on ? AI_ICONS.speakerOn : AI_ICONS.speakerOff;
    voiceBtn.setAttribute("aria-pressed", String(on));
    voiceBtn.setAttribute("aria-label", on ? "Replies are read aloud. Turn the voice off" : "Voice is off. Read replies aloud");
    voiceBtn.title = on ? "Voice on: " + assistantVoice.voiceName() + " (click to turn off)" : "Voice off (click to turn on)";
  };
  syncVoiceBtn();
  voiceBtn.hidden = !assistantVoice.canSpeak();
  voiceBtn.addEventListener("click", ()=>{ assistantVoice.setEnabled(!assistantVoice.enabled()); syncVoiceBtn(); });
  voiceBtn.addEventListener("mouseenter", syncVoiceBtn);              // hover shows which voice is used right now
  if (window.speechSynthesis && "onvoiceschanged" in window.speechSynthesis) window.speechSynthesis.addEventListener("voiceschanged", syncVoiceBtn);
  if (assistantVoice.canListen()){
    const micBtn = document.createElement("button");
    micBtn.type = "button"; micBtn.className = "assistant-mic-btn"; micBtn.id = "assistantMicBtn";
    micBtn.innerHTML = AI_ICONS.mic;
    micBtn.setAttribute("aria-label", "Speak your question"); micBtn.title = "Speak your question";
    const langBtn = document.createElement("button");
    langBtn.type = "button"; langBtn.className = "assistant-lang-btn"; langBtn.id = "assistantMicLang";
    const syncLang = ()=>{ const l = assistantVoice.listenLang(); langBtn.textContent = l === "fil-PH" ? "FIL" : "EN";
      langBtn.title = "Microphone language: " + (l === "fil-PH" ? "Filipino (Tagalog / Bisaya words)" : "English") + ". Click to switch.";
      langBtn.setAttribute("aria-label", langBtn.title); };
    syncLang();
    langBtn.addEventListener("click", ()=>{ assistantVoice.setListenLang(assistantVoice.listenLang() === "fil-PH" ? "en-US" : "fil-PH"); syncLang(); });
    form.insertBefore(micBtn, sendButton);
    form.insertBefore(langBtn, micBtn);
    micBtn.addEventListener("click", ()=>{
      if (assistantVoice.listening()) return assistantVoice.stopListening();
      if (input.disabled) return;
      assistantVoice.listen({
        onStart:()=>{ micBtn.classList.add("listening"); micBtn.setAttribute("aria-label", "Listening… click to stop"); setAssistantStatus("Listening… speak now."); },
        onText:(text, final)=>{ input.value = text; if (final){ setAssistantStatus(""); if (text.trim()) form.requestSubmit(); } },
        onEnd:()=>{ micBtn.classList.remove("listening"); micBtn.setAttribute("aria-label", "Speak your question"); },
        onError:msg=>setAssistantStatus(msg, true)
      });
    });
  }
  document.addEventListener("click", trackAssistantFocus, true);
  renderAssistantContext();
  document.getElementById("assistantCloseBtn").addEventListener("click", ()=>setOpen(false));
  document.addEventListener("keydown", event=>{
    if (event.key === "Escape" && !panel.hidden) setOpen(false);
  });
  form.addEventListener("submit", event=>{
    event.preventDefault();
    sendAssistantMessage().catch(error=>{
      console.error("Assistant request failed", error);
      setAssistantStatus("The assistant request failed: " + error.message, true);
      setAssistantBusy(false);
    });
  });

  function setAssistantStatus(message, isError=false){
    status.textContent = message;
    status.classList.toggle("error", isError);
  }

  function setAssistantBusy(isBusy){
    assistantBusy = isBusy;
    input.disabled = isBusy || Boolean(assistantPendingAction);
    sendButton.disabled = isBusy || Boolean(assistantPendingAction);
    document.querySelectorAll("#assistantSuggestions .assistant-chip").forEach(chip=>{ chip.disabled = input.disabled; });
    sendButton.innerHTML = isBusy ? AI_ICONS.busy : AI_ICONS.send;
  }

  function appendAssistantMessage(text, speaker="assistant", opts={}){
    const row = document.createElement("div");
    row.className = "assistant-message" + (speaker === "user" ? " user" : "");
    if (speaker !== "user"){
      const avatar = document.createElement("span");
      avatar.className = "assistant-message-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.innerHTML = AI_LOGO;
      row.appendChild(avatar);
    }
    const body = document.createElement("div");
    body.className = "assistant-bubble";
    const message = document.createElement("p");
    body.appendChild(message);
    row.appendChild(body);
    const box = document.getElementById("assistantMessages");
    const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    box.appendChild(row);
    const finish = ()=>{
      if (Array.isArray(opts.blocks) && opts.blocks.length){ row.classList.add("rich"); renderAssistantBlocks(body, opts.blocks); }
      if (stick || opts.scroll !== false) box.scrollTop = box.scrollHeight;
      if (opts.done) opts.done();
    };
    if (speaker !== "user" && opts.animate) assistantType(message, text, ()=>{ if (stick) box.scrollTop = box.scrollHeight; }, finish);
    else { message.textContent = text; finish(); }
    if (stick || speaker === "user") box.scrollTop = box.scrollHeight;
    return row;
  }

  function appendAssistantLoader(){
    // Centered over the conversation area, so it is obvious the request is being processed.
    const box = document.getElementById("assistantMessages");
    const overlay = document.createElement("div");
    overlay.className = "assistant-busy";
    overlay.setAttribute("role", "status");
    overlay.innerHTML = '<div class="assistant-loader"><div class="loader" aria-hidden="true"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div></div><span>Working on it…</span>';
    overlay.style.top = box.offsetTop + "px";
    overlay.style.height = box.offsetHeight + "px";
    panel.appendChild(overlay);
    box.setAttribute("aria-busy", "true");
    return {remove(){ overlay.remove(); box.removeAttribute("aria-busy"); }};
  }

  function appendAssistantAction(action){
    const card = document.createElement("div");
    card.className = "assistant-action";
    const title = document.createElement("strong");
    title.textContent = "Please confirm this change";
    const description = document.createElement("p");
    description.textContent = describeAssistantAction(action);
    const controls = document.createElement("div");
    controls.className = "assistant-action-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "confirm";
    confirm.textContent = "Confirm";
    controls.append(cancel, confirm);
    card.append(title, description, controls);
    document.getElementById("assistantMessages").appendChild(card);
    card.scrollIntoView({block:"nearest"});

    assistantPendingAction = {action, card, uid:currentUser.uid};
    setAssistantBusy(false);
    cancel.addEventListener("click", ()=>{
      assistantPendingAction = null;
      card.remove();
      setAssistantBusy(false);
      appendAssistantMessage("Okay, I cancelled that change.");
      setAssistantStatus("No tracker changes were made.");
    });
    confirm.addEventListener("click", async ()=>{
      if (!assistantPendingAction || assistantPendingAction.card !== card) return;
      const actionUid = assistantPendingAction.uid;
      if (!currentUser || currentUser.uid !== actionUid) return;
      cancel.disabled = true;
      confirm.disabled = true;
      confirm.textContent = "Working…";
      setAssistantBusy(true);
      setAssistantStatus("Applying the confirmed change…");
      try{
        const before = assistantSnapshotFor(action);
        await applyAssistantAction(action, actionUid);
        if (!currentUser || currentUser.uid !== actionUid) return;
        setAssistantStatus("Checking the saved record…");
        const check = await verifyAssistantAction(action, before);
        appendAssistantMessage(check.message, "assistant", {animate:true});
        setAssistantStatus(check.ok ? "Verified in the database." : "Saved through the normal workflow, but I could not confirm it.", !check.ok);
      }catch(error){
        if (!currentUser || currentUser.uid !== actionUid) return;
        console.error("Confirmed assistant action failed", error);
        appendAssistantMessage("I couldn’t complete that change: " + error.message);
        setAssistantStatus("The change was not completed.", true);
      }finally{
        if (assistantPendingAction && assistantPendingAction.card === card){
          assistantPendingAction = null;
          card.remove();
          setAssistantBusy(false);
        }
      }
    });
  }

  async function sendAssistantMessage(){
    if (assistantBusy || assistantPendingAction) return;
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    appendAssistantMessage(text, "user");
    if (!aiUid()){
      appendAssistantMessage("Please sign in to ask about live tracker data or make changes.");
      setAssistantStatus("Sign in is required for private tracker data.", true);
      return;
    }
    if (aiIsAdmin() && db && !Object.values(assistantDataLoaded).every(Boolean)){
      appendAssistantMessage("Your tracker data is still loading. Please try again in a moment.");
      setAssistantStatus("Waiting for the signed-in account’s live data.", true);
      return;
    }

    setAssistantBusy(true);
    setAssistantStatus("Checking your question and current tracker data…");
    const pending = appendAssistantLoader();
    const requestUid = aiUid();
    const controller = new AbortController();
    assistantRequestController = controller;
    try{
      const timeout = setTimeout(()=>controller.abort(), 65000);
      let response;
      const token = await aiToken();
      if (aiUid() !== requestUid) return;
      try{
        response = await fetch(ASSISTANT_ENDPOINT, {
          method:"POST",
          headers:{"Content-Type":"application/json","Authorization":"Bearer "+token},
          signal:controller.signal,
          body:JSON.stringify({question:text, conversationId:assistantConversationId, context:assistantContextPayload()})
        });
      }finally{
        clearTimeout(timeout);
      }
      if (aiUid() !== requestUid) return;
      const result = await response.json();
      if (aiUid() !== requestUid) return;
      if (!response.ok) throw new Error(result.error || "Assistant service returned HTTP " + response.status + ".");
      const answer = result;
      if (typeof answer.conversationId === "string"){ assistantConversationId = answer.conversationId; assistantRestoredFor = requestUid; }
      else if (answer.intent === "history_cleared"){ assistantConversationId = null; }
      if (typeof answer.response !== "string" || !["tracker","unrelated","uncertain"].includes(answer.scope)){
        throw new Error("The assistant service returned an invalid answer. Please try again.");
      }
      pending.remove();
      if (typeof answer.intro === "string" && answer.intro){          // first reply of a new chat: introduce myself
        appendAssistantMessage(answer.intro);
        assistantVoice.speak(answer.intro, true);
      }
      if (answer.scope === "unrelated"){
        // the server's own explanation ("I have no internet access …") when it gave one, otherwise the general line
        const said = answer.response && answer.response.length > 60 ? answer.response
          : "I can help with this Dorm Vacancy Tracker—its features, records, and workflows. I can’t help with unrelated questions.";
        assistantVoice.speak(said);
        appendAssistantMessage(said);
        setAssistantStatus("This assistant is limited to the vacancy tracker.");
      }else if (answer.scope === "uncertain"){
        assistantVoice.speak(answer.response || "I can't verify that from the tracker. Could you clarify what screen or record you mean?");
        appendAssistantMessage(answer.response || "I can’t verify that from the tracker. Could you clarify what screen or record you mean?");
        setAssistantStatus("I couldn’t verify enough tracker information to answer.");
      }else{
        const nav = answer.nav && typeof answer.nav === "object" ? answer.nav : null;
        assistantVoice.speak(assistantSpeechText(answer), false, {lively:true});
        appendAssistantMessage(answer.response, "assistant", {animate:true, blocks:answer.blocks,
          done:nav ? ()=>assistantNavigate(nav) : null});
        renderAssistantContext(answer.suggestions);
        if (answer.action && answer.action.type && answer.action.type !== "none" && !aiIsAdmin()){
          appendAssistantMessage("That change belongs to your Branch Admin page. Open it (say “open the Room Canvas”) and ask me again there. Nothing was changed.");
          setAssistantStatus("No changes were made.");
        }else if (answer.action && answer.action.type && answer.action.type !== "none"){
          const validation = validateAssistantAction(answer.action);
          if (validation){
            appendAssistantMessage(validation);
            setAssistantStatus("No changes were made; I need more specific information.");
          }else{
            appendAssistantAction(answer.action);
            setAssistantStatus("Review the proposed change. Nothing is written until you confirm.");
          }
        }else{
          setAssistantStatus("Answer based on the current tracker and its features.");
        }
      }
    }catch(error){
      pending.remove();
      if (aiUid() !== requestUid) return;
      let message;
      if (error.name === "AbortError"){
        message = "The assistant took too long to respond. Please try again.";
      }else if (error instanceof TypeError){
        message = "I can’t reach the assistant service. Check your connection and try again.";
      }else{
        message = error.message;
      }
      appendAssistantMessage(message);
      setAssistantStatus(message, true);
    }finally{
      if (assistantRequestController === controller){
        assistantRequestController = null;
        setAssistantBusy(false);
      }
    }
  }

  async function restoreAssistantHistory(){
    const uid = aiUid();
    if (!uid || assistantRestoredFor === uid) return;
    assistantRestoredFor = uid;
    try{
      const data = await aiPost("/api/assistant/recent", {});
      if (aiUid() !== uid || !Array.isArray(data.messages) || !data.messages.length) return;
      assistantConversationId = data.conversationId;
      const box = document.getElementById("assistantMessages");
      const sep = document.createElement("p");
      sep.className = "assistant-notice assistant-earlier";
      sep.textContent = "Earlier in this conversation";
      box.insertBefore(sep, document.getElementById("assistantStatus"));
      data.messages.forEach(m=>{
        const row = appendAssistantMessage(m.content, m.role === "user" ? "user" : "assistant", {blocks:m.blocks, scroll:false});
        box.insertBefore(row, document.getElementById("assistantStatus"));
      });
      box.scrollTop = box.scrollHeight;
    }catch(error){
      assistantRestoredFor = null;
      setAssistantStatus("Couldn't load your earlier conversation: " + error.message, true);
    }
  }

  async function showAssistantMemory(){
    const old = document.querySelector("#assistantMessages .assistant-memory");
    if (old){ old.remove(); return; }
    const data = await aiPost("/api/assistant/memory", {});
    const card = document.createElement("div");
    card.className = "assistant-memory";
    const h = document.createElement("strong");
    h.textContent = "What I remember for this account";
    card.appendChild(h);
    const list = document.createElement("ul");
    (data.items || []).forEach(item=>{ const li = document.createElement("li"); li.textContent = item.label; list.appendChild(li); });
    if (!(data.items || []).length){ const p = document.createElement("p"); p.textContent = "Nothing yet. Try: “Remember that I prefer table format for reports.”"; card.appendChild(p); }
    else card.appendChild(list);
    const row = document.createElement("div");
    row.className = "assistant-action-actions";
    const clear = document.createElement("button"); clear.type = "button"; clear.textContent = "Clear memory";
    const hist = document.createElement("button"); hist.type = "button"; hist.textContent = "Clear chat history";
    const close = document.createElement("button"); close.type = "button"; close.textContent = "Close";
    row.append(hist, clear, close);
    card.appendChild(row);
    clear.disabled = !(data.items || []).length;
    clear.addEventListener("click", async ()=>{
      clear.disabled = true;
      try{ await aiPost("/api/assistant/memory", {clear:true}); card.remove(); appendAssistantMessage("I cleared everything I remembered for your account."); }
      catch(error){ setAssistantStatus("Couldn't clear memory: " + error.message, true); clear.disabled = false; }
    });
    hist.addEventListener("click", ()=>{ card.remove(); input.value = "Clear my chat history"; form.requestSubmit(); });
    close.addEventListener("click", ()=>card.remove());
    const box = document.getElementById("assistantMessages");
    box.appendChild(card);
    box.scrollTop = box.scrollHeight;
  }
  window.restoreAssistantHistory = restoreAssistantHistory;

  setAssistantStatus(assistantDefaultStatus());
}

// ---------------------------------------------------------------- shared helpers (both pages)
// Show the real answer progressively. It starts at once and takes at least 5 seconds to finish (feedback A-0025),
// a little longer for long answers (at most 8 seconds).
function assistantType(el, text, onStep, onDone){
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || !text || text.length < 4){ el.textContent = text || ""; onDone(); return; }
  const duration = Math.max(5000, Math.min(8000, text.length * 18)), start = performance.now();
  el.classList.add("typing");
  let finished = false;
  const step = ()=>{
    if (finished) return;
    const n = Math.min(text.length, Math.ceil(text.length * (performance.now() - start) / duration));
    el.textContent = text.slice(0, n);
    onStep();
    if (n < text.length) setTimeout(step, 16);          // ~60 updates a second
    else { finished = true; el.classList.remove("typing"); onDone(); }
  };
  step();
}

// Structured report parts from the server. Built with DOM nodes and textContent only (no HTML injection).
function renderAssistantBlocks(container, blocks){
  const wrap = document.createElement("div");
  wrap.className = "assistant-blocks";
  blocks.slice(0, 30).forEach(b=>{
    if (!b || typeof b !== "object") return;
    let el;
    if (b.type === "heading" || b.type === "subheading"){ el = document.createElement(b.type === "heading" ? "h4" : "h5"); el.textContent = String(b.text || ""); }
    else if (b.type === "text"){ el = document.createElement("p"); el.textContent = String(b.text || ""); }
    else if (b.type === "note"){ el = document.createElement("p"); el.className = "assistant-block-note"; el.textContent = String(b.text || ""); }
    else if (b.type === "list" && Array.isArray(b.items)){
      el = document.createElement("ul");
      b.items.slice(0, 40).forEach(item=>{ const li = document.createElement("li"); li.textContent = String(item); el.appendChild(li); });
    }else if (b.type === "table" && Array.isArray(b.columns) && Array.isArray(b.rows)){
      el = document.createElement("div");
      el.className = "assistant-table-wrap";
      const table = document.createElement("table");
      const head = table.createTHead().insertRow();
      b.columns.forEach(c=>{ const th = document.createElement("th"); th.textContent = String(c); head.appendChild(th); });
      const body = table.createTBody();
      b.rows.slice(0, 60).forEach(r=>{ const tr = body.insertRow(); (Array.isArray(r) ? r : []).forEach(v=>{ const td = tr.insertCell(); td.textContent = v === null || v === undefined ? "—" : String(v); }); });
      el.appendChild(table);
    }
    if (el) wrap.appendChild(el);
  });
  container.appendChild(wrap);
}

// Carry out a navigation the server worked out (it already checked rooms and Super Admin access).
// "scroll down a little", "slide right the check-out dates", "go to the top": moves the page (or the nearest sideways list) for the user
function assistantScroll(move){
  const dir = String(move.dir || "down"), big = move.amount === "lot", small = move.amount === "little";
  const smooth = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  const page = document.scrollingElement || document.documentElement;
  if (dir === "top" || dir === "bottom"){ window.scrollTo({top:dir === "top" ? 0 : page.scrollHeight, behavior:smooth}); return; }
  if (dir === "up" || dir === "down"){
    const step = Math.round(innerHeight * (small ? 0.25 : big ? 1.6 : 0.7)) * (dir === "up" ? -1 : 1);
    if (move.target === "chat"){ const box = document.getElementById("assistantMessages"); if (box){ box.scrollBy({top:step, behavior:smooth}); return; } }
    window.scrollBy({top:step, behavior:smooth});
    return;
  }
  // the Checkout Schedule month wheel is moved by dragging, so drag it the way a hand would
  const stage = document.getElementById("coStage");
  if (stage && (move.target === "checkout" || !move.target)){
    const r = stage.getBoundingClientRect();
    if (r.width > 60 && r.height > 40 && r.bottom > 0 && r.top < innerHeight){
      const toRight = dir === "right", sy = r.top + r.height * 0.82, sx = r.left + r.width * (toRight ? 0.22 : 0.78);
      const dist = Math.max(120, Math.min(190, stage.clientWidth * 0.2)) * (big ? 2 : 1) * (toRight ? 1 : -1);
      const fire = (type, px)=>stage.dispatchEvent(new PointerEvent(type, {bubbles:true, cancelable:true, pointerId:78, pointerType:"mouse", button:0, buttons:type === "pointerup" ? 0 : 1, clientX:px, clientY:sy, isPrimary:true}));
      stage.scrollIntoView({block:"center", behavior:smooth});
      setTimeout(()=>{ fire("pointerdown", sx); let k = 0; const n = 14;
        const tick = ()=>{ k++; fire("pointermove", sx + dist * k / n); if (k < n) setTimeout(tick, 18); else fire("pointerup", sx + dist); };
        tick(); }, 350);
      return;
    }
  }
  // left / right: the sideways list the user means, else the widest one on screen
  const hint = {checkout:".checkout-scroll, .checkout-list, .checkout-picker, .co-track, .co-carousel, .gcal-list", hallway:".hallway-canvas, .hallway-wrap, .v-hallway-scroll",
                matrix:".matrix-scroll"}[move.target] || "";
  const onScreen = el=>{ const r = el.getBoundingClientRect(); return r.width > 40 && r.height > 20 && r.bottom > 0 && r.top < innerHeight && !el.closest("#assistantPanel, .assistant-panel"); };
  const wide = el=>el.scrollWidth > el.clientWidth + 8 && /(auto|scroll)/.test(getComputedStyle(el).overflowX);
  let list = hint ? Array.from(document.querySelectorAll(hint)).filter(el=>wide(el) && onScreen(el)) : [];
  if (!list.length) list = Array.from(document.querySelectorAll("main *, .tab-panel *, body > div *")).filter(el=>wide(el) && onScreen(el)).slice(0, 400);
  const sign = dir === "left" ? -1 : 1;
  if (!list.length){
    // nothing slides sideways here: use the page's own previous / next control when the user meant the dates
    const btn = document.querySelector(sign < 0 ? '[data-co="prev"], .co-prev, [data-cal="prev"], .cal-prev' : '[data-co="next"], .co-next, [data-cal="next"], .cal-next');
    if (btn && onScreen(btn)){ btn.click(); return; }
    window.scrollBy({left:sign * Math.round(innerWidth * 0.6), behavior:smooth});
    return;
  }
  list.sort((a, b)=>b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight);
  const el = list[0];
  el.scrollIntoView({block:"nearest", behavior:smooth});
  el.scrollBy({left:sign * Math.round(el.clientWidth * (small ? 0.3 : big ? 1.5 : 0.75)), behavior:smooth});
  el.classList.add("assistant-spotlight"); setTimeout(()=>el.classList.remove("assistant-spotlight"), 1800);
}
// "switch to dark mode", "start the tutorial", "mute your voice", "read that again", "close the chat", "refresh", "sign me out"
function assistantUi(ui){
  const click = sel=>{ const el = document.querySelector(sel); if (el){ el.click(); return true; } return false; };
  if (ui.theme){
    const dark = document.body.classList.contains("auth-dark") || document.body.classList.contains("v-dark") || document.documentElement.dataset.theme === "dark";
    if (ui.theme === "toggle" || (ui.theme === "dark") !== dark) click("#appThemeToggle, #vThemeToggle, #themeB, #portalThemeToggle, #heroThemeToggle");
  }
  if (ui.tutorial && window.VTTutorial){
    const l = document.getElementById("assistantLauncher");
    if (l && l.getAttribute("aria-expanded") === "true") l.click();
    setTimeout(()=>window.VTTutorial.start(), 500);
  }
  if (ui.voice){
    assistantVoice.setEnabled(ui.voice === "on");
    const b = document.getElementById("assistantVoiceBtn");
    if (b) b.dispatchEvent(new Event("mouseenter"));          // repaints the speaker icon
  }
  if (ui.repeat){
    const all = Array.from(document.querySelectorAll("#assistantMessages .assistant-message:not(.user)"));
    const prev = all.length > 1 ? all[all.length - 2] : null;
    if (prev) assistantVoice.speak(prev.innerText, true);
  }
  if (ui.close){ const l = document.getElementById("assistantLauncher"); if (l && l.getAttribute("aria-expanded") === "true") setTimeout(()=>l.click(), 1200); }
  if (ui.expand) click("#assistantExpandBtn, .assistant-expand-btn:not(.assistant-voice-btn)");
  if (ui.newchat) setTimeout(()=>{ if (typeof resetAssistantForUserChange === "function") resetAssistantForUserChange(); }, 1800);
  if (ui.print) setTimeout(()=>window.print(), 600);
  if (ui.back) setTimeout(()=>history.back(), 800);
  if (ui.reload) setTimeout(()=>location.reload(), 1500);
  if (ui.signout) setTimeout(()=>{ if (window.VecancyAuth && VecancyAuth.signOut) VecancyAuth.signOut(); else click("#signOutBtn, #outBtn"); }, 1800);
}
function assistantNavigate(nav){
  if (!nav || typeof nav !== "object") return;
  if (nav.ui && typeof nav.ui === "object"){ assistantUi(nav.ui); if (Object.keys(nav).length === 1) return; }
  if (nav.scroll && typeof nav.scroll === "object"){
    const move = nav.scroll, rest = Object.assign({}, nav); delete rest.scroll;
    if (Object.keys(rest).length){ assistantNavigate(rest); setTimeout(()=>assistantScroll(move), 500); } else assistantScroll(move);
    return;
  }
  const here = (location.pathname.split("/").pop() || "index.html").toLowerCase();
  if (nav.url && nav.url !== here){
    try{ sessionStorage.setItem("vtAiNav", JSON.stringify({tab:nav.tab || null, roomId:nav.roomId || null})); }catch(error){}
    location.href = nav.url;
    return;
  }
  if (!aiIsAdmin()){ aiPage().onNav(nav); renderAssistantContext(); return; }
  if (nav.tab && typeof switchTab === "function"){ switchTab(nav.tab); renderAssistantContext(); }
  // "show me only the vacant beds": set the page's own filter bar, exactly as if the user picked it
  if (nav.filters && typeof nav.filters === "object"){
    const ids = {status:"filterVacancy", gender:"filterGender", demographic:"filterDemographic", search:"filterSearch"};
    Object.entries(ids).forEach(([key,id])=>{
      const el = document.getElementById(id), value = nav.filters[key];
      if (!el || value === undefined || value === null) return;
      if (el.tagName === "SELECT" && !Array.from(el.options).some(o=>o.value === String(value))) return;
      el.value = String(value);
      el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", {bubbles:true}));
      el.classList.add("assistant-spotlight"); setTimeout(()=>el.classList.remove("assistant-spotlight"), 2600);
    });
  }
  // "add a reason to my data transfer": only fills the box; the user presses Generate
  if (typeof nav.transferPurpose === "string" && typeof TR !== "undefined"){
    setTimeout(()=>{
      TR.draft.trPurpose = nav.transferPurpose;
      const box = document.getElementById("trPurpose");
      if (box){ box.value = nav.transferPurpose; box.focus(); box.classList.add("assistant-spotlight"); setTimeout(()=>box.classList.remove("assistant-spotlight"), 2600); }
    }, 200);
  }
  if (nav.roomId){
    assistantFocus.roomId = nav.roomId; assistantFocus.index = null;
    renderAssistantContext();
    setTimeout(()=>{
      const tile = document.querySelector(`#view-dashboard [data-room="${CSS.escape(nav.roomId)}"], #view-dashboard .room-tile[data-id="${CSS.escape(nav.roomId)}"], #view-dashboard [data-id="${CSS.escape(nav.roomId)}"]`);
      const card = tile && (tile.closest(".room-card,.canvas-room,.room-tile") || tile);
      if (card){ card.scrollIntoView({block:"center", behavior:"smooth"}); card.classList.add("assistant-spotlight"); setTimeout(()=>card.classList.remove("assistant-spotlight"), 2600); }
      if (typeof tiShowRoom === "function" && !(typeof TI !== "undefined" && TI.side && TI.side.roomId === nav.roomId)) tiShowRoom(nav.roomId);
    }, 120);
  }
}
function consumePendingNav(){
  let nav = null;
  try{ nav = JSON.parse(sessionStorage.getItem("vtAiNav") || "null"); sessionStorage.removeItem("vtAiNav"); }catch(error){}
  if (!nav) return;
  const run = ()=>{
    if (aiIsAdmin() && typeof assistantDataLoaded !== "undefined" && !Object.values(assistantDataLoaded).every(Boolean)) return setTimeout(run, 300);
    assistantNavigate(nav);
  };
  setTimeout(run, 50);
}

// What the record looked like before a confirmed change, to compare with afterwards.
function assistantSnapshotFor(action){
  try{
    if (action.type === "create_room") return {rooms:rooms.length};
    if (action.type === "add_reserve_client") return {prospects:prospects.length};
  }catch(error){}
  return {};
}
// Re-read the record from the database after a confirmed change and report what is ACTUALLY saved.
async function verifyAssistantAction(action, before){
  const roomDoc = async id=>{ const snap = await userCollection("rooms").doc(id).get(); return snap.exists ? snap.data() : null; };
  const ok = message=>({ok:true, message});
  const unsure = message=>({ok:false, message});
  try{
    switch(action.type){
      case "update_tenant_contact":{
        const room = await roomDoc(action.roomId);
        const bed = room && room.beds.find(b=>b.slot===action.slot);
        const rec = bed && bed.tenantId ? await userCollection("tenants").doc(bed.tenantId).get() : null;
        return rec && rec.exists && rec.data().contact === action.contact
          ? ok(`Done. I re-read the record: ${action.tenant}'s contact number is now ${action.contact}.`)
          : unsure("I couldn't confirm the new number in the database. Open Tenant Information to check it.");
      }
      case "checkout_tenant":{
        const room = await roomDoc(action.roomId);
        const bed = room && room.beds.find(b=>b.slot===action.slot);
        return bed && !bed.tenant ? ok(`Done. ${action.slot} is now vacant in the database and the stay is in Tenant History.`)
          : unsure("The bed still shows a tenant in the database, so the check-out may not have completed.");
      }
      case "transfer_resident":{
        const target = await roomDoc(action.targetRoomId);
        const bed = target && target.beds.find(b=>b.slot===action.targetSlot);
        return bed && bed.tenant ? ok(`Done. ${bed.tenant} is now saved in ${action.targetSlot} of Room ${target.room}.`)
          : unsure("I couldn't see the resident in the target bed after the transfer. Check the Room Canvas.");
      }
      case "edit_room":{
        const room = await roomDoc(action.roomId);
        const changes = (action.changes && action.changes.bedChanges) || [];
        const bad = changes.filter(c=>{ const bed = room && room.beds.find(b=>b.slot===c.slot); return !bed || (c.tenant !== undefined && (bed.tenant || null) !== (c.tenant || null)); });
        return room && !bad.length ? ok(`Done. I re-read Room ${room.room} and the change is saved.`)
          : unsure("The room was submitted, but I couldn't see every change in the database. Check the room on the Room Canvas.");
      }
      case "create_room":{
        await new Promise(r=>setTimeout(r, 400));
        const snap = await userCollection("rooms").get();
        return snap.docs.some(d=>String(d.data().room) === String(action.room)) ? ok(`Done. Room ${action.room} is saved in the database.`)
          : unsure("I couldn't find the new room in the database yet. Check the Room Canvas.");
      }
      case "delete_room":
        return (await roomDoc(action.roomId)) ? unsure("The room is still in the database; the app may have blocked the deletion (residents or reservations remain).")
          : ok("Done. The room is no longer in the database.");
      case "add_reserve_client":{
        const snap = await userCollection("prospects").get();
        return snap.docs.some(d=>d.data().name === action.name) ? ok(`Done. ${action.name} is saved as a reserved client.`)
          : unsure("I couldn't find the new reserved client in the database. Check Reserved Clients.");
      }
      case "cancel_reservation": case "confirm_reservation": case "delete_reserve_client":{
        const snap = await userCollection("prospects").doc(action.prospectId).get();
        if (action.type === "delete_reserve_client") return snap.exists ? unsure("The client is still in the database.") : ok("Done. The reserved client was removed.");
        const p = snap.exists ? snap.data() : null;
        if (action.type === "cancel_reservation") return p && !p.reservedBed ? ok("Done. The reservation is cancelled in the database.") : unsure("The reservation still shows in the database.");
        return p && (p.reservedBed || p.checkedIn) ? ok("Done. The reservation is confirmed in the database.") : unsure("I couldn't see the confirmed reservation in the database.");
      }
      default:
        return ok("Saved through the app's normal workflow, and it reported no error.");
    }
  }catch(error){
    return unsure("The change was sent, but re-reading it failed: " + error.message);
  }
}

function validateAssistantAction(action){
  if (!action || typeof action !== "object" || typeof action.type !== "string") return "I couldn’t understand the requested tracker change. Please describe it another way.";
  if (!currentUser || !currentUser.uid || !db) return "Please sign in before making tracker changes.";
  const fail = message=>message;
  const has = (object,key)=>typeof object[key]==="string" && object[key].trim().length>0;
  switch(action.type){
    case "create_room":
      if (!has(action,"room")) return fail("What room name or number should I use?");
      if (!Number.isInteger(action.capacity) || action.capacity<1 || action.capacity>20) return fail("Please specify a room capacity from 1 to 20 beds.");
      if (action.roomType !== undefined && !["Room","Bedspacer"].includes(action.roomType)) return fail("Choose Room or Bedspacer for the room type.");
      if (!["Male","Female","Mixed"].includes(action.gender) || !["Students","Reviewees","Mixed"].includes(action.demographic) || !["Bedspace","Whole Room"].includes(action.tenancyMode)) return fail("I need valid room gender, resident-group zoning, and tenancy-mode details before proposing this room.");
      if (action.beds !== undefined && (!Array.isArray(action.beds) || action.beds.length>action.capacity)) return fail("The room's bed details do not match its capacity.");
      if (Array.isArray(action.beds) && action.beds.some(bed=>bed && ((bed.residentType!==undefined && !["Student","Reviewee","Temporary"].includes(bed.residentType)) || (bed.residentGender!==undefined && !["Unspecified","Male","Female"].includes(bed.residentGender))))) return fail("One or more bed details contain an unsupported resident group or gender.");
      break;
    case "edit_room":{
      if (!has(action,"roomId") || !action.changes || typeof action.changes!=="object") return fail("Which room should I edit, and what should change?");
      {
        const matches = rooms.filter(room=>room.id===action.roomId || String(room.room)===action.roomId);
        if (matches.length!==1) return fail("I can’t identify that room uniquely. Please specify its room number.");
        if (!Object.keys(action.changes).length) return fail("Please specify at least one room field to change.");
        const allowed = new Set(["room","type","gender","demographic","tenancyMode","capacity","bedChanges"]);
        if (Object.keys(action.changes).some(key=>!allowed.has(key))) return fail("I can’t safely apply those room changes. Please request supported room or bed fields.");
        if (action.changes.type!==undefined && !["Room","Bedspacer"].includes(action.changes.type)) return fail("Choose Room or Bedspacer for the room type.");
        if (action.changes.gender!==undefined && !["Male","Female","Mixed"].includes(action.changes.gender)) return fail("Room gender must be Male, Female, or Mixed.");
        if (action.changes.demographic!==undefined && !["Students","Reviewees","Mixed"].includes(action.changes.demographic)) return fail("Resident-group zoning must be Students, Reviewees, or Mixed.");
        if (action.changes.tenancyMode!==undefined && !["Bedspace","Whole Room"].includes(action.changes.tenancyMode)) return fail("Tenancy mode must be Bedspace or Whole Room.");
        if (action.changes.capacity!==undefined && (!Number.isInteger(action.changes.capacity) || action.changes.capacity<1 || action.changes.capacity>20)) return fail("Room capacity must be from 1 to 20 beds.");
        if (action.changes.room!==undefined && (typeof action.changes.room!=="string" || !action.changes.room.trim())) return fail("Room name cannot be blank.");
        if (action.changes.bedChanges!==undefined){
          if (!Array.isArray(action.changes.bedChanges)) return fail("Bed changes must identify specific beds.");
          const room = matches[0];
          const slots = new Set(room.beds.map(bed=>bed.slot));
          const seen = new Set();
          for (const bed of action.changes.bedChanges){
            if (!bed || !slots.has(bed.slot) || seen.has(bed.slot)) return fail("Each bed change must refer to a different existing bed.");
            seen.add(bed.slot);
            if (Object.keys(bed).some(key=>!["slot","tenant","residentType","residentGender","start","end"].includes(key))) return fail("A bed change contains an unsupported field.");
            if (bed.residentType!==undefined && !["Student","Reviewee","Temporary"].includes(bed.residentType)) return fail("Choose Student, Reviewee, or Temporary as the resident group.");
            if (bed.residentGender!==undefined && !["Unspecified","Male","Female"].includes(bed.residentGender)) return fail("Choose Unspecified, Male, or Female as the resident gender.");
            if (bed.tenant!==undefined && bed.tenant!==null && typeof bed.tenant!=="string") return fail("Bed occupant must be a name or null.");
          }
        }
      }
      break;
    }
    case "checkout_tenant":{
      const room = rooms.find(item=>item.id===action.roomId);
      const bed = room && room.beds.find(item=>item.slot===action.slot);
      if (!room || !bed || !bed.tenant) return fail("I can’t find an occupied bed to check out. It may have changed; ask again.");
      if (bed.temporaryClientId) return fail("That bed has a temporary guest. Check them out from Temporary Dorm Clients.");
      if (action.record === "bad" && !String(action.reason || "").trim()) return fail("A bad record needs a reason. Tell me why, for example “bad record because of unpaid rent”.");
      break;
    }
    case "delete_room":
      if (!has(action,"roomId") || !rooms.some(room=>room.id===action.roomId || String(room.room)===action.roomId)) return fail("I can’t identify that room. Please specify its room number.");
      break;
    case "add_reserve_client":
      if (!has(action,"name") || !has(action,"checkIn") || !["Male","Female","Any"].includes(action.gender) || !["Student","Reviewee"].includes(action.demographic)) return fail("To add a reserve client, I need a name, gender, resident group, and check-in date.");
      if (Boolean(action.roomId)!==Boolean(action.slot)) return fail("A preferred reservation needs both a room and a bed.");
      break;
    case "delete_reserve_client":
      if (!has(action,"prospectId") || !prospects.some(client=>client.id===action.prospectId)) return fail("I can’t identify that reserve client. Please specify their name.");
      break;
    case "add_temporary_client":
      if (!has(action,"name") || !has(action,"start") || !has(action,"end") || !["Male","Female","Mixed"].includes(action.gender) || !has(action,"roomId") || !has(action,"slot")) return fail("To assign a temporary client, I need their name, gender, check-in/out, and a specific compatible vacant bed.");
      if (parseScheduleDate(action.end,true) && parseScheduleDate(action.start) && parseScheduleDate(action.end,true)<=parseScheduleDate(action.start)) return fail("The temporary client's checkout must be later than check-in.");
      break;
    case "checkout_temporary_client":
      if (!has(action,"clientId") || !temporaryClients.some(client=>client.id===action.clientId && client.status!=="Checked out")) return fail("I can’t identify an active temporary client to check out.");
      break;
    case "transfer_resident":{
      if (!has(action,"sourceRoomId") || !has(action,"sourceSlot") || !has(action,"targetRoomId") || !has(action,"targetSlot")) return fail("Please specify the resident’s current bed and the destination bed.");
      const source = rooms.find(room=>room.id===action.sourceRoomId);
      const target = rooms.find(room=>room.id===action.targetRoomId);
      if (!source || !target || !source.beds.some(bed=>bed.slot===action.sourceSlot && bed.tenant)) return fail("I can’t verify that occupied source bed.");
      if (!target.beds.some(bed=>bed.slot===action.targetSlot)) return fail("I can’t verify the destination bed.");
      break;
    }
    case "confirm_reservation":{
      const prospect = prospects.find(item=>item.id===action.prospectId);
      const room = rooms.find(item=>item.id===action.roomId);
      if (!prospect || !room || !has(action,"slot")) return fail("I can’t verify the reserve client and target bed.");
      break;
    }
    case "cancel_reservation":{
      const prospect = prospects.find(item=>item.id===action.prospectId);
      if (!prospect || !prospect.reservedBed) return fail("I can’t find an active reservation to cancel.");
      break;
    }
    case "create_shape":
      if (!has(action,"label") || !["facility","walkway"].includes(action.kind) || !["rectangle","circle","triangle"].includes(action.geometry)) return fail("I need a label and a supported facility/walkway shape before creating it.");
      if (action.color!==undefined && !/^#[0-9a-f]{6}$/i.test(action.color)) return fail("Shape color must be a six-digit hex color.");
      break;
    case "edit_shape":{
      if (!has(action,"shapeId") || !action.changes || !shapes.some(shape=>shape.id===action.shapeId)) return fail("I can’t identify that hallway shape or the requested changes.");
      const allowed = new Set(["label","kind","geometry","color"]);
      if (!Object.keys(action.changes).length || Object.keys(action.changes).some(key=>!allowed.has(key))) return fail("I can only change the shape label, type, geometry, or color.");
      if (action.changes.kind!==undefined && !["facility","walkway"].includes(action.changes.kind)) return fail("Shape type must be facility or walkway.");
      if (action.changes.geometry!==undefined && !["rectangle","circle","triangle"].includes(action.changes.geometry)) return fail("Choose rectangle, circle, or triangle geometry.");
      if (action.changes.color!==undefined && !/^#[0-9a-f]{6}$/i.test(action.changes.color)) return fail("Shape color must be a six-digit hex color.");
      if (action.changes.label!==undefined && (typeof action.changes.label!=="string" || !action.changes.label.trim())) return fail("A shape label cannot be blank.");
      break;
    }
    case "delete_shape":
      if (!has(action,"shapeId") || !shapes.some(shape=>shape.id===action.shapeId)) return fail("I can’t identify that hallway shape to delete.");
      break;
    case "update_tenant_contact":{
      const room = rooms.find(item=>item.id===action.roomId);
      const bed = room && room.beds.find(item=>item.slot===action.slot);
      if (!bed || !bed.tenant || tiNorm(bed.tenant) !== tiNorm(action.tenant)) return fail("That tenant is no longer in that bed. Nothing was changed.");
      if (!has(action,"contact") || !phMobileValid(action.contact)) return fail("That isn't a valid Philippine mobile number (09XXXXXXXXX or +639XXXXXXXXX).");
      break;
    }
    case "none":
      break;
    default:
      return fail("That tracker operation isn’t available through the assistant.");
  }
  return null;
}

function describeAssistantAction(action){
  if (action && typeof action.summary === "string" && action.summary.trim()){
    const text = action.summary.trim();
    return text.charAt(0).toUpperCase() + text.slice(1);
  }
  const room = action.roomId && rooms.find(item=>item.id===action.roomId || String(item.room)===action.roomId);
  const prospect = action.prospectId && prospects.find(item=>item.id===action.prospectId);
  const client = action.clientId && temporaryClients.find(item=>item.id===action.clientId);
  const shape = action.shapeId && shapes.find(item=>item.id===action.shapeId);
  switch(action.type){
    case "create_room":
      return `Create room ${action.room}, capacity ${action.capacity}, ${action.gender}, ${action.demographic}, ${action.tenancyMode}.`;
    case "edit_room":
      return `Edit room ${room ? room.room : action.roomId}. Requested changes: ${JSON.stringify(action.changes)}.`;
    case "delete_room":
      return `Delete room ${room ? room.room : action.roomId}. The existing tracker will block deletion if residents, reservations, or temporary-client records remain.`;
    case "add_reserve_client":
      return `Add reserve client ${action.name}, ${action.gender} ${action.demographic}, check-in ${action.checkIn}${action.roomId ? `, preferred room ${rooms.find(item=>item.id===action.roomId)?.room||action.roomId} ${action.slot||""}` : ""}.`;
    case "delete_reserve_client":
      return `Delete reserve client ${prospect ? prospect.name : action.prospectId}.`;
    case "add_temporary_client":
      return `Add temporary client ${action.name}, assigned to room ${rooms.find(item=>item.id===action.roomId)?.room||action.roomId}, ${action.slot}, from ${action.start} to ${action.end}.`;
    case "checkout_temporary_client":
      return `Check out temporary client ${client ? client.name : action.clientId} and release their assigned bed.`;
    case "transfer_resident":{
      const sourceRoom = rooms.find(item=>item.id===action.sourceRoomId);
      const targetRoom = rooms.find(item=>item.id===action.targetRoomId);
      return `Transfer the resident in room ${sourceRoom ? sourceRoom.room : action.sourceRoomId}, ${action.sourceSlot}, to room ${targetRoom ? targetRoom.room : action.targetRoomId}, ${action.targetSlot}.`;
    }
    case "confirm_reservation":
      return `Confirm ${prospect ? prospect.name : "the reserve client"} for room ${rooms.find(item=>item.id===action.roomId)?.room||action.roomId}, ${action.slot}.`;
    case "cancel_reservation":
      return `Cancel the reservation for ${prospect ? prospect.name : action.prospectId}.`;
    case "create_shape":
      return `Add hallway ${action.kind} “${action.label}” as a ${action.geometry}.`;
    case "edit_shape":
      return `Edit hallway shape “${shape ? shape.label : action.shapeId}”: ${JSON.stringify(action.changes)}.`;
    case "delete_shape":
      return `Delete hallway shape “${shape ? shape.label : action.shapeId}”.`;
    case "update_tenant_contact":
      return `Change the contact number of ${action.tenant} (Room ${room ? room.room : action.roomId}, ${action.slot}) to ${action.contact}.`;
    default:
      return "Perform the requested tracker operation.";
  }
}

function findAssistantRoom(roomId){
  const matches = rooms.filter(room=>room.id===roomId || String(room.room)===String(roomId));
  if (matches.length!==1) throw new Error("The room name is missing or ambiguous; no changes were made.");
  return matches[0];
}

function assistantDateTimeValue(value, isEnd=false){
  if (!value) return "";
  const text = String(value);
  // A plain date or local date/time is used as written (a plain end date means the end of that day).
  if (/^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$/.test(text)) return toDateTimeInput(text, isEnd);
  // A stored instant (with Z / offset) is shown in this computer's local time, so it never shifts.
  const date = parseScheduleDate(text, isEnd);
  if (!date) throw new Error("A date could not be understood. Use an ISO date or date/time.");
  return new Date(date.getTime() - date.getTimezoneOffset()*60000).toISOString().slice(0,16);
}

function assistantSetRoomForm(room, changes, isNew=false){
  const values = {
    room:changes.room ?? (room && room.room) ?? "",
    type:changes.type ?? (room && room.type) ?? "Room",
    gender:changes.gender ?? (room && room.gender) ?? "Mixed",
    demographic:changes.demographic ?? (room && room.demographic) ?? "Mixed",
    tenancyMode:changes.tenancyMode ?? (room && room.tenancyMode) ?? "Bedspace"
  };
  document.getElementById("rmRoomNumber").value = values.room;
  document.getElementById("rmType").value = values.type;
  document.getElementById("rmGender").value = values.gender;
  document.getElementById("rmDemographic").value = values.demographic;
  document.getElementById("rmTenancyMode").value = values.tenancyMode;
  if (typeof changes.ac === "boolean") document.getElementById("rmAc").value = String(changes.ac);   // "set S-110 to aircon"
  const capacity = changes.capacity ?? (room ? room.beds.length : 4);
  if (!Number.isInteger(capacity) || capacity<1 || capacity>20) throw new Error("Room capacity must be between 1 and 20 beds.");
  setCapacity(capacity);
  const rows = Array.from(document.querySelectorAll("#bedsEditor .bed-edit-row"));
  const baseBeds = room ? room.beds : [];
  const bedChanges = Array.isArray(changes.bedChanges) ? changes.bedChanges : [];
  const initialBeds = Array.isArray(changes.beds) ? changes.beds : [];
  if (isNew && initialBeds.length>capacity) throw new Error("Room bed details cannot exceed its capacity.");
  if (!isNew && bedChanges.some(edit=>!room.beds.some(bed=>bed.slot===edit.slot))) throw new Error("One of the specified beds no longer exists.");
  rows.forEach((row,index)=>{
    const old = baseBeds[index] || {};
    let next = isNew ? (initialBeds[index] || {}) : {};
    if (!isNew){
      const slot = old.slot || "Bed " + (index+1);
      const edits = bedChanges.filter(item=>item.slot===slot);
      if (edits.length>1) throw new Error("A bed change refers to the same bed more than once.");
      next = edits[0] || {};
    }
    const tenant = Object.prototype.hasOwnProperty.call(next,"tenant") ? next.tenant : old.tenant;
    row.querySelector(".be-tenant").value = tenant || "";
    row.querySelector(".be-demographic").value = next.residentType || old.residentType || "Student";
    row.querySelector(".be-gender").value = next.residentGender || old.residentGender || "Unspecified";
    row.querySelector(".be-start").value = assistantDateTimeValue(Object.prototype.hasOwnProperty.call(next,"start") ? next.start : old.start);
    row.querySelector(".be-end").value = assistantDateTimeValue(Object.prototype.hasOwnProperty.call(next,"end") ? next.end : old.end, true);
  });
}

async function applyAssistantAction(action, expectedUid=currentUser && currentUser.uid){
  const invalid = validateAssistantAction(action);
  if (invalid) throw new Error(invalid);
  if (!currentUser || !currentUser.uid || currentUser.uid !== expectedUid) throw new Error("Your sign-in expired. Sign in again before applying a change.");

  switch(action.type){
    case "create_room":{
      openRoomModal(null);
      assistantSetRoomForm(null,{...action,type:action.roomType||"Room"},true);
      await saveRoom();
      if (document.getElementById("roomModalBackdrop").classList.contains("open")) throw new Error("The room was not saved. Review the room form validation message.");
      return;
    }
    case "edit_room":{
      const room = findAssistantRoom(action.roomId);
      openRoomModal(room.id);
      assistantSetRoomForm(room,action.changes);
      await saveRoom();
      if (document.getElementById("roomModalBackdrop").classList.contains("open")) throw new Error("The room was not saved. Review the room form validation message.");
      return;
    }
    case "delete_room":{
      const room = findAssistantRoom(action.roomId);
      await deleteRoom(room.id);
      return;
    }
    case "checkout_tenant":{
      const room = findAssistantRoom(action.roomId);
      const index = room.beds.findIndex(bed=>bed.slot===action.slot);
      if (index<0) throw new Error("That bed no longer exists; nothing was changed.");
      // A good / bad record asked for in the chat is saved with the Tenant History entry (same as the Check out button).
      const rec = action.record === "good" || action.record === "bad" ? {record:action.record, reason:action.record === "bad" ? String(action.reason || "").slice(0,400) : ""} : null;
      await checkoutBed(room.id, index, rec || true);
      return;
    }
    case "add_reserve_client":{
      document.getElementById("pName").value = action.name;
      document.getElementById("pGender").value = action.gender;
      document.getElementById("pDemographic").value = action.demographic;
      document.getElementById("pCheckIn").value = assistantDateTimeValue(action.checkIn);
      document.getElementById("pCheckOut").value = assistantDateTimeValue(action.checkOut, true);
      document.getElementById("pNotes").value = action.notes || "";
      refreshBedTargetSelectors();
      if (action.roomId || action.slot){
        const room = findAssistantRoom(action.roomId);
        const bed = room.beds.find(item=>item.slot===action.slot);
        if (!bed) throw new Error("The preferred bed was not found; no reserve client was added.");
        const option = Array.from(document.getElementById("pDesiredBed").options)
          .find(item=>JSON.parse(item.value || "[]")[0]===room.id && JSON.parse(item.value || "[]")[1]===room.beds.indexOf(bed));
        if (option) document.getElementById("pDesiredBed").value = option.value;
        // The reserve form keeps its chosen bed in reserveChoice (js/16-reserve-group.js); the bed is re-checked when it is saved.
        if (typeof reserveChoice !== "undefined"){
          if (typeof reserveMode !== "undefined" && reserveMode !== "single") throw new Error("Switch Reserved Clients to Single first; no reserve client was added.");
          reserveChoice = {roomId:room.id, slots:[bed.slot]};
        }else if (!option) throw new Error("That bed is not currently an eligible match; no reserve client was added.");
      }
      await addProspect();
      return;
    }
    case "delete_reserve_client":
      await deleteProspect(action.prospectId);
      return;
    case "add_temporary_client":{
      const room = findAssistantRoom(action.roomId);
      const index = room.beds.findIndex(item=>item.slot===action.slot);
      if (index<0) throw new Error("The specified bed was not found; no temporary client was added.");
      document.getElementById("tName").value = action.name;
      document.getElementById("tGender").value = action.gender;
      document.getElementById("tStart").value = assistantDateTimeValue(action.start);
      document.getElementById("tEnd").value = assistantDateTimeValue(action.end, true);
      document.getElementById("tNotes").value = action.notes || "";
      refreshBedTargetSelectors();
      const targetValue = JSON.stringify([room.id,index]);
      const target = Array.from(document.getElementById("tTargetBed").options).find(option=>option.value===targetValue);
      if (!target) throw new Error("That bed is no longer vacant or compatible; no temporary client was added.");
      document.getElementById("tTargetBed").value = targetValue;
      await addTemporaryClientDirect();
      return;
    }
    case "checkout_temporary_client":
      await checkoutTemporaryClient(action.clientId, "skip-record");
      return;
    case "transfer_resident":{
      const source = findAssistantRoom(action.sourceRoomId);
      const target = findAssistantRoom(action.targetRoomId);
      const sourceIndex = source.beds.findIndex(bed=>bed.slot===action.sourceSlot);
      const targetIndex = target.beds.findIndex(bed=>bed.slot===action.targetSlot);
      if (sourceIndex<0 || targetIndex<0) throw new Error("The specified source or target bed no longer exists.");
      openTransferModal(source.id,sourceIndex);
      const targetValue = JSON.stringify([target.id,targetIndex]);
      const select = document.getElementById("transferTarget");
      if (!Array.from(select.options).some(option=>option.value===targetValue)) throw new Error("That target bed is no longer vacant or compatible.");
      select.value = targetValue;
      await confirmBedTransfer();
      return;
    }
    case "confirm_reservation":
      await confirmReservation(action.prospectId,action.roomId,action.slot);
      return;
    case "cancel_reservation":
      await cancelReservation(action.prospectId);
      return;
    case "create_shape":
      openShapeModal(null);
      document.getElementById("shapeLabel").value = action.label;
      document.getElementById("shapeKind").value = action.kind;
      document.getElementById("shapeGeometry").value = action.geometry;
      document.getElementById("shapeColor").value = /^#[0-9a-f]{6}$/i.test(action.color||"") ? action.color : "#dce8e4";
      await saveShape();
      return;
    case "edit_shape":
      openShapeModal(action.shapeId);
      if (Object.prototype.hasOwnProperty.call(action.changes,"label")) document.getElementById("shapeLabel").value = action.changes.label;
      if (Object.prototype.hasOwnProperty.call(action.changes,"kind")) document.getElementById("shapeKind").value = action.changes.kind;
      if (Object.prototype.hasOwnProperty.call(action.changes,"geometry")) document.getElementById("shapeGeometry").value = action.changes.geometry;
      if (/^#[0-9a-f]{6}$/i.test(action.changes.color||"")) document.getElementById("shapeColor").value = action.changes.color;
      await saveShape();
      return;
    case "delete_shape":
      openShapeModal(action.shapeId);
      await deleteShape();
      return;
    case "update_tenant_contact":{
      // Same rules as the Tenant Information form: one transaction, the bed must still hold this tenant.
      const room = findAssistantRoom(action.roomId);
      const index = room.beds.findIndex(bed=>bed.slot===action.slot);
      const bed = room.beds[index];
      const existing = bed ? tiRecordForBed(bed) : null;
      const ref = existing ? userCollection("tenants").doc(existing.id) : userCollection("tenants").doc();
      const roomRef = userCollection("rooms").doc(room.id);
      await db.runTransaction(async tx=>{
        const [snap, roomSnap] = await Promise.all([tx.get(ref), tx.get(roomRef)]);
        if (!roomSnap.exists) throw new Error("The room no longer exists.");
        const beds = roomSnap.data().beds.slice(), cur = beds[index];
        if (!cur || tiNorm(cur.tenant) !== tiNorm(action.tenant)) throw new Error("This bed changed. Nothing was saved.");
        if (snap.exists) tx.update(ref, {contact:action.contact, updatedAt:sqlServerTimestamp()});
        else tx.set(ref, {name:cur.tenant, contact:action.contact, address:null, ec1:null, ec2:null, photoVersion:null, updatedAt:sqlServerTimestamp()});
        if (cur.tenantId !== ref.id){ beds[index] = {...cur, tenantId:ref.id}; tx.update(roomRef, {beds}); }
      });
      return;
    }
    default:
      throw new Error("That tracker operation is not supported.");
  }
}
