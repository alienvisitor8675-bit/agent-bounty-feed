#!/usr/bin/env bash
# Deploy the paid worker, verify a real 402 live, then advertise it in the free feed and push.
set -euo pipefail
cd "$(dirname "$0")"
export PATH=/home/box/node-v22.11.0-linux-x64/bin:$PATH
URL=https://agent-bounty-feed.dailydollar.workers.dev
npx -y wrangler@latest deploy </dev/null
for n in 1 2 3 4 5 6 7 8 9 10 11 12; do
  code=$(curl -s -o /tmp/abf402.json -w '%{http_code}' "$URL/v1/bounties?min_usd=2" || true)
  [ "$code" = 402 ] && break; sleep 10
done
[ "$code" = 402 ] || { echo "live check failed: $code"; exit 1; }
python3 - <<'PY'
import json; d=json.load(open('/tmp/abf402.json')); a=d['accepts'][0]
assert a['network']=='base' and a['maxAmountRequired']=='10000' and a['payTo'].lower()=='0x6523acd890ec5853db6d9eb731d7892666dbd27e'
print('402 OK', a['scheme'], a['network'], a['maxAmountRequired'], a['payTo'], a['asset'])
PY
curl -sf "$URL/health"; echo
echo "$URL" > LIVE_URL
cd ..
python3 - <<'PY'
import re
s=open('README.md').read(); sec=open('paid-worker/README-live-section.md').read().rstrip()+"\n\n"
s=re.sub(r"## (Planned paid tier \(x402\)|Paid filtered endpoint \(x402\) — live)\n.*?(?=\n## )", sec.rstrip()+"\n", s, flags=re.S)
s=s.replace("No auth and no rate-limit games: it's static files.","No auth and no rate-limit games: it's static files (a paid, filtered x402 endpoint is also live, see below).")
open('README.md','w').write(s)
s=open('paid-worker/README.md').read().replace("# Paid tier (x402) — not deployed yet","# Paid tier (x402) — live at https://agent-bounty-feed.dailydollar.workers.dev")
open('paid-worker/README.md','w').write(s)
PY
export GH_CONFIG_DIR=/home/box/daily-dollar/accounts/gh-bot
python3 collect.py docs
git add README.md collect.py docs paid-worker
git -c user.name=dailydollar-bot -c user.email=dailydollar@mail.grokbot.com commit -qm "paid tier: x402 endpoint live on Cloudflare Workers (\$0.01 USDC on Base)" || true
git pull -q --rebase origin main && git push -q origin main && echo pushed
