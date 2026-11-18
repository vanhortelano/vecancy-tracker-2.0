/* vacancy-core.js — ONE set of bed/room status rules, shared by the Branch Admin page (admin.html) and the
   Dormitory Viewer (viewer.html). The Branch Admin's bedStatus()/roomVacancy() call these functions, so a bed
   has the same status, colour and count everywhere.

   Statuses (same names, colours and legend as the Branch Admin Hallway Layout / Bed Matrix):
     vacant · occupied · reserved · temporary (temporary occupied) · overdue · soon (checkout ≤ 48 h)
   "Upcoming vacancy" is NOT a separate status: it is an occupied bed (occupied / soon / temporary) whose expected
   check-out falls within the next UPCOMING_DAYS days. It is still counted as occupied, never as vacant.

   The functions only need: bed.tenant (truthy = someone is in the bed), bed.start, bed.end, bed.reservedFor
   (truthy = held by a reservation), bed.residentType; room.tenancyMode. The viewer copy of a room carries
   tenant:true/false instead of the name, so no tenant identity is ever needed here. */
window.VTCore = (function(){
  const DAY = 864e5, UPCOMING_DAYS = 7;
  const STATUS = {
    vacant:{label:"Vacant", color:"var(--vacant)"},
    occupied:{label:"Occupied", color:"var(--occupied)"},
    reserved:{label:"Reserved", color:"var(--reserved)"},
    temporary:{label:"Temporary occupied", color:"var(--temporary)"},
    overdue:{label:"Overdue", color:"var(--overdue)"},
    soon:{label:"Checkout ≤48h", color:"var(--soon)"}
  };
  const ORDER = ["vacant","occupied","soon","temporary","overdue","reserved"];
  const OCCUPIED = ["occupied","soon","temporary","overdue"];

  function parseDate(value, isEnd){
    if (!value) return null;
    const text = String(value);
    if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return new Date(text + (isEnd ? "T23:59:59" : "T00:00:00"));
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function bedStatus(bed, room, now){
    now = now === undefined ? Date.now() : now;
    const start = parseDate(bed.start), end = parseDate(bed.end, true);
    if (room && room.tenancyMode === "Whole Room" && !bed.tenant){
      if (room.beds.some(item=>item.tenant && bedStatus(item, null, now) !== "reserved")) return "occupied";
      if (room.beds.some(item=>item.reservedFor || (item.tenant && bedStatus(item, null, now) === "reserved"))) return "reserved";
    }
    if (!bed.tenant){
      if (bed.reservedFor) return "reserved";
      return "vacant";
    }
    if (end && end.getTime() < now) return "overdue";
    if (start && start.getTime() > now) return "reserved";
    if (bed.residentType === "Temporary") return "temporary";
    if (end && end.getTime() - now <= 48 * 60 * 60 * 1000) return "soon";
    return "occupied";
  }

  function roomVacancy(r, now){
    const total = r.beds.length;
    if (r.tenancyMode === "Whole Room"){
      const status = r.beds.reduce((result,b)=>{
        const state = bedStatus(b, r, now);
        if (state === "reserved") result.reserved = true;
        else if (state !== "vacant") result.occupied = true;
        return result;
      }, {occupied:false, reserved:false});
      return {total, vacant:status.occupied || status.reserved ? 0 : total, occupied:status.occupied ? total : 0, reserved:status.reserved ? total : 0};
    }
    const vacant = r.beds.filter(b=>bedStatus(b, r, now) === "vacant").length;
    const reserved = r.beds.filter(b=>bedStatus(b, r, now) === "reserved").length;
    return {total, vacant, occupied:total - vacant - reserved, reserved};
  }

  // An occupied bed whose expected check-out is within the next `days` days (and not already past).
  function isUpcoming(bed, room, now, days){
    now = now === undefined ? Date.now() : now;
    const status = bedStatus(bed, room, now);
    if (!["occupied","soon","temporary"].includes(status)) return false;
    const end = parseDate(bed.end, true);
    return !!end && end.getTime() > now && end.getTime() <= now + (days || UPCOMING_DAYS) * DAY;
  }

  // Per-bed view for a published (name-free) room: status, dates, upcoming flag.
  function bedStates(room, now){
    now = now === undefined ? Date.now() : now;
    if (Array.isArray(room.bedInfo) && room.bedInfo.length){
      const r = {tenancyMode:room.tenancyMode, beds:room.bedInfo};
      return room.bedInfo.map((b,i)=>{
        const status = bedStatus(b, r, now);
        return {slot:b.slot || "Bed " + (i+1), status, start:b.tenant ? b.start || null : null, end:b.tenant ? b.end || null : null,
          reservedFrom:b.reservedFrom || null, upcoming:isUpcoming(b, r, now)};
      });
    }
    // older published copies only have a status per bed
    return (Array.isArray(room.beds) ? room.beds : []).map((st,i)=>({slot:"Bed " + (i+1), status:STATUS[st] ? st : "vacant", start:null, end:null, reservedFrom:null, upcoming:false}));
  }

  // Scheduled occupancy at a FUTURE moment t (used for the 30-day outlook): a tenant stays until the expected
  // check-out; someone already past check-out stays counted until the admin checks them out (we can't know when);
  // a reserved bed counts from its reservation check-in.
  function occupiedAt(b, t, now){
    now = now === undefined ? Date.now() : now;
    if (b.tenant){
      const start = parseDate(b.start), end = parseDate(b.end, true);
      if (end && end.getTime() < now) return true;
      return (!start || start.getTime() <= t) && (!end || end.getTime() > t);
    }
    if (b.reservedFor){ const from = parseDate(b.reservedFrom); return !!from && from.getTime() <= t; }
    return false;
  }

  function emptyCounts(){ return {total:0, occupied:0, vacant:0, reserved:0, upcoming:0, overdue:0, temporary:0, soon:0}; }
  // Room summary = exactly the sum of its beds (so the summary always matches the bed list).
  function summarize(states){
    const c = emptyCounts();
    states.forEach(b=>{
      c.total++;
      if (b.status === "vacant") c.vacant++;
      else if (b.status === "reserved") c.reserved++;
      else c.occupied++;
      if (b.status === "overdue") c.overdue++;
      if (b.status === "temporary") c.temporary++;
      if (b.status === "soon") c.soon++;
      if (b.upcoming) c.upcoming++;
    });
    return c;
  }

  // Filters used by the viewer (the same meanings as the Branch Admin shared filters).
  function roomMatches(room, f){
    f = f || {};
    if (f.gender && f.gender !== "all" && (room.gender || "Mixed") !== f.gender) return false;
    if (f.demographic && f.demographic !== "all"){
      const d = room.demographic || "Mixed";
      if (f.demographic === "Mixed" && ["Students","Reviewees"].includes(d)) return false;
      if (f.demographic !== "Mixed" && d !== f.demographic) return false;
    }
    if (f.room && f.room !== "all" && room.id !== f.room) return false;
    if (f.search && !String(room.room || "").toLowerCase().includes(String(f.search).toLowerCase())) return false;
    return true;
  }

  // Statistics for a scope: every number is the sum over the matching rooms' beds.
  function stats(rooms, f, now){
    const c = emptyCounts();
    let roomCount = 0, roomsWithSpace = 0;
    rooms.forEach(room=>{
      if (!roomMatches(room, f)) return;
      const s = summarize(bedStates(room, now));
      if (f && f.status === "vacant" && !s.vacant) return;
      if (f && f.status === "full" && s.vacant) return;
      if (f && f.status === "upcoming" && !s.upcoming) return;
      roomCount++;
      if (s.vacant) roomsWithSpace++;
      Object.keys(c).forEach(k=>{ c[k] += s[k]; });
    });
    return {...c, rooms:roomCount, roomsWithSpace,
      occupancyRate:c.total ? c.occupied / c.total * 100 : 0, vacancyRate:c.total ? c.vacant / c.total * 100 : 0};
  }

  function scopeLabel(f, rooms){
    const parts = [];
    if (f.gender && f.gender !== "all") parts.push({Male:"Male", Female:"Female", Mixed:"Mixed gender"}[f.gender] || f.gender);
    if (f.demographic && f.demographic !== "all") parts.push(f.demographic === "Mixed" ? "Mixed groups" : f.demographic);
    if (f.room && f.room !== "all"){ const r = (rooms || []).find(x=>x.id === f.room); parts.push("Room " + (r ? r.room : f.room)); }
    if (f.status && f.status !== "all") parts.push({vacant:"Rooms with vacancy", full:"Full rooms", upcoming:"Rooms with upcoming vacancy"}[f.status] || f.status);
    if (f.search) parts.push("“" + f.search + "”");
    return parts.length ? parts.join(" · ") : "All";
  }

  function fmtDate(v){
    const d = parseDate(v);
    if (!d) return "";
    return /^\d{4}-\d{2}-\d{2}$/.test(String(v)) ? d.toLocaleDateString([], {month:"long", day:"numeric", year:"numeric"})
      : d.toLocaleString([], {month:"long", day:"numeric", year:"numeric", hour:"numeric", minute:"2-digit"});
  }

  return {DAY, UPCOMING_DAYS, STATUS, ORDER, OCCUPIED, parseDate, bedStatus, roomVacancy, isUpcoming, bedStates,
    summarize, roomMatches, stats, scopeLabel, fmtDate, occupiedAt};
})();
