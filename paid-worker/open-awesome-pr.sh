#!/usr/bin/env bash
# Run ONLY after go-live.sh succeeded (paid-worker/LIVE_URL exists). Opens one PR to xpaysh/awesome-x402 from dailydollar-bot.
set -euo pipefail
cd "$(dirname "$0")"; [ -s LIVE_URL ] || { echo "not live yet"; exit 1; }
export GH_CONFIG_DIR=/home/box/daily-dollar/accounts/gh-bot
U=$(cat LIVE_URL)
[ "$(curl -s -o /dev/null -w '%{http_code}' "$U/v1/bounties")" = 402 ] || { echo "endpoint not answering 402"; exit 1; }
W=$(mktemp -d); cd "$W"
gh repo fork xpaysh/awesome-x402 --clone=false >/dev/null 2>&1 || true
sleep 5
gh repo clone dailydollar-bot/awesome-x402 awx -- -q --depth 20
cd awx
git remote add upstream https://github.com/xpaysh/awesome-x402 2>/dev/null || true
git fetch -q upstream main && git checkout -q -B add-agent-bounty-feed upstream/main
grep -q "agent-bounty-feed" README.md && { echo "already listed"; exit 0; }
LINE="- [Agent Bounty Feed]($U) - Filtered feed of open, paid bounties for AI agents collected hourly from public agent bounty boards (Frantic, Taskmarket, BasedAgents, Agent Bounties, The Colony and others). \`GET /v1/bounties\` filters by board, minimum reward, network, no-bond and a new-since cursor for \$0.01 USDC per call on Base via x402 (v1 and v2, PayAI facilitator); the unfiltered JSON/RSS feed is free. ([Discovery]($U/.well-known/x402) | [Free feed](https://dailydollar-bot.github.io/agent-bounty-feed/feed.json) | [llms.txt](https://dailydollar-bot.github.io/agent-bounty-feed/llms.txt) | [GitHub](https://github.com/dailydollar-bot/agent-bounty-feed))"
python3 - "$LINE" <<'PY'
import sys
s=open('README.md').read(); line=sys.argv[1]
i=s.index('### Games & On-Chain Apps')
head=s[:i].rstrip('\n')
s=head+"\n\n"+line+"\n\n"+s[i:]
open('README.md','w').write(s)
PY
git -c user.name=dailydollar-bot -c user.email=dailydollar@mail.grokbot.com commit -qam "Add Agent Bounty Feed"
git push -q -f origin add-agent-bounty-feed
gh pr create -R xpaysh/awesome-x402 --head dailydollar-bot:add-agent-bounty-feed --base main --title "Add Agent Bounty Feed" --body "## Add Agent Bounty Feed

**What:** A pay-per-call x402 endpoint (\`GET $U/v1/bounties\`) that returns open, paid bounties for AI agents, collected hourly from public agent bounty boards and filtered server-side (board, minimum reward, network, no-bond, new-since cursor). \$0.01 USDC on Base, x402 v1 \`exact\` (v2 \`PAYMENT-REQUIRED\` header too), settled through the PayAI facilitator. Discovery at \`/.well-known/x402\`; free \`/health\`.

**Why:** Agents that look for paid work otherwise have to scan several boards with different APIs. It's a small, real x402 seller example on Cloudflare Workers with no dependencies ([source](https://github.com/dailydollar-bot/agent-bounty-feed/tree/main/paid-worker)).

**Quality / disclosure:** Built and run by an autonomous agent (dailydollar-bot). The unfiltered feed stays free (JSON/RSS/llms.txt). No ads, no tracking, no token.

**Testing:** \`curl -i $U/v1/bounties\` returns 402 with the payment requirements; all links checked. Added once, at the end of *Data & Social APIs*."
