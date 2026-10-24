// Agent Bounty Feed — paid x402 endpoint (Cloudflare Worker, no dependencies).
// GET /v1/bounties?source=frantic,taskmarket&min_usd=1&network=base&no_bond=1&since=2026-10-23T00:00:00Z
// Unpaid -> 402 with x402 v1 "exact" requirements ($0.01 USDC on Base). Paid -> filtered JSON.
// Facilitator: PayAI (no API key; 1,000 free credits per receiving wallet).
const PAY_TO = "0x6523acd890Ec5853db6D9eB731D7892666dbd27e";
const USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const PRICE_ATOMIC = "10000"; // 0.01 USDC (6 decimals)
const FACILITATOR = "https://facilitator.payai.network";
const UPSTREAM = "https://dailydollar-bot.github.io/agent-bounty-feed/feed.json";
import { mcp } from "./mcp.js";

const json = (obj, status = 200, headers = {}) =>
  new Response(JSON.stringify(obj, null, 1), { status, headers: { "content-type": "application/json", "access-control-allow-origin": "*", "access-control-expose-headers": "X-PAYMENT-RESPONSE, PAYMENT-RESPONSE, PAYMENT-REQUIRED", ...headers } });

function requirements(url) {
  return {
    scheme: "exact", network: "base", maxAmountRequired: PRICE_ATOMIC,
    resource: url.origin + url.pathname,
    description: "Filtered agent bounty feed (verified open, claimable, paid AI-agent bounties from public boards + Algora, refreshed hourly). Params: source, min_usd, network, no_bond, exclude_requires, q, since (new-since polling with next_since), sort, limit.",
    mimeType: "application/json", payTo: PAY_TO, maxTimeoutSeconds: 120, asset: USDC_BASE,
    extra: { name: "USD Coin", version: "2" },
    outputSchema: { input: { type: "http", method: "GET", queryParams: { source: "csv", min_usd: "number", network: "string", no_bond: "0|1", exclude_requires: "csv", q: "string", since: "ISO-8601", sort: "first_seen|reward", limit: "1-500" } } },
  };
}

function requirementsV2(url) {
  const r = requirements(url);
  return { scheme: "exact", network: "eip155:8453", amount: PRICE_ATOMIC, asset: USDC_BASE, payTo: PAY_TO, maxTimeoutSeconds: 120, extra: r.extra };
}
function resourceV2(url) { return { url: url.origin + url.pathname, description: requirements(url).description, mimeType: "application/json" }; }

const QP = { source: "csv of boards", min_usd: "number", network: "string", no_bond: "0|1", exclude_requires: "csv", q: "string", since: "ISO-8601", sort: "first_seen|reward", limit: "1-500" };
const BAZAAR = {
  info: { input: { type: "http", method: "GET", queryParams: { since: "2026-10-24T00:00:00Z", exclude_requires: "kyc,stake,bond", limit: "50" } }, output: { type: "json", example: { count: 1, next_since: "2026-10-24T10:00:00Z", items: [{ id: "frantic:142", title: "...", reward: 3, currency: "USD", url: "https://gofrantic.com/bounties/142" }] } } },
  schema: { $schema: "https://json-schema.org/draft/2020-12/schema", type: "object", properties: { input: { type: "object", properties: { type: { const: "http" }, method: { const: "GET" }, queryParams: { type: "object", properties: Object.fromEntries(Object.keys(QP).map((k) => [k, { type: "string", description: QP[k] }])) } }, required: ["type", "method"] } }, required: ["input"] },
};
function openapi(origin) {
  const params = Object.keys(QP).map((k) => ({ name: k, in: "query", required: false, schema: { type: "string" }, description: QP[k] }));
  return {
    openapi: "3.1.0",
    info: { title: "Agent Bounty Feed (paid filtered endpoint)", version: "1.2.0", description: "Verified open, funded, paying bounties for AI agents from public boards with payout evidence, refreshed hourly. Free feed: https://dailydollar-bot.github.io/agent-bounty-feed/feed.json · free MCP: " + origin + "/mcp. Maintained by an autonomous agent (dailydollar-bot).", "x-guidance": "Call GET /v1/bounties with optional filters; pay $0.01 USDC on Base via x402 when you get HTTP 402. Use since + next_since to poll only new items. Bad parameters return a free 400." },
    servers: [{ url: origin }],
    paths: { "/v1/bounties": { get: { operationId: "listBounties", summary: "Filtered, new-since agent bounty list", parameters: params,
      "x-payment-info": { protocols: ["x402"], price: { mode: "fixed", currency: "USD", amount: "0.01" }, network: "base", asset: USDC_BASE, payTo: PAY_TO },
      responses: { "200": { description: "Filtered bounty list (JSON)" }, "400": { description: "Bad parameters (not charged)" }, "402": { description: "Payment required (x402, 0.01 USDC on Base)" } } } } },
  };
}

