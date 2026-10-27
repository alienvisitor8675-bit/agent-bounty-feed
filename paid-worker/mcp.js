// Agent Bounty Feed — free remote MCP server (Streamable HTTP, stateless, JSON responses, no auth).
// Spec: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#streamable-http
const SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"];
const PAID_NOTE = "Free MCP data = the hourly public feed. For server-side filtered polling from code, the paid x402 endpoint GET https://agent-bounty-feed.dailydollar.workers.dev/v1/bounties?since=... costs $0.01 USDC on Base per call. Always confirm terms on the source board before working.";
const CORS = { "access-control-allow-origin": "*", "access-control-expose-headers": "mcp-session-id, mcp-protocol-version" };

const FILTER_PROPS = {
  source: { type: "string", description: "Comma-separated boards: frantic, taskmarket, algora, agentbounties, basedagents, superteam, licium, hondo, cantina, sherlock, code4rena, direct (cantina/sherlock/code4rena are audit contests, kind=audit_contest)" },
  min_usd: { type: "number", description: "Minimum reward in USD-equivalent; items with unknown USD value (e.g. OUSD with est_usd=null) are excluded when > 0" },
  network: { type: "string", description: "Payout network prefix, e.g. base, solana, tempo" },
  exclude_requires: { type: "string", description: "Comma-separated requirements to exclude: kyc, stake, bond, github, x_account, public_post, purchase, human_only, agent_account, wallet_evm, wallet_solana" },
  q: { type: "string", description: "Case-insensitive text search in title and eligibility" },
  limit: { type: "integer", minimum: 1, maximum: 100, description: "Max items to return (default 20)" },
};
const TOOLS = [
  { name: "list_bounties", title: "List open paid bounties",
    description: "List currently open, claimable, paid bounties for AI agents (verified hourly from Frantic, Taskmarket, Algora/GitHub, Agent Bounties, The Colony and more). Each item has reward, est_usd, url, deadline, requires[], slots_left, competition and payout_track_record.",
    inputSchema: { type: "object", properties: { ...FILTER_PROPS, sort: { type: "string", enum: ["reward", "first_seen"], description: "reward (default) or first_seen (newest first)" } } },
    annotations: { readOnlyHint: true, openWorldHint: true } },
  { name: "get_new_bounties", title: "Bounties first seen since a time",
    description: "Bounties first seen strictly after `since` (ISO-8601), oldest first by (first_seen, id). If has_more=true, call again with since=next_since and after_id=next_after_id (no items are skipped); when has_more=false, next_since is the feed time to poll from next.",
    inputSchema: { type: "object", properties: { since: { type: "string", description: "ISO-8601 timestamp, e.g. 2026-10-24T00:00:00Z" }, after_id: { type: "string", description: "Page cursor: next_after_id from the previous response (use with its next_since)" }, ...FILTER_PROPS }, required: ["since"] },
    annotations: { readOnlyHint: true, openWorldHint: true } },
  { name: "get_bounty", title: "Get one bounty",
    description: "Full record for one bounty id from list_bounties (e.g. frantic:142, taskmarket:TSK-XXXX, algora:owner/repo#123).",
    inputSchema: { type: "object", properties: { id: { type: "string" } }, required: ["id"] },
    annotations: { readOnlyHint: true, openWorldHint: true } },
  { name: "get_feed_stats", title: "Feed stats",
    description: "Totals: item count, total USD, per-source counts, new in last 24h, how many need no bond/stake/KYC, items dropped by verification, last refresh time.",
    inputSchema: { type: "object", properties: {} },
    annotations: { readOnlyHint: true, openWorldHint: true } },
];

const slim = (i) => ({ id: i.id, source: i.source, title: i.title, reward: i.reward, currency: i.currency, est_usd: i.est_usd, network: i.network,
  deadline: i.deadline, url: i.url, requires: i.requires, slots_left: i.slots_left, competition: i.competition,
  payout_track_record: i.payout_track_record, first_seen: i.first_seen, eligibility: i.eligibility });

function toQuery(args) {
  const p = new URLSearchParams();
  for (const k of ["source", "min_usd", "network", "exclude_requires", "q", "since", "after_id", "sort"]) if (args[k] !== undefined && args[k] !== null && args[k] !== "") p.set(k, String(args[k]));
  const lim = Math.max(1, Math.min(100, parseInt(args.limit ?? 20, 10) || 20));
  p.set("limit", String(lim));
  return p;
}

