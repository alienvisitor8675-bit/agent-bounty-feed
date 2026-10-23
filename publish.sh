#!/usr/bin/env bash
# Refresh the public feed and push it (run hourly from the box rescan).
set -euo pipefail
cd "$(dirname "$0")"
export GH_CONFIG_DIR=/home/box/daily-dollar/accounts/gh-bot
git pull -q --rebase origin main || true
python3 collect.py docs
git add docs
if git diff --cached --quiet; then echo "no change"; exit 0; fi
git -c user.name=dailydollar-bot -c user.email=dailydollar@mail.grokbot.com commit -qm "feed: refresh $(date -u +%Y-%m-%dT%H:%MZ)"
git push -q origin main
echo "pushed"
