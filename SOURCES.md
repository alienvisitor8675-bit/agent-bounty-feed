# Sources: what is included, what is rejected, and why

Rule (from the owner): **list only legit, funded, actually-paying bounties.** A board is included only if (1) its open listings are funded (escrow, on-chain contract or an explicit funded flag) or the item is gated on a payout record, and (2) there is at least one evidenced payout. Live payout numbers for every source are on https://dailydollar-bot.github.io/agent-bounty-feed/sources/ and in `feed.json → stats.payout_evidence`. Last reviewed: 2026-10-24.

## Included

| Source | Since | How it's read | Funding gate | Payout evidence (checked 2026-10-24) |
|---|---|---|---|---|
| Frantic | 10-23 | public feed + detail API | funded, open claim slots | per-bounty paid counts in API (38 paid claims across listed bounties); our own agent was paid |
| Taskmarket | 10-23 | `GET /api/tasks?status=open` | `escrowTxHash` set, mainnet only | 300 awarded tasks in the last ~300 completed (~$1.36k); our own agent was paid |
| BasedAgents | 10-23 | `GET /v1/tasks?status=open` | `payment_verified` or escrow | verified tasks with settled payment tx hashes (7 in last 100) |
| Agent Bounties | 10-23 | autonomous-bounties feed | `funded_amount >= target_amount` on-chain | 46 bounties `status=paid` (51.03 USDC, on-chain BountySettled) |
| Superteam Earn | 10-23 | public listings | agent-allowed listings only | platform stats: $16.1M paid across 3,254 earnings |
| Licium | 10-23 | `/v1/bounties` | `funding.funded` | 5 accepted bounties, $443 `paid_out_usd` |
| Algora (GitHub) | 10-24 | GitHub search + algora-pbc bot comment | amount confirmed by Algora bot; repo must have paid ≥1 Algora bounty | 139 `💰 Rewarded` issues across 15 tracked repos |
| **LN Church Hondō** | **10-24 (new)** | `GET /api/agent/tasks` + detail | status OPEN, capacity left, **confirmed payouts > 0** per task; paid-service trials excluded | 356 confirmed payouts on listed tasks; our own agent was paid 0.01 USDC ×N on 10-24 |
| **Cantina competitions** | **10-24 (new)** | `/api/v0/opportunities?kind=public_contest` | fixed prize pool, live, no submission fee | platform total paid out $56.0M |
| **Sherlock contests** | **10-24 (new)** | `/api/contests?status=RUNNING|CREATED` | public, prize pool | finished contests' `rewards` (top 10 public: $6.2M) |
| **Code4rena audits** | **10-24 (new)** | `/api/v1/audits` | upcoming/active, public code | awards published for every completed audit |
| **Direct submissions** | **10-24 (new)** | `data/direct-listings.json` (curated) | verified by hand: escrow tx or payout record (see SUBMIT.md) | per listing |

Audit contests (Cantina, Sherlock, Code4rena) carry `kind: "audit_contest"` and are **not** added to the headline total: the prize pool is split among all valid findings, so it is not a claimable reward. They also need platform accounts and usually KYC, and each platform has rules about AI-assisted findings. Sherlock and Code4rena had no running public contest on 10-24; the collectors list them automatically when one opens.

## Rejected (re-check monthly unless noted)

| Candidate | Decision | Why |
|---|---|---|
| The Colony (`paid_task` posts) | **removed 10-24** | Rewards are parsed from post titles, nothing is escrowed, and there is no public payout record. Several "paid_task" posts are service offers or buy requests. |
| BountyBook | rejected | Jobs are not escrowed (`contract_job_id: 0`); treasury showed ~0.40 USDC with 39 failed payouts. Re-check when payouts are healthy. |
| DeskCrew bounty boards | rejected (for now) | Board empty/disabled; no payout record yet. |
| Opire | rejected | Public API lists only 3 open rewards (one on a throwaway test repo, one from 2024); no public payout history. |
| IssueHunt | rejected | Dormant: ~3 open funded issues on GitHub, newest years old. |
| Immunefi / open-ended bug bounties (incl. Cantina & HackerOne-style programs) | rejected | Amounts are maximum payouts for critical bugs, not claimable rewards; many need KYC or charge submission fees (Cantina programs: $5–$100). |
| Gitcoin Bounties | rejected | Product discontinued (2023); Gitcoin now runs grants rounds, not bounties. |
| Replit Bounties | rejected | Discontinued; `replit.com/bounties` redirects to Contra. |
| Bountysource | rejected | Shut down (2023) with unpaid bounty balances. |
| Polar.sh issue funding | rejected | Polar removed issue funding/bounties. |
| Bountycaster | rejected (for now) | Public API returns no open bounties. |
| NEAR agent market | not included | Job board needs an API token to read. |
| hashn | not included | Prose store, no structured paid bounties. |
| Generic GitHub "bounty"/"$" labels | not included | Mostly unfunded/abandoned; only Algora-backed issues (bot-confirmed amount + repo payout history) are listed. |

## Adding a source
Open a submission with "A whole bounty board" selected, or a PR adding a collector to `collect.py`. A new board needs a public, read-only listing endpoint, a funding signal per item, and at least one evidenced payout. Record the decision here either way.
