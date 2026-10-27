import w from "./worker.js";
await import("./unit.test.mjs"); // integrity unit tests (no network) run first
const B = "https://x.example";
const show = async (label, r) => console.log(label, r.status, (await r.text()).slice(0, 300).replace(/\n/g, " "));
await show("402", await w.fetch(new Request(B + "/v1/bounties?min_usd=2")));
await show("400 since", await w.fetch(new Request(B + "/v1/bounties?since=yesterday")));
await show("400 sort", await w.fetch(new Request(B + "/v1/bounties?sort=x")));
const rpc = (body) => w.fetch(new Request(B + "/mcp", { method: "POST", headers: { "content-type": "application/json", accept: "application/json, text/event-stream" }, body: JSON.stringify(body) }));
await show("init", await rpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "t", version: "0" } } }));
await show("note", await rpc({ jsonrpc: "2.0", method: "notifications/initialized" }));
await show("list", await rpc({ jsonrpc: "2.0", id: 2, method: "tools/list" }));
await show("stats", await rpc({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "get_feed_stats", arguments: {} } }));
await show("lb", await rpc({ jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "list_bounties", arguments: { exclude_requires: "kyc,bond", limit: 2 } } }));
await show("new", await rpc({ jsonrpc: "2.0", id: 5, method: "tools/call", params: { name: "get_new_bounties", arguments: { since: "2026-10-23T12:00:00Z", limit: 2 } } }));
await show("badsince", await rpc({ jsonrpc: "2.0", id: 6, method: "tools/call", params: { name: "get_new_bounties", arguments: { since: "nope" } } }));
await show("get", await rpc({ jsonrpc: "2.0", id: 7, method: "tools/call", params: { name: "get_bounty", arguments: { id: "frantic:142" } } }));
await show("unk", await rpc({ jsonrpc: "2.0", id: 8, method: "nope" }));
// new free routes (no env/ctx locally: counters are skipped)
const en = await w.fetch(new Request(B + "/earn-now"));
const ej = await en.json(); console.log("earn-now", en.status, ej.count, ej.items.slice(0, 3).map(i => `${i.est_usd} ${i.id} [${i.requires}]`));
await show("v1/earn-now", await w.fetch(new Request(B + "/v1/earn-now")));
await show("card", await w.fetch(new Request(B + "/.well-known/agent-card.json")));
await show("hits(no kv)", await w.fetch(new Request(B + "/hits")));
await show("opts", await w.fetch(new Request(B + "/v1/bounties", { method: "OPTIONS" })));
