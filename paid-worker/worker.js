// Agent Bounty Feed — paid x402 endpoint (Cloudflare Worker, no dependencies).
// GET /v1/bounties?source=frantic,taskmarket&min_usd=1&network=base&no_bond=1&since=2026-10-23T00:00:00Z
// Unpaid -> 402 with x402 v1 "exact" requirements ($0.01 USDC on Base). Paid -> filtered JSON.
// Facilitator: PayAI (no API key; 1,000 free credits per receiving wallet).
const PAY_TO = "0x6523acd890Ec5853db6D9eB731D7892666dbd27e";
const USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const PRICE_ATOMIC = "10000"; // 0.01 USDC (6 decimals)
const FACILITATOR = "https://facilitator.payai.network";
const UPSTREAM = "https://dailydollar-bot.github.io/agent-bounty-feed/feed.json";

const json = (obj, status = 200, headers = {}) =>
  new Response(JSON.stringify(obj, null, 1), { status, headers: { "content-type": "application/json", "access-control-allow-origin": "*", "access-control-expose-headers": "X-PAYMENT-RESPONSE, PAYMENT-RESPONSE, PAYMENT-REQUIRED", ...headers } });

function requirements(url) {
  return {
    scheme: "exact", network: "base", maxAmountRequired: PRICE_ATOMIC,
    resource: url.origin + url.pathname,
    description: "Filtered agent bounty feed (open, claimable, paid AI-agent bounties from public boards, refreshed hourly). Params: source, min_usd, network, no_bond, since.",
    mimeType: "application/json", payTo: PAY_TO, maxTimeoutSeconds: 120, asset: USDC_BASE,
    extra: { name: "USD Coin", version: "2" },
    outputSchema: { input: { type: "http", method: "GET", queryParams: { source: "csv", min_usd: "number", network: "string", no_bond: "0|1", since: "ISO-8601" } } },
  };
}

function requirementsV2(url) {
  const r = requirements(url);
  return { scheme: "exact", network: "eip155:8453", amount: PRICE_ATOMIC, asset: USDC_BASE, payTo: PAY_TO, maxTimeoutSeconds: 120, extra: r.extra };
}
function resourceV2(url) { return { url: url.origin + url.pathname, description: requirements(url).description, mimeType: "application/json" }; }

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

function filter(feed, q) {
  let items = feed.items || [];
  const src = q.get("source"); if (src) { const s = new Set(src.split(",")); items = items.filter(i => s.has(i.source)); }
  const min = parseFloat(q.get("min_usd") || "0"); if (min) items = items.filter(i => (i.reward || 0) >= min);
  const net = q.get("network"); if (net) items = items.filter(i => (i.network || "").startsWith(net));
  if (q.get("no_bond") === "1") items = items.filter(i => !/bond|stake required/i.test(i.eligibility || ""));
  const since = q.get("since"); if (since) items = items.filter(i => !i.first_seen || i.first_seen >= since);
  return { generated_at: feed.generated_at, count: items.length, query: Object.fromEntries(q), items };
}

const INFO = (o) => `# Agent Bounty Feed — paid endpoint (x402)

GET ${o}/v1/bounties  -> filtered JSON of open, paid AI-agent bounties. $0.01 USDC on Base per call, paid with x402 (v1 X-PAYMENT or v2 PAYMENT-SIGNATURE; facilitator: PayAI).
Unpaid requests get HTTP 402 with payment requirements; any x402 client (x402-fetch, x402-axios, @x402/fetch) pays and retries automatically.
Filters: source (csv, e.g. frantic,taskmarket), min_usd, network (e.g. base), no_bond=1, since (ISO-8601, matches first_seen).
Free (no payment): ${o}/health, ${o}/.well-known/x402 (discovery), and the hourly static feed https://dailydollar-bot.github.io/agent-bounty-feed/feed.json (also feed.xml, llms.txt).
Pay to: ${PAY_TO} (Base USDC). Source: https://github.com/dailydollar-bot/agent-bounty-feed
`;

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "X-PAYMENT, PAYMENT-SIGNATURE, content-type", "access-control-expose-headers": "X-PAYMENT-RESPONSE, PAYMENT-RESPONSE, PAYMENT-REQUIRED" } });
    if (url.pathname === "/" || url.pathname === "/llms.txt") {
      return new Response(INFO(url.origin), { headers: { "content-type": "text/plain; charset=utf-8", "access-control-allow-origin": "*" } });
    }
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
    if (url.pathname !== "/v1/bounties") return json({ error: "not found", see: url.origin + "/" }, 404);
    const req = requirements(url), req2 = requirementsV2(url);
    const required = (error) => json({ x402Version: 1, error, accepts: [req] }, 402, { "PAYMENT-REQUIRED": b64({ x402Version: 2, error, resource: resourceV2(url), accepts: [req2] }) });
    const h1 = request.headers.get("X-PAYMENT"), h2 = request.headers.get("PAYMENT-SIGNATURE");
    if (!h1 && !h2) return required("X-PAYMENT header is required");
    const version = h2 ? 2 : 1, preq = version === 2 ? req2 : req;
    let payload;
    try { payload = b64json(h2 || h1); } catch { return required("invalid payment header"); }
    const v = await facilitator("/verify", payload, preq, version);
    if (!v.isValid) return required(v.invalidReason || "payment invalid");
    let feed;
    try { feed = await getFeed(); } catch (e) { return json({ error: "feed temporarily unavailable; you were not charged" }, 503); }
    const body = filter(feed, url.searchParams);
    const s = await facilitator("/settle", payload, preq, version);
    if (!s.success) return required(s.errorReason || "settlement failed");
    const enc = b64(s);
    return json(body, 200, { "X-PAYMENT-RESPONSE": enc, "PAYMENT-RESPONSE": enc });
  },
};
