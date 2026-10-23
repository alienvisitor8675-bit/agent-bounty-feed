# Paid tier (x402) — not deployed yet

`worker.js` is a dependency-free Cloudflare Worker:

- `GET /v1/bounties` without payment returns `402` with x402 v1 `exact` requirements: 0.01 USDC (`10000` atomic) on `base`, `payTo` 0x6523acd890Ec5853db6D9eB731D7892666dbd27e, asset USDC `0x8335…2913`.
- With an `X-PAYMENT` header it calls the PayAI facilitator `/verify`, builds the filtered response, then `/settle`, and returns the data with `X-PAYMENT-RESPONSE`.
- Filters: `source` (csv), `min_usd`, `network`, `no_bond=1`, `since` (ISO time, matches `first_seen`).
- PayAI needs no API key: 1,000 free credits per receiving wallet, then $1 = 1,000 credits.

Deploy: `npx wrangler deploy` with a Cloudflare account (free Workers plan allows commercial use). Test locally: `node test.mjs`.
