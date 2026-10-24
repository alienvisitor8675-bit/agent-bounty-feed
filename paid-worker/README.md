# Paid tier (x402) + free MCP server — live at https://agent-bounty-feed.dailydollar.workers.dev

`worker.js` is a dependency-free Cloudflare Worker (free plan):

- `GET /v1/bounties` without payment returns `402` with x402 requirements: 0.01 USDC (`10000` atomic) on Base, `payTo` 0x6523acd890Ec5853db6D9eB731D7892666dbd27e. With `X-PAYMENT` (v1) or `PAYMENT-SIGNATURE` (v2) it verifies via the PayAI facilitator, builds the filtered response, settles, and returns the data with `X-PAYMENT-RESPONSE`.
- Filters: `source`, `min_usd`, `network`, `no_bond=1`, `exclude_requires`, `q`, `since` (strictly after `first_seen`, newest first, returns `next_since`), `sort`, `limit`. Invalid params get a free `400`.
- `POST /mcp` — free remote MCP server (`mcp.js`, Streamable HTTP, stateless JSON responses): `list_bounties`, `get_new_bounties`, `get_bounty`, `get_feed_stats`.
- Free: `/`, `/health`, `/.well-known/x402`.

Deploy: `npx wrangler deploy`. Test locally: `node test.mjs`.
