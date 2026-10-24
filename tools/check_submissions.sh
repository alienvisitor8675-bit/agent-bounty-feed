#!/usr/bin/env bash
# List open 'bounty-submission' issues for review (read-only). Run at the 22:00 test-and-improve step.
export GH_CONFIG_DIR=/home/box/daily-dollar/accounts/gh-bot
gh issue list -R dailydollar-bot/agent-bounty-feed --label bounty-submission --state open \
  --json number,title,createdAt,url --jq '.[] | "#\(.number)  \(.createdAt)  \(.title)  \(.url)"'
