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
  new Response(JSON.stringify(obj, null, 1), { status, headers: { "content-type": "application/json", "access-control-allow-origin": "*", "access-control-expose-headers": "X-PAYMENT-RESPONSE", ...headers } });

function requirements(url) {
  return {
    scheme: "exact", network: "base", maxAmountRequired: PRICE_ATOMIC,
    resource: url.origin + url.pathname,
    description: "Filtered agent bounty feed (open, claimable, paid bounties from 7 boards). Params: source, min_usd, network, no_bond, since.",
    mimeType: "application/json", payTo: PAY_TO, maxTimeoutSeconds: 120, asset: USDC_BASE,
    extra: { name: "USD Coin", version: "2" },
    outputSchema: { input: { type: "http", method: "GET", queryParams: { source: "csv", min_usd: "number", network: "string", no_bond: "0|1", since: "ISO-8601" } } },
  };
}

function b64json(s) { return JSON.parse(atob(s)); }

async function facilitator(path, payload, req) {
  const r = await fetch(FACILITATOR + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ x402Version: 1, paymentPayload: payload, paymentRequirements: req }) });
  return r.json();
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

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/" || url.pathname === "/llms.txt") {
      return new Response(`# Agent Bounty Feed — paid endpoint\n\nGET ${url.origin}/v1/bounties (x402, $0.01 USDC on Base per call). Filters: source, min_usd, network, no_bond, since.\nFree hourly feed: https://dailydollar-bot.github.io/agent-bounty-feed/feed.json\n`, { headers: { "content-type": "text/plain" } });
    }
    if (url.pathname !== "/v1/bounties") return json({ error: "not found" }, 404);
    const req = requirements(url);
    const header = request.headers.get("X-PAYMENT");
    if (!header) return json({ x402Version: 1, error: "X-PAYMENT header is required", accepts: [req] }, 402);
    let payload;
    try { payload = b64json(header); } catch { return json({ x402Version: 1, error: "invalid X-PAYMENT header", accepts: [req] }, 402); }
    const v = await facilitator("/verify", payload, req);
    if (!v.isValid) return json({ x402Version: 1, error: v.invalidReason || "payment invalid", accepts: [req] }, 402);
    const feed = await (await fetch(UPSTREAM, { cf: { cacheTtl: 60 } })).json();
    const body = filter(feed, url.searchParams);
    const s = await facilitator("/settle", payload, req);
    if (!s.success) return json({ x402Version: 1, error: s.errorReason || "settlement failed", accepts: [req] }, 402);
    return json(body, 200, { "X-PAYMENT-RESPONSE": btoa(JSON.stringify(s)) });
  },
};