async function callTool(name, args, d) {
  const feed = await d.getFeed();
  if (name === "get_feed_stats") return { generated_at: feed.generated_at, stats: feed.stats || { items: (feed.items || []).length }, feeds: { json: feed.feed_url, home: feed.home_page_url }, note: PAID_NOTE };
  if (name === "get_bounty") {
    const it = (feed.items || []).find(i => i.id === args.id);
    if (!it) throw new ToolError(`No open bounty with id ${args.id} (it may have closed). Use list_bounties.`);
    return { generated_at: feed.generated_at, item: it, note: PAID_NOTE };
  }
  if (name === "list_bounties" || name === "get_new_bounties") {
    if (name === "get_new_bounties" && !args.since) throw new ToolError("since is required (ISO-8601)");
    if (name === "list_bounties") { delete args.since; delete args.after_id; }
    const { opts, errs } = d.parseQuery(toQuery(args));
    if (errs.length) throw new ToolError(errs.join("; "));
    const r = d.applyFilter(feed, opts);
    return { generated_at: feed.generated_at, has_more: r.has_more, next_since: r.next_since, next_after_id: r.next_after_id, sort: r.sort, count: r.items.length, total_matching: r.total_matching, items: r.items.map(slim), note: PAID_NOTE };
  }
  throw new RpcError(-32602, `Unknown tool: ${name}`);
}
class ToolError extends Error {}
class RpcError extends Error { constructor(code, msg) { super(msg); this.code = code; } }

async function handle(msg, d) {
  const { id, method, params = {} } = msg || {};
  if (!msg || msg.jsonrpc !== "2.0" || typeof method !== "string") return id === undefined ? null : err(id ?? null, -32600, "Invalid Request");
  const isNote = id === undefined || id === null;
  try {
    let result;
    switch (method) {
      case "initialize": {
        const v = SUPPORTED.includes(params.protocolVersion) ? params.protocolVersion : SUPPORTED[0];
        result = { protocolVersion: v, capabilities: { tools: { listChanged: false } },
          serverInfo: { name: "agent-bounty-feed", title: "Agent Bounty Feed", version: "1.2.0", websiteUrl: "https://dailydollar-bot.github.io/agent-bounty-feed/" },
          instructions: "Find open, paid bounties an AI agent can claim. Start with get_feed_stats or list_bounties (filter with exclude_requires=kyc,stake,bond for no-friction work). Poll get_new_bounties with since=next_since (plus after_id=next_after_id while has_more=true). " + PAID_NOTE };
        break;
      }
      case "ping": result = {}; break;
      case "tools/list": result = { tools: TOOLS }; break;
      case "tools/call": {
        try {
          const out = await callTool(params.name, { ...(params.arguments || {}) }, d);
          result = { content: [{ type: "text", text: JSON.stringify(out, null, 1) }], structuredContent: out, isError: false };
        } catch (e) {
          if (e instanceof ToolError) result = { content: [{ type: "text", text: e.message }], isError: true };
          else if (e instanceof RpcError) throw e;
          else result = { content: [{ type: "text", text: "Feed temporarily unavailable: " + (e.message || e) }], isError: true };
        }
        break;
      }
      case "resources/list": result = { resources: [] }; break;
      case "prompts/list": result = { prompts: [] }; break;
      default:
        if (method.startsWith("notifications/")) return null;
        throw new RpcError(-32601, `Method not found: ${method}`);
    }
    return isNote ? null : { jsonrpc: "2.0", id, result };
  } catch (e) {
    return isNote ? null : err(id, e.code || -32603, e.message || "Internal error");
  }
}
const err = (id, code, message) => ({ jsonrpc: "2.0", id, error: { code, message } });
const j = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { "content-type": "application/json", ...CORS } });

export async function mcp(request, url, d) {
  if (request.method === "GET") {
    // No server-initiated SSE stream; a browser GET gets a short human note.
    const accept = request.headers.get("accept") || "";
    if (accept.includes("text/event-stream")) return new Response(null, { status: 405, headers: { allow: "POST", ...CORS } });
    return new Response(`Agent Bounty Feed MCP server (Streamable HTTP). POST JSON-RPC to ${url.origin}/mcp.\nClaude Code: claude mcp add --transport http agent-bounty-feed ${url.origin}/mcp\nTools: list_bounties, get_new_bounties, get_bounty, get_feed_stats.\n`, { status: 200, headers: { "content-type": "text/plain; charset=utf-8", ...CORS } });
  }
  if (request.method === "DELETE") return new Response(null, { status: 405, headers: { allow: "POST", ...CORS } });
  if (request.method !== "POST") return new Response(null, { status: 405, headers: { allow: "GET, POST", ...CORS } });
  let body;
  try { body = await request.json(); } catch { return j(err(null, -32700, "Parse error"), 400); }
  if (Array.isArray(body)) {
    const outs = (await Promise.all(body.map(m => handle(m, d)))).filter(Boolean);
    return outs.length ? j(outs) : new Response(null, { status: 202, headers: CORS });
  }
  const out = await handle(body, d);
  return out ? j(out) : new Response(null, { status: 202, headers: CORS });
}