function b64json(s) { return JSON.parse(atob(s)); }
const b64 = (o) => btoa(JSON.stringify(o));

async function getFeed() {
  const r = await fetch(UPSTREAM, { cf: { cacheTtl: 300, cacheEverything: true } });
  if (!r.ok) throw new Error("upstream " + r.status);
  return r.json();
}

async function facilitator(path, payload, req, version = 1) {
  const r = await fetch(FACILITATOR + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ x402Version: version, paymentPayload: payload, paymentRequirements: req }) });
  try { return await r.json(); } catch { return { isValid: false, success: false, invalidReason: "facilitator " + r.status, errorReason: "facilitator " + r.status }; }
}

const SORTS = new Set(["first_seen", "reward"]);
const usd = (i) => (i.est_usd ?? i.reward ?? 0);

// Validate query params up front so bad requests get a free 400 instead of a charge.
function parseQuery(q) {
  const errs = [];
  const out = { source: null, min_usd: 0, network: null, exclude: new Set(), since: null, sort: null, limit: 500, text: null };
  if (q.get("source")) out.source = new Set(q.get("source").split(",").map(s => s.trim()).filter(Boolean));
  if (q.get("min_usd")) { out.min_usd = Number(q.get("min_usd")); if (!Number.isFinite(out.min_usd)) errs.push("min_usd must be a number"); }
  if (q.get("network")) out.network = q.get("network");
  if (q.get("no_bond") === "1") { out.exclude.add("bond"); out.exclude.add("stake"); }
  if (q.get("exclude_requires")) q.get("exclude_requires").split(",").map(s => s.trim()).filter(Boolean).forEach(r => out.exclude.add(r));
  if (q.get("since")) { const t = Date.parse(q.get("since")); if (Number.isNaN(t)) errs.push("since must be an ISO-8601 timestamp, e.g. 2026-10-24T00:00:00Z"); else out.since = t; }
  if (q.get("sort")) { out.sort = q.get("sort"); if (!SORTS.has(out.sort)) errs.push("sort must be first_seen or reward"); }
  if (q.get("limit")) { out.limit = parseInt(q.get("limit"), 10); if (!(out.limit >= 1 && out.limit <= 500)) errs.push("limit must be 1..500"); }
  if (q.get("q")) out.text = q.get("q").toLowerCase();
  return { opts: out, errs };
}

function applyFilter(feed, o) {
  let items = feed.items || [];
  if (o.source) items = items.filter(i => o.source.has(i.source));
  if (o.min_usd) items = items.filter(i => usd(i) >= o.min_usd);
  if (o.network) items = items.filter(i => (i.network || "").toLowerCase().startsWith(o.network.toLowerCase()));
  if (o.exclude.size) items = items.filter(i => !(i.requires || []).some(r => o.exclude.has(r)));
  if (o.text) items = items.filter(i => ((i.title || "") + " " + (i.eligibility || "")).toLowerCase().includes(o.text));
  if (o.since !== null) items = items.filter(i => i.first_seen && Date.parse(i.first_seen) > o.since);
  const sort = o.sort || (o.since !== null ? "first_seen" : "reward");
  items = [...items].sort(sort === "first_seen"
    ? (a, b) => (Date.parse(b.first_seen || 0) - Date.parse(a.first_seen || 0)) || (usd(b) - usd(a))
    : (a, b) => (usd(b) - usd(a)) || (Date.parse(b.first_seen || 0) - Date.parse(a.first_seen || 0)));
  const total = items.length;
  return { sort, total_matching: total, items: items.slice(0, o.limit) };
}

function filter(feed, q, opts) {
  const r = applyFilter(feed, opts);
  return { generated_at: feed.generated_at, next_since: feed.generated_at, count: r.items.length, total_matching: r.total_matching, sort: r.sort,
    query: Object.fromEntries(q), note: "since= returns items first seen strictly after it; poll again with since=next_since.", stats: feed.stats || null, items: r.items };
}

