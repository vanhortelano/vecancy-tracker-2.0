// Trading-style time-series chart (canvas, no libraries). Drag to move through time, wheel / buttons to zoom.
//
//  * History is drawn from recorded observations only. Points with v === null are GAPS; nothing is invented.
//  * Line style: each segment is coloured by DIRECTION — green when vacancy went up versus the previous point,
//    red when it went down, grey when unchanged. (More vacant beds = more available inventory; not profit/loss.)
//  * Candle style: real OHLC per calendar interval (day / week / month / year) from the raw observations:
//    open = first observation, high = max, low = min, close = last. Body = open..close, wicks = high / low.
//  * Future: PURPLE only. "Confirmed" = dashed step line from contract end dates and reservations.
//    "Trend estimate" = dotted line with a shaded uncertainty band. Never mixed with the history.
//  * The value axis is fixed to ALL loaded data (history + forecast), so moving through time never reshapes
//    the historical line.
window.CChart = (function(){
  const UP = "#16a34a", DOWN = "#dc2626", FLAT = "#94a3b8", PURPLE = "#7c3aed";
  const DAYMS = 864e5;

  function intervalStart(t, unit){
    const d = new Date(t);
    if (unit === "second") return Math.floor(t / 1000) * 1000;
    if (unit === "minute") return new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes()).getTime();
    if (unit === "hour") return new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours()).getTime();
    if (unit === "day") return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    if (unit === "week"){ const s = new Date(d.getFullYear(), d.getMonth(), d.getDate()); s.setDate(s.getDate() - ((s.getDay() + 6) % 7)); return s.getTime(); }
    if (unit === "month") return new Date(d.getFullYear(), d.getMonth(), 1).getTime();
    return new Date(d.getFullYear(), 0, 1).getTime();
  }
  function intervalNext(t, unit){
    const d = new Date(t);
    if (unit === "second") return t + 1000;
    if (unit === "minute") return new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes() + 1).getTime();
    if (unit === "hour") return new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours() + 1).getTime();
    if (unit === "day") return new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).getTime();
    if (unit === "week") return new Date(d.getFullYear(), d.getMonth(), d.getDate() + 7).getTime();
    if (unit === "month") return new Date(d.getFullYear(), d.getMonth() + 1, 1).getTime();
    return new Date(d.getFullYear() + 1, 0, 1).getTime();
  }
  // Group raw observations into calendar intervals and compute Open / High / Low / Close for each.
  function ohlc(obs, unit){
    const groups = new Map();
    obs.filter(p=>p.v != null).sort((a,b)=>a.t-b.t).forEach(p=>{
      const k = intervalStart(p.t, unit);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(p);
    });
    return Array.from(groups.entries()).sort((a,b)=>a[0]-b[0]).map(([k, a])=>({
      t0:k, t1:intervalNext(k, unit), open:a[0].v, close:a[a.length-1].v,
      high:Math.max(...a.map(p=>p.v)), low:Math.min(...a.map(p=>p.v)), n:a.filter(p=>!p.carried).length}));
  }

  function create(canvas, cb){
    const ctx = canvas.getContext("2d");
    const S = {series:[], obs:[], t0:0, t1:1, latest:Date.now(), dataMin:0, exhausted:false, fmt:v=>String(Math.round(v*10)/10),
      hover:null, style:"line", unit:"day", bands:null, yLo:0, yHi:1, invert:false, zones:null};
    let drag = null, olderAt = 0;
    const R = 16, T = 14, B = 30;
    let L = 56;                     // wider when the risk colour strip is shown on the left
    const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

    function box(){
      const r = canvas.getBoundingClientRect(), d = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(r.width*d) || canvas.height !== Math.round(r.height*d)){ canvas.width = Math.round(r.width*d); canvas.height = Math.round(r.height*d); }
      ctx.setTransform(d,0,0,d,0,0);
      return {w:r.width, h:r.height};
    }
    const tx = (t, w) => L + (t - S.t0) / (S.t1 - S.t0) * (w - L - R);
    const xt = (x, w) => S.t0 + (x - L) / (w - L - R) * (S.t1 - S.t0);

    function tickLabel(t, span){
      const d = new Date(t);
      if (span <= 5*60e3) return d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"});
      if (span <= 2*DAYMS && span > 12*36e5) return d.toLocaleDateString([], {month:"short", day:"numeric"}) + " " + d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
      return span <= 2*DAYMS ? d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})
        : span <= 400*DAYMS ? d.toLocaleDateString([], {month:"short", day:"numeric"}) : d.toLocaleDateString([], {month:"short", year:"numeric"});
    }
    // value axis: from everything loaded (history, observations, forecast, band), so it never jumps while panning
    function computeY(){
      let lo = Infinity, hi = -Infinity;
      const take = v => { if (v != null && isFinite(v)){ lo = Math.min(lo, v); hi = Math.max(hi, v); } };
      S.series.forEach(s=>{ s.points.forEach(p=>take(p.v)); (s.band||[]).forEach(b=>{ take(b.lo); take(b.hi); }); });
      S.obs.forEach(p=>take(p.v));
      if (!isFinite(lo)){ lo = 0; hi = 1; }
      if (hi === lo){ hi += 1; lo = Math.max(0, lo - 1); }
      const pad = (hi - lo) * .1; S.yLo = Math.max(0, lo - pad); S.yHi = hi + pad;
      if (S.bands) S.yHi = Math.max(S.yHi, ...S.bands.map(b=>Math.min(b.to, 100)).filter(isFinite));
      // keep every risk boundary on screen so all three colours of the strip are visible
      if (S.zones){ const edges = S.zones.flatMap(z=>[z.from, z.to]).filter(v=>isFinite(v) && v > 0 && v < (S.zoneCap || Infinity));
        if (edges.length){ S.yLo = Math.min(S.yLo, Math.max(0, Math.min(...edges) * .6)); S.yHi = Math.max(S.yHi, Math.min(S.zoneCap || Infinity, Math.max(...edges) * 1.25)); } }
    }
    /* Risk colour strip at the left edge: green SAFE at the top, yellow NORMAL in the middle, red RISK at the bottom
       (vacancy metrics are drawn upside down, so high vacancy = risk sits low). Where two colours meet they blend. */
    function drawStrip(h, ty){
      if (!S.zones) return;
      const x = 6, sw = 16, top = T, bot = h - B, H = bot - top;
      const col = {safe:"#16a34a", normal:"#eab308", risk:"#dc2626"}, name = {safe:"SAFE", normal:"NORMAL", risk:"RISK"};
      const segs = S.zones.map(z=>{ const a = ty(Math.max(z.from, S.yLo)), b = ty(Math.min(z.to, S.yHi)); return {lvl:z.level, y0:Math.max(top, Math.min(a, b)), y1:Math.min(bot, Math.max(a, b))}; })
        .filter(g=>g.y1 - g.y0 > .5).sort((p,q)=>p.y0 - q.y0);
      if (!segs.length) return;
      const g = ctx.createLinearGradient(0, top, 0, bot), blend = Math.min(.05, 10 / H);
      segs.forEach(sg=>{ const a = (sg.y0 - top) / H, b = (sg.y1 - top) / H;
        g.addColorStop(Math.max(0, Math.min(1, a + (a > 0 ? blend : 0))), col[sg.lvl]); g.addColorStop(Math.max(0, Math.min(1, b - (b < 1 ? blend : 0))), col[sg.lvl]); });
      ctx.save(); ctx.fillStyle = g; ctx.beginPath(); ctx.roundRect(x, top, sw, H, 6); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = "700 9.5px 'DM Sans', sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      segs.forEach(sg=>{ const len = sg.y1 - sg.y0, label = name[sg.lvl]; if (len < ctx.measureText(label).width + 8) return;
        ctx.save(); ctx.translate(x + sw / 2, (sg.y0 + sg.y1) / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(label, 0, .5); ctx.restore(); });
      // soft tint of each zone inside the plot
      segs.forEach(sg=>{ ctx.globalAlpha = .06; ctx.fillStyle = col[sg.lvl]; ctx.fillRect(L, sg.y0, 9999, sg.y1 - sg.y0); });
      ctx.restore();
    }

    function drawCandles(w, ty){
      const candles = ohlc(S.obs, S.unit);
      candles.forEach(c=>{
        const x0 = tx(c.t0, w), x1 = tx(c.t1, w);
        if (x1 < L || x0 > w - R) return;
        const bw = Math.max(2, Math.min(40, (x1 - x0) * .62)), x = (x0 + x1) / 2;
        const col = c.close > c.open ? UP : c.close < c.open ? DOWN : FLAT;
        ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.moveTo(x, ty(c.high)); ctx.lineTo(x, ty(Math.max(c.open, c.close))); ctx.stroke();   // upper wick
        ctx.beginPath(); ctx.moveTo(x, ty(Math.min(c.open, c.close))); ctx.lineTo(x, ty(c.low)); ctx.stroke();     // lower wick
        const yo = ty(c.open), yc = ty(c.close), top = Math.min(yo, yc), bh = Math.abs(yo - yc);
        if (bh < 1.5){ ctx.beginPath(); ctx.moveTo(x - bw/2, yo); ctx.lineTo(x + bw/2, yo); ctx.lineWidth = 2; ctx.stroke(); }   // doji: open = close
        else { ctx.fillRect(x - bw/2, top, bw, bh); }
      });
      return candles;
    }
    function drawHistoryLine(s, w, ty){
      let prev = null;
      const live = Date.now();
      ctx.lineWidth = s.combined ? 3.2 : 2.6; ctx.lineCap = "round"; ctx.setLineDash([]);
      s.points.forEach(p0=>{
        const p = p0.held ? {...p0, t:Math.max(p0.t, live)} : p0;      // the state in effect continues up to this second
        if (p.v == null){ prev = null; return; }
        if (prev){
          ctx.strokeStyle = p.v > prev.v ? UP : p.v < prev.v ? DOWN : FLAT;
          ctx.beginPath(); ctx.moveTo(tx(prev.t, w), ty(prev.v)); ctx.lineTo(tx(p.t, w), ty(p.v)); ctx.stroke();
        }
        prev = p;
      });
      const shown = s.points.filter(p=>p.v != null && !p.held && p.t >= S.t0 && p.t <= S.t1);
      if (shown.length && shown.length < 160) shown.forEach((p,i)=>{
        const before = s.points[s.points.indexOf(p) - 1];
        ctx.fillStyle = before && before.v != null ? (p.v > before.v ? UP : p.v < before.v ? DOWN : FLAT) : FLAT;
        ctx.beginPath(); ctx.arc(tx(p.t, w), ty(p.v), 2.6, 0, 7); ctx.fill();
      });
      // name tag in the series colour at the last visible point (identifies the dormitory)
      const last = shown[shown.length - 1];
      if (last && S.series.filter(x=>!x.forecast).length > 1){
        const x = Math.min(tx(last.t, w) + 6, w - R - 4), y = ty(last.v);
        ctx.font = "600 10px 'DM Sans', sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
        const label = s.name, lw = ctx.measureText(label).width + 10;
        ctx.fillStyle = s.color; ctx.beginPath(); ctx.roundRect(Math.min(x, w - R - lw), y - 8, lw, 16, 5); ctx.fill();
        ctx.fillStyle = "#fff"; ctx.fillText(label, Math.min(x, w - R - lw) + 5, y);
      }
    }
    function drawForecast(s, w, ty){
      if (s.band && s.band.length > 1){
        ctx.save(); ctx.globalAlpha = .14; ctx.fillStyle = PURPLE; ctx.beginPath();
        s.band.forEach((b,i)=>{ const x = tx(b.t, w), y = ty(b.hi); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
        s.band.slice().reverse().forEach(b=>ctx.lineTo(tx(b.t, w), ty(b.lo)));
        ctx.closePath(); ctx.fill(); ctx.restore();
      }
      ctx.strokeStyle = PURPLE; ctx.lineWidth = s.kind === "confirmed" ? 2.4 : 2; ctx.lineCap = "round";
      ctx.setLineDash(s.kind === "confirmed" ? [8, 5] : [2, 5]);
      ctx.beginPath();
      const live = Date.now();
      s.points.forEach((p0,i)=>{
        const p = !i && p0.t < live && s.points.length > 1 && s.points[1].t > live ? {...p0, t:live} : p0;   // the forecast starts at NOW
        const x = tx(p.t, w), y = ty(p.v);
        if (!i) ctx.moveTo(x, y);
        else if (s.kind === "confirmed"){ ctx.lineTo(x, ty(s.points[i-1].v)); ctx.lineTo(x, y); }   // step: changes happen on the date
        else ctx.lineTo(x, y);
      });
      ctx.stroke(); ctx.setLineDash([]);
      if (s.kind === "confirmed") s.points.forEach((p,i)=>{ if (!i) return; const x = tx(p.t, w); if (x < L || x > w - R) return; ctx.fillStyle = css("--card") || "#fff"; ctx.beginPath(); ctx.arc(x, ty(p.v), 3, 0, 7); ctx.fill(); ctx.strokeStyle = PURPLE; ctx.lineWidth = 1.5; ctx.stroke(); });
    }

    function draw(){
      const {w, h} = box(); ctx.clearRect(0, 0, w, h);
      const ink = css("--ink"), soft = css("--soft") || css("--ink-soft"), line = css("--line");
      const span = S.t1 - S.t0, lo = S.yLo, hi = S.yHi;
      L = S.zones ? 78 : 56;
      const ty = v => S.invert ? T + ((v - lo) / (hi - lo)) * (h - T - B) : T + (1 - (v - lo) / (hi - lo)) * (h - T - B);
      ctx.save(); ctx.beginPath(); ctx.rect(0, 0, w - R, h); ctx.clip(); drawStrip(h, ty); ctx.restore();
      ctx.font = "11px 'DM Sans', sans-serif"; ctx.textBaseline = "middle";
      // risk bands (from the configured thresholds, only for the vacancy-rate view)
      if (S.bands && !S.zones) S.bands.forEach(b=>{
        const yTop = ty(Math.min(b.to, hi)), yBot = ty(Math.max(b.from, lo));
        if (yBot <= yTop) return;
        ctx.save(); ctx.globalAlpha = .09; ctx.fillStyle = b.color; ctx.fillRect(L, yTop, w - L - R, yBot - yTop); ctx.restore();
        ctx.save(); ctx.fillStyle = b.color; ctx.font = "600 10px 'DM Sans', sans-serif"; ctx.textAlign = "right"; ctx.fillText(b.label, w - R - 4, yTop + 9); ctx.restore();
      });
      ctx.strokeStyle = line; ctx.fillStyle = soft; ctx.lineWidth = 1; ctx.textAlign = "right";
      for (let i = 0; i <= 4; i++){ const v = lo + (hi - lo) * i / 4, y = ty(v); ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(w - R, y); ctx.stroke(); ctx.fillText(S.fmt(v), L - 8, y); }
      ctx.textAlign = "center"; ctx.textBaseline = "top";
      for (let i = 0; i <= 5; i++){ const t = S.t0 + span * i / 5, x = tx(t, w); ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, h - B); ctx.stroke(); ctx.fillText(tickLabel(t, span), Math.min(Math.max(x, L + 22), w - R - 22), h - B + 8); }
      ctx.save(); ctx.beginPath(); ctx.rect(L, T - 2, w - L - R, h - T - B + 4); ctx.clip();
      // NOW marker: left = recorded history, right = forecast (purple)
      S.latest = Math.max(S.latest, Date.now());
      const nx = tx(S.latest, w);
      if (nx > L && nx < w - R){
        ctx.save(); ctx.fillStyle = PURPLE; ctx.globalAlpha = .04; ctx.fillRect(nx, T, w - R - nx, h - T - B); ctx.restore();
        ctx.save(); ctx.strokeStyle = soft; ctx.setLineDash([2, 5]); ctx.beginPath(); ctx.moveTo(nx, T); ctx.lineTo(nx, h - B); ctx.stroke(); ctx.setLineDash([]);
        ctx.fillStyle = soft; ctx.font = "10px 'DM Sans', sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillText("NOW", nx + 4, T + 2);
        ctx.fillStyle = PURPLE; ctx.fillText("FORECAST (estimated) →", nx + 4, T + 14);
        ctx.fillStyle = soft; ctx.textAlign = "right"; ctx.fillText("← RECORDED HISTORY", nx - 6, T + 14); ctx.restore();
      }
      let candles = null;
      if (S.style === "candle") candles = drawCandles(w, ty);
      else S.series.filter(s=>!s.forecast).forEach(s=>drawHistoryLine(s, w, ty));
      S.series.filter(s=>s.forecast).forEach(s=>drawForecast(s, w, ty));
      ctx.restore();
      const anyHist = S.style === "candle" ? S.obs.some(p=>p.v != null && p.t >= S.t0 && p.t <= S.t1)
        : S.series.some(s=>!s.forecast && s.points.some(p=>p.v != null && p.t >= S.t0 && p.t <= S.t1));
      const anyFc = S.series.some(s=>s.forecast && s.points.some(p=>p.t >= S.t0 && p.t <= S.t1));
      if (!anyHist && !anyFc){
        ctx.fillStyle = soft; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.font = "13px 'DM Sans', sans-serif";
        ctx.fillText("No recorded data in this period", (L + w - R) / 2, (T + h - B) / 2);
      }
      // zoom level (hours → minutes → seconds)
      const lvl = span >= 2*DAYMS ? Math.round(span / DAYMS) + " days" : span >= 2*36e5 ? Math.round(span / 36e5) + " hours" : span >= 2*60e3 ? Math.round(span / 60e3) + " minutes" : Math.max(1, Math.round(span / 1000)) + " seconds";
      ctx.save(); ctx.font = "600 10px 'DM Sans', sans-serif"; ctx.fillStyle = soft; ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillText("Showing " + lvl, L + 6, T + 4); ctx.restore();
      if (S.hover != null) drawTooltip(w, h, ty, candles, ink, soft, line);
    }

    function drawTooltip(w, h, ty, candles, ink, soft, line){
      const span = S.t1 - S.t0, x = tx(S.hover, w);
      ctx.strokeStyle = soft; ctx.setLineDash([4, 4]); ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, h - B); ctx.stroke(); ctx.setLineDash([]);
      let head = "", rows = [];
      const c = candles && candles.find(k=>S.hover >= k.t0 && S.hover < k.t1);
      if (c){
        const fmtD = t=>new Date(t).toLocaleDateString([], {month:"short", day:"numeric", year:"numeric"});
        head = S.unit === "second" || S.unit === "minute" ? new Date(c.t0).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"}) + " – " + new Date(c.t1).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"})
          : S.unit === "hour" ? new Date(c.t0).toLocaleString([], {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit"}) + " – " + new Date(c.t1).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})
          : S.unit === "day" ? fmtD(c.t0) : fmtD(c.t0) + " – " + fmtD(c.t1 - 1);
        const col = c.close > c.open ? UP : c.close < c.open ? DOWN : FLAT;
        rows = [["Open", c.open], ["High", c.high], ["Low", c.low], ["Close", c.close]].map(([n, v])=>({c:col, n, v:S.fmt(v)}));
        rows.push({c:soft, n:c.n ? "Records in this period" : "No new record (state carried)", v:c.n ? String(c.n) : ""});
      } else {
        S.series.forEach(s=>{
          let best = null;
          if (s.step || s.kind === "confirmed"){        // the value IN EFFECT at that moment (records stay valid until the next one)
            const pts = s.points.filter(p=>p.v != null);
            if (pts.length && S.hover >= pts[0].t && S.hover <= pts[pts.length-1].t) pts.forEach(p=>{ if (p.t <= S.hover) best = p; });
            if (best) best = {...best, t:S.hover};
          } else s.points.forEach(p=>{ if (p.v != null && (!best || Math.abs(p.t - S.hover) < Math.abs(best.t - S.hover))) best = p; });
          if (best && Math.abs(best.t - S.hover) <= Math.max(span / 40, 36e5)){
            if (!head) head = new Date(best.t).toLocaleString([], span <= 2*36e5 ? {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit", second:"2-digit"}
              : {month:"short", day:"numeric", year:"numeric", hour:"2-digit", minute:"2-digit"});
            rows.push({c:s.forecast ? PURPLE : s.color, n:s.name + (s.forecast ? " (estimate)" : ""), v:S.fmt(best.v)});
          }
        });
      }
      if (!rows.length) return;
      ctx.font = "12px 'DM Sans', sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
      const bw = Math.max(ctx.measureText(head).width, ...rows.map(r=>ctx.measureText(r.n + "  " + r.v).width + 18)) + 20, bh = 24 + rows.length * 18;
      let bx = x + 12; if (bx + bw > w - R) bx = x - bw - 12;
      ctx.fillStyle = css("--card") || "#fff"; ctx.strokeStyle = line; ctx.beginPath(); ctx.roundRect(bx, T + 4, bw, bh, 10); ctx.fill(); ctx.stroke();
      ctx.fillStyle = soft; ctx.fillText(head, bx + 10, T + 18);
      rows.forEach((r, i)=>{ const y = T + 38 + i * 18; ctx.fillStyle = r.c; ctx.beginPath(); ctx.arc(bx + 14, y, 4, 0, 7); ctx.fill(); ctx.fillStyle = ink; ctx.fillText(r.n + "  " + r.v, bx + 26, y); });
    }

    function clamp(){
      cb && cb.onWindow && cb.onWindow(S.t0, S.t1);
      if (S.t0 < S.dataMin && !S.exhausted && Date.now() - olderAt > 800){ olderAt = Date.now(); cb && cb.needOlder && cb.needOlder(); }
    }
    canvas.style.touchAction = "pan-y pinch-zoom"; canvas.style.cursor = "grab";
    canvas.addEventListener("pointerdown", e => { drag = {x:e.clientX, t0:S.t0, t1:S.t1}; canvas.setPointerCapture(e.pointerId); canvas.style.cursor = "grabbing"; });
    canvas.addEventListener("pointermove", e => {
      const r = canvas.getBoundingClientRect(), w = r.width;
      if (drag){ const dt = (e.clientX - drag.x) / (w - L - R) * (drag.t1 - drag.t0); S.t0 = drag.t0 - dt; S.t1 = drag.t1 - dt; clamp(); S.hover = null; }
      else S.hover = xt(e.clientX - r.left, w);
      draw();
    });
    const end = () => { drag = null; canvas.style.cursor = "grab"; };
    canvas.addEventListener("pointerup", end); canvas.addEventListener("pointercancel", end);
    canvas.addEventListener("pointerleave", () => { S.hover = null; draw(); });
    canvas.addEventListener("wheel", e => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.25 : .8, xt(e.clientX - canvas.getBoundingClientRect().left, canvas.getBoundingClientRect().width)); }, {passive:false});
    function zoom(f, at){
      const span = Math.min(60 * 365 * DAYMS, Math.max(10e3, (S.t1 - S.t0) * f)), c = at == null ? (S.t0 + S.t1) / 2 : at, k = (c - S.t0) / (S.t1 - S.t0);
      S.t0 = c - span * k; S.t1 = S.t0 + span; clamp(); draw();
    }
    new ResizeObserver(draw).observe(canvas);
    // when the window is short (≤ 3 hours) and shows NOW, redraw every second so the current state keeps moving
    setInterval(()=>{ if (canvas.offsetParent && !drag && S.t1 - S.t0 <= 3*36e5 && S.t1 >= Date.now() - 1000 && S.t0 <= Date.now()) draw(); }, 1000);

    return {
      setData(series, o){ S.series = series; S.obs = (o && o.obs) || []; Object.assign(S, o || {}); computeY(); draw(); },
      setWindow(a, b){ S.t0 = a; S.t1 = b; draw(); },
      zoom, redraw: draw,
      centerOn(t){ const sp = S.t1 - S.t0; S.t0 = t - sp/2; S.t1 = t + sp/2; clamp(); draw(); },
      window: () => [S.t0, S.t1]
    };
  }
  return {create, ohlc, intervalStart, intervalNext};
})();
