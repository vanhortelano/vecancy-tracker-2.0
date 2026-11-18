import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const BASE = "http://127.0.0.1:8099";
const now = () => Math.floor(Date.now() / 1000);
let currentToken = null;
globalThis.window = globalThis;
globalThis.document = { hidden: false, addEventListener() {} };
const realFetch = fetch;
globalThis.fetch = (u, o) => realFetch(BASE + u, o);
vm.runInThisContext(readFileSync(new URL("../../sqlstore.js", import.meta.url), "utf8"));
const S = window.SQLSTORE, db = S.db;
S.setTokenProvider(async () => currentToken);
const tok = (uid, e = `${uid}@gmail.com`) => `${uid}|${e}|1|google.com|1`;
const as = (uid) => { currentToken = tok(uid); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function register(uid, name) {
  const r = await realFetch(BASE + "/api/account/register", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + tok(uid) }, body: JSON.stringify({ username: name, password: "password1" }) });
  assert.equal(r.status, 200, await r.text());
}
const results = [];
const test = async (name, fn) => { try { await fn(); results.push(["PASS", name]); } catch (e) { results.push(["FAIL", name + " :: " + (e.stack || e)]); } };

await register("ua", "user-a"); await register("ub", "user-b");
const col = (uid, name) => db.collection("users").doc(uid).collection(name);

await test("add/get/update/delete + orderBy/limit + data() copies", async () => {
  as("ua");
  const r1 = await col("ua", "rooms").add({ room: "B", capacity: 1, beds: [{ slot: "Bed 1", tenant: null }] });
  const r2 = await col("ua", "rooms").add({ room: "A", capacity: 1, beds: [{ slot: "Bed 1", tenant: "Z" }] });
  assert.equal(r1.id.length, 20);
  const snap = await col("ua", "rooms").orderBy("room").get();
  assert.deepEqual(snap.docs.map((d) => d.data().room), ["A", "B"]);
  assert.equal((await col("ua", "rooms").limit(1).get()).size, 1);
  const d = (await r2.get()); d.data().beds[0].tenant = "mutated";
  assert.equal(d.data().beds[0].tenant, "Z");                    // callers cannot corrupt the snapshot
  await r2.update({ gender: "Female" });
  assert.equal((await r2.get()).data().room, "A");
  await r1.delete();
  assert.equal((await r1.get()).exists, false);
  assert.equal((await col("ua", "rooms").get()).empty, false);
});

await test("timestamps and server timestamps behave like before", async () => {
  as("ua");
  const ref = col("ua", "tenant_history").doc();
  await ref.set({ tenant: "T", leftAt: S.serverTimestamp(), expireAt: S.Timestamp.fromMillis(Date.now() + 86400000) });
  const d = (await ref.get()).data();
  assert.ok(typeof d.leftAt.toDate().getTime() === "number" && d.expireAt.toMillis() > Date.now());
  const old = await col("ua", "tenant_history").where("expireAt", "<=", S.Timestamp.now()).limit(200).get();
  assert.equal(old.empty, true);
});

await test("concurrent read-modify-write transactions never lose an update", async () => {
  as("ua");
  const ref = await col("ua", "rooms").add({ room: "C", capacity: 0, beds: [], counter: 0 });
  await Promise.all(Array.from({ length: 8 }, () => db.runTransaction(async (tx) => {
    const s = await tx.get(ref);
    await sleep(15);                                              // widen the race window
    tx.update(ref, { counter: s.data().counter + 1 });
  })));
  assert.equal((await ref.get()).data().counter, 8);
});

await test("transaction that throws writes nothing; batch is all-or-nothing", async () => {
  as("ua");
  const ref = await col("ua", "rooms").add({ room: "D", capacity: 0, beds: [], counter: 0 });
  await assert.rejects(db.runTransaction(async (tx) => { await tx.get(ref); tx.update(ref, { counter: 99 }); throw new Error("nope"); }), /nope/);
  assert.equal((await ref.get()).data().counter, 0);
  const b = db.batch();
  b.set(col("ua", "shapes").doc("s1"), { label: "ok" });
  b.set(col("ub", "shapes").doc("s2"), { label: "not mine" });    // belongs to someone else
  await assert.rejects(b.commit(), (e) => e.code === "permission-denied");
  assert.equal((await col("ua", "shapes").doc("s1").get()).exists, false);
});

await test("another account's data is refused with permission-denied", async () => {
  as("ub");
  await assert.rejects(col("ua", "rooms").get(), (e) => e.code === "permission-denied");
  await assert.rejects(col("ua", "rooms").doc("x").set({ room: "hack" }), (e) => e.code === "permission-denied");
  assert.equal((await col("ub", "rooms").get()).size, 0);
});

await test("onSnapshot: initial callback, change callback, no repeat, unsubscribe, error callback", async () => {
  as("ua");
  const seen = [];
  const unsub = col("ua", "prospects").orderBy("checkIn").onSnapshot((s) => seen.push(s.docs.map((d) => d.data().name)));
  await sleep(300);
  assert.deepEqual(seen, [[]]);                                   // initial (empty) snapshot arrives once
  await col("ua", "prospects").add({ name: "P1", checkIn: "2026-01-01" });
  await sleep(300);                                               // own writes refresh immediately
  assert.deepEqual(seen.at(-1), ["P1"]);
  const n = seen.length; await sleep(900); assert.equal(seen.length, n);   // unchanged data => no extra callbacks
  unsub();
  await col("ua", "prospects").add({ name: "P2", checkIn: "2026-01-02" });
  await sleep(300); assert.equal(seen.length, n);                 // unsubscribed => silent
  let err = null;
  as("ub");
  const un2 = col("ua", "prospects").onSnapshot(() => {}, (e) => { err = e; });
  await sleep(300); un2();
  assert.equal(err && err.code, "permission-denied");
});

await test("doc listener sees remote changes within the poll interval", async () => {
  as("ua");
  const ref = col("ua", "settings").doc("viewerAccess");
  const events = [];
  const unsub = ref.onSnapshot((s) => events.push(s.exists ? s.data().enabled : "none"));
  await sleep(300);
  await realFetch(BASE + "/api/commit", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + tok("ua") }, body: JSON.stringify({ writes: [{ op: "set", path: ["users", "ua", "settings", "viewerAccess"], data: { code: "dorm-xx", enabled: true } }] }) });
  await sleep(4800);                                              // a change made elsewhere (another tab/device)
  unsub();
  assert.deepEqual(events, ["none", true]);
});

for (const [s, n] of results) console.log(s, n);
process.exit(results.some((r) => r[0] === "FAIL") ? 1 : 0);
