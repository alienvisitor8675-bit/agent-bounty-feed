// Unit tests for feed integrity (no network). Run: node paid-worker/unit.test.mjs
import assert from "node:assert/strict";
import w, { _test as T } from "./worker.js";
import { mcp } from "./mcp.js";
let n = 0; const ok = (name, fn) => { fn(); n++; console.log("ok -", name); };
const q = (s) => { const r = T.parseQuery(new URLSearchParams(s)); assert.deepEqual(r.errs, []); return r.opts; };
const GEN = "2026-10-28T00:00:00Z";

// ---- Bug 1: unknown USD stays unknown
const usdFeed = { generated_at: GEN, items: [
  { id: "taskmarket:TSK-Y7YSTT0V", reward: 100, currency: "OUSD", est_usd: null, first_seen: "2026-10-27T01:00:00Z" },
  { id: "taskmarket:TSK-FXES37VN", reward: 50, currency: "OUSD", est_usd: null, first_seen: "2026-10-27T02:00:00Z" },
  { id: "x:usdc50", reward: 50, currency: "USDC", est_usd: 50, first_seen: "2026-10-27T03:00:00Z" },
  { id: "x:usdc50-noest", reward: 50, currency: "USDC", first_seen: "2026-10-27T03:30:00Z" },
  { id: "x:zero", reward: 0, currency: "USD", est_usd: 0, first_seen: "2026-10-27T04:00:00Z" },
  { id: "x:bad", reward: "lots", currency: "USD", est_usd: "50", first_seen: "2026-10-27T05:00:00Z" },
  { id: "x:nan", reward: NaN, currency: "USDC", first_seen: "2026-10-27T06:00:00Z" },
  { id: "x:none", first_seen: "2026-10-27T07:00:00Z" },
] };
ok("knownUsd: OUSD/null -> null; USDC explicit -> 50; USD-like reward fallback; malformed -> null", () => {
  const by = Object.fromEntries(usdFeed.items.map(i => [i.id, T.knownUsd(i)]));
  assert.equal(by["taskmarket:TSK-Y7YSTT0V"], null); assert.equal(by["taskmarket:TSK-FXES37VN"], null);
  assert.equal(by["x:usdc50"], 50); assert.equal(by["x:usdc50-noest"], 50); assert.equal(by["x:zero"], 0);
  assert.equal(by["x:bad"], null); assert.equal(by["x:nan"], null); assert.equal(by["x:none"], null);
});
ok("min_usd=50 excludes 100 OUSD/null and 50 OUSD/null, keeps explicit 50 USDC", () => {
  const ids = T.applyFilter(usdFeed, q("min_usd=50")).items.map(i => i.id).sort();
  assert.deepEqual(ids, ["x:usdc50", "x:usdc50-noest"]);
});
ok("min_usd=0.01 excludes zero/malformed/unknown", () => {
  const ids = T.applyFilter(usdFeed, q("min_usd=0.01")).items.map(i => i.id);
  for (const bad of ["x:zero", "x:bad", "x:nan", "x:none", "taskmarket:TSK-Y7YSTT0V"]) assert.ok(!ids.includes(bad), bad);
});
ok("sort=reward puts unknown USD after known values", () => {
  const ids = T.applyFilter(usdFeed, q("sort=reward")).items.map(i => i.id);
  const firstNull = ids.findIndex(id => T.knownUsd(usdFeed.items.find(i => i.id === id)) === null);
  assert.ok(ids.slice(firstNull).every(id => T.knownUsd(usdFeed.items.find(i => i.id === id)) === null));
  assert.deepEqual(ids.slice(0, 2).sort(), ["x:usdc50", "x:usdc50-noest"]);
});

