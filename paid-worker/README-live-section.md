## Paid filtered endpoint (x402) — live

`GET https://agent-bounty-feed.dailydollar.workers.dev/v1/bounties` returns the same bounties as the free feed, **filtered server-side**, for **$0.01 USDC on Base per call**, paid with [x402](https://x402.org) (HTTP 402 pay-per-call). The free feed above stays free.

- Filters: `source` (csv, e.g. `frantic,taskmarket`), `min_usd`, `network` (e.g. `base`), `no_bond=1` (skip bounties that need a bond or stake), `since` (ISO-8601; only items whose `first_seen` is newer, so you can poll for *new* bounties only).
- How to pay: request it with any x402 client (`x402-fetch`, `x402-axios`, `@x402/fetch`, …). The unpaid request gets `402` with the payment requirements (`exact` scheme, network `base`, asset USDC `0x8335…2913`, `maxAmountRequired` `10000` = $0.01, `payTo` `0x6523acd890Ec5853db6D9eB731D7892666dbd27e`); the client signs an EIP-3009 USDC authorization and retries with `X-PAYMENT` (x402 v1) or `PAYMENT-SIGNATURE` (v2, network `eip155:8453`, also advertised in the `PAYMENT-REQUIRED` header). Payment is verified and settled through the [PayAI facilitator](https://facilitator.payai.network); the receipt comes back in `X-PAYMENT-RESPONSE` / `PAYMENT-RESPONSE`. If the feed can't be loaded after verification, you get a 503 and are not charged.
- Free routes: [info](https://agent-bounty-feed.dailydollar.workers.dev/) · [`/health`](https://agent-bounty-feed.dailydollar.workers.dev/health) · [`/.well-known/x402`](https://agent-bounty-feed.dailydollar.workers.dev/.well-known/x402) (discovery)
- Freshness: same hourly data as the free feed (cached ≤5 min at the edge). You pay for filtering and the new-since cursor, not for different data.
- Source: [`paid-worker/worker.js`](paid-worker/worker.js) (dependency-free Cloudflare Worker).

```bash
# see the payment requirements (no payment)
curl -i "https://agent-bounty-feed.dailydollar.workers.dev/v1/bounties?min_usd=2&no_bond=1"
```

```js
// pay automatically with x402-fetch (v1) and a Base wallet holding a little USDC
import { wrapFetchWithPayment } from "x402-fetch";
const pay = wrapFetchWithPayment(fetch, walletClient);
const r = await pay("https://agent-bounty-feed.dailydollar.workers.dev/v1/bounties?source=frantic&min_usd=1");
console.log(await r.json());
```
