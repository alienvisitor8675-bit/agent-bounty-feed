#!/usr/bin/env bash
# Refresh the public feed and push it (run hourly from the box rescan).
set -euo pipefail
cd "$(dirname "$0")"
export GH_CONFIG_DIR=/home/box/daily-dollar/accounts/gh-bot
git pull -q --rebase origin main || true
python3 collect.py docs
# Weekly 'State of Agent Bounties' report: regenerate on Sundays (UTC) or if missing; cheap, so also fine to run by hand.
if [ "$(date -u +%u)" = 7 ] || [ ! -f docs/report/index.html ]; then python3 report.py || echo "WARN report failed"; fi
# Cheap liveness check of the paid x402 endpoint (unpaid GET -> expect 402; never pays).
if [ -s paid-worker/LIVE_URL ]; then
  PURL=$(cat paid-worker/LIVE_URL)
  pc=$(curl -s -m 15 -o /dev/null -w '%{http_code}' "$PURL/v1/bounties" || echo 000)
  hc=$(curl -s -m 15 -o /dev/null -w '%{http_code}' "$PURL/health" || echo 000)
  echo "$(date '+%F %T %Z') paid=$pc health=$hc" >> /home/box/daily-dollar/ledger/paid-endpoint-checks.log
  [ "$pc" = 402 ] || echo "WARN paid endpoint returned $pc (expected 402)"
fi
git add docs data
if git diff --cached --quiet; then echo "no change"; exit 0; fi
git -c user.name=dailydollar-bot -c user.email=dailydollar@mail.grokbot.com commit -qm "feed: refresh $(date -u +%Y-%m-%dT%H:%MZ)"
git push -q origin main
echo "pushed"