// ---- Bug 2: gap-free delta pages
const mk = (k, ts) => ({ id: `t:${String(k).padStart(3, "0")}`, reward: k, currency: "USD", est_usd: k, first_seen: ts });
const pad = (m) => `2026-10-27T10:${String(m).padStart(2, "0")}:00Z`;
function drain(feed, since, limit, extra = "") {
  const got = []; let cur = { since, after: null }, pages = 0;
  for (;;) {
    const s = `since=${cur.since}&limit=${limit}${cur.after ? "&after_id=" + encodeURIComponent(cur.after) : ""}${extra}`;
    const r = T.filter(feed, new URLSearchParams(s), q(s)); pages++;
    got.push(...r.items.map(i => i.id));
    if (!r.has_more) { assert.equal(r.next_since, feed.generated_at); assert.equal(r.next_after_id, null); return { got, pages }; }
    assert.ok(r.next_since && r.next_after_id); cur = { since: r.next_since, after: r.next_after_id };
    assert.ok(pages < 50, "runaway paging");
  }
}
ok("25 new unique items, limit 20 -> 2 pages, all 25 delivered once", () => {
  const feed = { generated_at: GEN, items: Array.from({ length: 25 }, (_, k) => mk(k, pad(k + 1))) };
  const first = T.applyFilter(feed, q("since=2026-10-27T00:00:00Z&limit=20"));
  assert.equal(first.items.length, 20); assert.equal(first.has_more, true); assert.equal(first.total_matching, 25);
  const { got, pages } = drain(feed, "2026-10-27T00:00:00Z", 20);
  assert.equal(pages, 2); assert.equal(got.length, 25); assert.equal(new Set(got).size, 25);
});
ok("tied timestamps across page boundary are not lost or duplicated", () => {
  const feed = { generated_at: GEN, items: Array.from({ length: 25 }, (_, k) => mk(k, k < 3 ? pad(1) : pad(2))) }; // 3 at :01, 22 at :02
  for (const lim of [1, 2, 3, 5, 20, 22, 24]) {
    const { got } = drain(feed, "2026-10-27T00:00:00Z", lim);
    assert.equal(got.length, 25, "limit " + lim); assert.equal(new Set(got).size, 25, "limit " + lim);
  }
});
ok("sort=reward with since still pages gap-free", () => {
  const feed = { generated_at: GEN, items: Array.from({ length: 25 }, (_, k) => mk(k, pad(k % 4))) };
  const { got } = drain(feed, "2026-10-27T00:00:00Z", 7, "&sort=reward");
  assert.equal(new Set(got).size, 25);
});
ok("empty drain: has_more=false, next_since=generated_at, count 0", () => {
  const feed = { generated_at: GEN, items: [mk(1, pad(1))] };
  const r = T.filter(feed, new URLSearchParams(), q("since=2026-10-27T12:00:00Z&limit=20"));
  assert.equal(r.count, 0); assert.equal(r.has_more, false); assert.equal(r.next_since, GEN);
});
ok("no since + truncated: next_since null (not a safe baseline)", () => {
  const feed = { generated_at: GEN, items: Array.from({ length: 5 }, (_, k) => mk(k, pad(k))) };
  const r = T.applyFilter(feed, q("limit=2")); assert.equal(r.has_more, true); assert.equal(r.next_since, null);
  assert.equal(T.applyFilter(feed, q("limit=5")).next_since, GEN);
});
ok("after_id without since is a free 400-style error", () => {
  assert.ok(T.parseQuery(new URLSearchParams("after_id=t:001")).errs.length === 1);
});
// MCP path uses the same cursor
const feed25 = { generated_at: GEN, items: Array.from({ length: 25 }, (_, k) => mk(k, pad(k + 1))) };
const call = async (name, args) => { const r = await mcp(new Request("https://x/mcp", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }) }), new URL("https://x/mcp"), { getFeed: async () => feed25, parseQuery: T.parseQuery, applyFilter: T.applyFilter }); return (await r.json()).result.structuredContent; };
{
  const a = await call("get_new_bounties", { since: "2026-10-27T00:00:00Z", limit: 20 });
  assert.equal(a.count, 20); assert.equal(a.has_more, true);
  const b = await call("get_new_bounties", { since: a.next_since, after_id: a.next_after_id, limit: 20 });
  assert.equal(b.count, 5); assert.equal(b.has_more, false); assert.equal(b.next_since, GEN);
  assert.equal(new Set([...a.items, ...b.items].map(i => i.id)).size, 25); n++; console.log("ok - MCP get_new_bounties 20+5 pages");
  const c = await call("list_bounties", { min_usd: 50 });
  assert.equal(c.count, 0); n++; console.log("ok - MCP list_bounties min_usd filter");
}
{
  const r = await mcp(new Request("https://x/mcp", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "list_bounties", arguments: { min_usd: 50 } } }) }), new URL("https://x/mcp"), { getFeed: async () => usdFeed, parseQuery: T.parseQuery, applyFilter: T.applyFilter });
  const ids = (await r.json()).result.structuredContent.items.map(i => i.id);
  assert.ok(!ids.some(id => id.startsWith("taskmarket:"))); n++; console.log("ok - MCP min_usd=50 excludes OUSD-null rows");
}

// ---- Bug 3: earn-now conservative eligibility + freshness
const NOW = Date.parse("2026-10-28T00:00:00Z");
const v = (h) => ({ checked_at: new Date(NOW - h * 3600e3).toISOString(), how: "t" });
const earnFeed = { generated_at: GEN, items: [
  { id: "frantic:97", kind: "bounty", reward: 10, currency: "USD", est_usd: 10, requires: ["agent_account", "purchase", "wallet_evm"], verified: v(0.5) },
  { id: "ok:fresh", kind: "bounty", reward: 5, currency: "USD", est_usd: 5, requires: ["agent_account"], verified: v(1) },
  { id: "old:verify", kind: "bounty", reward: 6, currency: "USD", est_usd: 6, requires: [], verified: v(7) },
  { id: "stale:flag", kind: "bounty", reward: 7, currency: "USD", est_usd: 7, requires: [], verified: v(1), stale: true },
  { id: "past:deadline", kind: "bounty", reward: 8, currency: "USD", est_usd: 8, requires: [], verified: v(1), deadline: "2026-10-27T23:00:00Z" },
  { id: "ousd:null", kind: "bounty", reward: 100, currency: "OUSD", est_usd: null, requires: [], verified: v(1) },
  { id: "no:verify", kind: "bounty", reward: 9, currency: "USD", est_usd: 9, requires: [] },
  { id: "fetched:recent", kind: "bounty", reward: 2, currency: "USDC", requires: [], fetched_at: new Date(NOW - 3600e3).toISOString() },
] };
ok("earn-now: excludes purchase (frantic:97), stale, >6h unverified, past deadline, OUSD-null", () => {
  const e = T.earnNow(earnFeed, NOW);
  assert.deepEqual(e.items.map(i => i.id), ["ok:fresh", "fetched:recent"]);
  assert.equal(e.excluded_not_fresh, 4);
});
ok("earn-now: excludes items whose source detail check failed (verified.degraded)", () => {
  const f = { generated_at: new Date(NOW).toISOString(), items: [
    { id: "frantic:deg", kind: "bounty", reward: 20, currency: "USD", est_usd: 20, requires: ["agent_account"], verified: { ...v(0.5), degraded: true } },
    { id: "frantic:ok", kind: "bounty", reward: 3, currency: "USD", est_usd: 3, requires: ["agent_account"], verified: v(0.5) },
  ] };
  const e = T.earnNow(f, NOW);
  assert.deepEqual(e.items.map(i => i.id), ["frantic:ok"]);
  assert.equal(e.excluded_not_fresh, 1);
});
console.log(`\n${n} unit tests passed`);