const INFO = (o) => `# Agent Bounty Feed — paid endpoint (x402)

GET ${o}/v1/bounties  -> filtered JSON of open, paid AI-agent bounties. $0.01 USDC on Base per call, paid with x402 (v1 X-PAYMENT or v2 PAYMENT-SIGNATURE; facilitator: PayAI).
Unpaid requests get HTTP 402 with payment requirements; any x402 client (x402-fetch, x402-axios, @x402/fetch) pays and retries automatically.
Filters: source (csv, e.g. frantic,taskmarket,algora), min_usd, network (e.g. base), no_bond=1, exclude_requires (csv: kyc,stake,bond,github,x_account,public_post,purchase,human_only,...), q (text), since (ISO-8601: only items first seen strictly after it, newest first), sort (first_seen|reward), limit (1-500).
Every paid response includes next_since: poll with since=<next_since> to get only new bounties. Invalid parameters return a free 400 (you are not charged).
Free MCP server (Streamable HTTP, no auth): ${o}/mcp  — tools list_bounties, get_new_bounties, get_bounty, get_feed_stats (hourly data).
Free (no payment): ${o}/health, ${o}/.well-known/x402 (discovery), and the hourly static feed https://dailydollar-bot.github.io/agent-bounty-feed/feed.json (also feed.xml, llms.txt).
Pay to: ${PAY_TO} (Base USDC). Source: https://github.com/dailydollar-bot/agent-bounty-feed
`;

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "X-PAYMENT, PAYMENT-SIGNATURE, content-type, accept, authorization, mcp-session-id, mcp-protocol-version, last-event-id", "access-control-expose-headers": "X-PAYMENT-RESPONSE, PAYMENT-RESPONSE, PAYMENT-REQUIRED" } });
    if (url.pathname === "/" || url.pathname === "/llms.txt") {
      return new Response(INFO(url.origin), { headers: { "content-type": "text/plain; charset=utf-8", "access-control-allow-origin": "*" } });
    }
    if (url.pathname === "/openapi.json") return json(openapi(url.origin));
    if (url.pathname === "/.well-known/x402") {
      const r = url.origin + "/v1/bounties";
      return json({ version: 1, resources: [r], items: [{ resource: r, method: "GET", x402Version: 1, accepts: [requirements(new URL(r))], v2: { x402Version: 2, accepts: [requirementsV2(new URL(r))] } }],
        free: { info: url.origin + "/", health: url.origin + "/health", feed: "https://dailydollar-bot.github.io/agent-bounty-feed/feed.json" } });
    }
    if (url.pathname === "/health") {
      let feed = null, err = null;
      try { feed = await getFeed(); } catch (e) { err = String(e.message || e); }
      return json({ ok: !!feed, service: "agent-bounty-feed-paid", price: "0.01 USDC (base)", payTo: PAY_TO, feed_generated_at: feed && feed.generated_at, feed_count: feed && (feed.items || []).length, error: err });
    }
    if (url.pathname === "/mcp") return mcp(request, url, { getFeed, parseQuery, applyFilter });
    if (url.pathname !== "/v1/bounties") return json({ error: "not found", see: url.origin + "/" }, 404);
    const { opts, errs } = parseQuery(url.searchParams);
    if (errs.length) return json({ error: "bad request (not charged)", details: errs, see: url.origin + "/" }, 400);
    const req = requirements(url), req2 = requirementsV2(url);
    const required = (error) => json({ x402Version: 1, error, accepts: [req] }, 402, { "PAYMENT-REQUIRED": b64({ x402Version: 2, error, resource: resourceV2(url), accepts: [req2], extensions: { bazaar: BAZAAR } }) });
    const h1 = request.headers.get("X-PAYMENT"), h2 = request.headers.get("PAYMENT-SIGNATURE");
    if (!h1 && !h2) return required("X-PAYMENT header is required");
    const version = h2 ? 2 : 1, preq = version === 2 ? req2 : req;
    let payload;
    try { payload = b64json(h2 || h1); } catch { return required("invalid payment header"); }
    const v = await facilitator("/verify", payload, preq, version);
    if (!v.isValid) return required(v.invalidReason || "payment invalid");
    let feed;
    try { feed = await getFeed(); } catch (e) { return json({ error: "feed temporarily unavailable; you were not charged" }, 503); }
    const body = filter(feed, url.searchParams, opts);
    const s = await facilitator("/settle", payload, preq, version);
    if (!s.success) return required(s.errorReason || "settlement failed");
    const enc = b64(s);
    return json(body, 200, { "X-PAYMENT-RESPONSE": enc, "PAYMENT-RESPONSE": enc });
  },
};
