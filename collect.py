#!/usr/bin/env python3
"""Agent Bounty Feed collector.

Collects currently open, claimable, *paid* bounties from public agent bounty
boards (no auth, read-only GETs) and writes:
  docs/feed.json  (JSON, schema in README)
  docs/feed.xml   (RSS 2.0)
  docs/llms.txt   (markdown for LLMs/humans)
  docs/index.html (simple HTML table)
Stdlib only. Never reads or writes credentials.
"""
import json, re, sys, os, html, datetime, urllib.request, urllib.error
from email.utils import format_datetime

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
SITE = os.environ.get("FEED_SITE", "https://dailydollar-bot.github.io/agent-bounty-feed")
UA = "agent-bounty-feed/1.0 (+https://github.com/dailydollar-bot/agent-bounty-feed)"
NOW = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
NOW_S = NOW.isoformat().replace("+00:00", "Z")
TIP = "0x6523acd890Ec5853db6D9eB731D7892666dbd27e"
CONTACT = "dailydollar@mail.grokbot.com"
# Paid x402 endpoint: only advertised once paid-worker/LIVE_URL exists (written after a live 402 check).
_live = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paid-worker", "LIVE_URL")
PAID = open(_live).read().strip() if os.path.exists(_live) else ""


def get(url, timeout=25, tries=3):
    import time
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError):
            if n == tries - 1:
                raise
            time.sleep(3 * (n + 1))


def clean(s, n=200):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


USD_LIKE = ("USD", "USDC", "USDT", "USDG", "PYUSD")


def item(source, id_, title, reward, currency, url, deadline=None, eligibility="", network=None, extra=None,
         requires=None, slots_left=None, competition=None, track=None, verified=""):
    """requires: list from REQUIRES_VOCAB. slots_left: int or None (unlimited / not exposed).
    competition: dict (submissions/attempts so far). track: payout_track_record dict or None."""
    est = round(float(reward), 2) if reward is not None and (currency or "").upper() in USD_LIKE else None
    return {
        "source": source,
        "id": f"{source}:{id_}",
        "title": clean(title, 180),
        "reward": round(float(reward), 6) if reward is not None else None,
        "currency": currency,
        "network": network,
        "deadline": deadline,
        "url": url,
        "eligibility": clean(eligibility, 400),
        "est_usd": est,
        "requires": sorted(set(requires or [])),
        "slots_left": slots_left,
        "competition": competition or None,
        "payout_track_record": track,
        "verified": {"checked_at": NOW_S, "how": verified} if verified else None,
        "fetched_at": NOW_S,
        **({"extra": extra} if extra else {}),
    }


REQUIRES_VOCAB = {
    "agent_account": "Register/enlist an agent account on the source board.",
    "wallet_evm": "An EVM wallet (Base or the listed chain) to receive USDC.",
    "wallet_solana": "A Solana wallet to receive the reward.",
    "bond": "A refundable claim bond / deposit is locked when claiming.",
    "stake": "A stake is required and can be slashed.",
    "kyc": "Payout needs identity verification (e.g. Stripe Connect / KYC).",
    "github": "A GitHub account (work is delivered as a pull request).",
    "x_account": "An X/Twitter account (the task asks for a post or reply).",
    "public_post": "Publishing a public post/article (Medium, dev.to, Bluesky, X...).",
    "human_only": "The board marks this as human-only; agents should not apply.",
    "purchase": "The task asks you to spend or buy something first.",
}
DROPS = {}


def drop(reason):
    DROPS[reason] = DROPS.get(reason, 0) + 1


def text_requires(t):
    t = (t or "").lower()
    r = []
    if re.search(r"\b(x\.com|twitter|tweet|repost|quote[- ]post)\b", t):
        r.append("x_account")
    if re.search(r"\b(medium|dev\.to|bluesky|publish (?:your|an|a)|blog post|article)\b", t):
        r.append("public_post")
    if re.search(r"\b(buy|purchase|hold) (?:\$?\d|some|it|the token|tokens?)\b", t):
        r.append("purchase")
    return r


def past(deadline):
    if not deadline:
        return False
    try:
        d = datetime.datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return d <= NOW
    except ValueError:
        return False


# ---------------------------------------------------------------- sources
def frantic():
    out = []
    feed = get("https://gofrantic.com/feed.json")
    for it in feed.get("items", []):
        f = it.get("_frantic", {})
        slots = f.get("claim_slots", {})
        if slots.get("available", 1) <= 0:
            drop("frantic: no claim slots left")
            continue
        extra, elig = {"claim_slots": slots}, "Enlist a Frantic agent (gofrantic.com). Paid in USDC after auto + sponsor review."
        slots_left, track, comp, how = slots.get("available"), None, None, "feed.json claim_slots"
        try:
            b = get(f["api_url"])["bounty"]
            if b.get("work_status") != "open" or not b.get("funded", True) or b.get("cancellation_status"):
                drop("frantic: not open/funded on detail API")
                continue
            cp = b.get("claim_progress") or {}
            slots_left = cp.get("available", slots_left)
            if slots_left is not None and slots_left <= 0:
                drop("frantic: no claim slots left")
                continue
            track = {k: cp.get(k, 0) for k in ("paid", "accepted", "rejected", "expired")}
            track["basis"] = "this bounty's claims so far (Frantic API)"
            q = b.get("quality") or {}
            if q.get("count"):
                track["review_avg_score"] = q.get("average_score")
            comp = {"active_claims": cp.get("active"), "delivered_awaiting_review": cp.get("delivered")}
            extra["claim_window_minutes"] = b.get("claim_window_minutes")
            extra["required_artifacts"] = b.get("required_artifacts")
            if b.get("claim_window_minutes"):
                elig += f" Claim window {b.get('claim_window_minutes')} min."
            if b.get("required_artifacts"):
                elig += f" Artifacts: {', '.join(b['required_artifacts'])}."
            elig += f" So far {cp.get('paid',0)} paid / {cp.get('rejected',0)} rejected."
            how = "Frantic detail API: work_status=open, funded, claim slots available"
        except Exception:
            pass
        out.append(item("frantic", f.get("number"), re.sub(r"^#\d+\s*|\s*·\s*\$[\d.]+$", "", it.get("title", "")),
                        f.get("price_usd"), "USD", it.get("url"), None, elig, "base (USDC)", extra,
                        ["agent_account", "wallet_evm"], slots_left, comp, track, how))
    return out


TM_CHAINS = {"8453": "base", "84532": "base-sepolia", "4217": "tempo"}
_tm_track = None


def taskmarket_requesters():
    """Count tasks each requester has completed with an award (last ~300 completed tasks)."""
    global _tm_track
    if _tm_track is not None:
        return _tm_track
    _tm_track, cursor = {}, None
    for _ in range(3):
        try:
            d = get("https://api.taskmarket.dev/api/tasks?status=completed&limit=100" + (f"&cursor={cursor}" if cursor else ""))
        except Exception:
            break
        for t in d.get("tasks", []):
            r = (t.get("requester") or "").lower()
            if t.get("awardCount"):
                _tm_track[r] = _tm_track.get(r, 0) + 1
        cursor = d.get("nextCursor")
        if not d.get("hasMore") or not cursor:
            break
    return _tm_track


def taskmarket():
    out, cursor, pages = [], None, 0
    track = taskmarket_requesters()
    while pages < 5:
        u = "https://api.taskmarket.dev/api/tasks?status=open&limit=100" + (f"&cursor={cursor}" if cursor else "")
        d = get(u)
        for t in d.get("tasks", []):
            if t.get("status") != "open" or not t.get("submissionWindowOpen", True) or t.get("phase") not in (None, "active"):
                drop("taskmarket: not open / submission window closed")
                continue
            if t.get("taskVisibility", "public") != "public" or t.get("hasAccessPassword"):
                drop("taskmarket: private or password-protected")
                continue
            if past(t.get("expiryTime")):
                drop("expired (deadline passed)")
                continue
            if t.get("claimedBy") and t.get("mode") != "bounty":
                drop("taskmarket: already claimed")
                continue
            desc = t.get("description") or ""
            m = re.match(r"\s*Title:\s*(.+)", desc)
            title = m.group(1) if m else desc.strip().split("\n")[0]
            reward = int(t.get("reward") or 0) / 1e6
            if reward <= 0 or not t.get("escrowTxHash"):
                drop("unfunded / no escrow")
                continue
            chain = TM_CHAINS.get(str(t.get("chainId")), f"eip155:{t.get('chainId')}")
            if chain == "base-sepolia":
                drop("testnet")
                continue
            elig = f"mode={t.get('mode')} (requester picks winner(s)); {t.get('submissionCount',0)} submissions so far; platform fee {int(t.get('platformFeeBps') or 0)/100:g}%; reward escrowed on-chain"
            req = ["agent_account", "wallet_evm"] + text_requires(desc)
            if t.get("stakeRequired"):
                elig += f"; STAKE REQUIRED ({t.get('stakeBps')} bps)"
                req.append("stake")
            elig += ". Needs a Taskmarket wallet (CLI: taskmarket.dev/skill.md)."
            r = (t.get("requester") or "").lower()
            tr = {"requester_awarded_tasks": track.get(r, 0), "basis": "requester's completed+awarded tasks among the last ~300 completed on Taskmarket"} if track else None
            if "purchase" in req:
                drop("asks the solver to buy/hold a token")
                continue
            out.append(item("taskmarket", t.get("referenceCode") or t["id"], title, reward, "USDC",
                            f"https://taskmarket.dev/tasks/{t.get('referenceCode') or t['id']}",
                            t.get("expiryTime"), elig, chain,
                            {"mode": t.get("mode"), "chain_id": t.get("chainId")},
                            req, None, {"submissions": t.get("submissionCount")}, tr,
                            "Taskmarket API: status=open, submissionWindowOpen, escrowTxHash set, not expired"))
        cursor = d.get("nextCursor")
        pages += 1
        if not d.get("hasMore") or not cursor:
            break
    return out


def basedagents():
    out = []
    d = get("https://api.basedagents.ai/v1/tasks?status=open&limit=100")
    for t in d.get("tasks", []):
        b = t.get("bounty") or {}
        amt = float(b.get("amount_display") or 0)
        if t.get("status") != "open" or not t.get("claimable") or t.get("claimed_by_agent_id"):
            drop("basedagents: not claimable")
            continue
        if amt <= 0:
            drop("no cash reward")
            continue
        if past(t.get("expires_at")):
            drop("expired (deadline passed)")
            continue
        # Only list tasks whose bounty payment is actually verified/escrowed; 'pending' = promise only.
        if not (t.get("payment_verified") or t.get("escrow")):
            drop("unfunded / no escrow")
            continue
        net = {"eip155:8453": "base"}.get(b.get("network"), b.get("network"))
        elig = f"category={t.get('category')}; needs capabilities {', '.join(t.get('required_capabilities') or []) or 'none listed'}. Register a BasedAgents agent to claim."
        out.append(item("basedagents", t["task_id"], t.get("title"), amt, b.get("token") or "USDC",
                        f"https://basedagents.ai/tasks/{t['task_id']}", t.get("expires_at"), elig, net, None,
                        ["agent_account", "wallet_evm"] + text_requires(t.get("description")),
                        1, None, None,
                        "BasedAgents API: open, claimable, unclaimed, payment verified/escrowed"))
    return out


def agentbounties():
    out = []
    d = get("https://api.agentbounties.app/v1/base/autonomous-bounties/feed?network=base-mainnet&claimable_only=true")
    for b in d if isinstance(d, list) else d.get("items", []):
        if b.get("status") != "claimable":
            drop("agentbounties: not claimable")
            continue
        doc = (b.get("terms") or {}).get("document") or {}
        ct = doc.get("contract_terms") or {}
        reward = int(b.get("solver_reward") or 0) / 1e6
        if reward <= 0 or int(b.get("funded_amount") or 0) < int(b.get("target_amount") or 0):
            drop("unfunded / no escrow")
            continue
        bond = int(b.get("claim_bond") or 0) / 1e6
        elig = f"On-chain bounty (Base), fully funded in contract. Claim bond {bond:g} USDC; claim window {int(ct.get('claim_window_seconds') or 0)//3600} h; verification {b.get('verification_mode')}."
        if b.get("verification_ready") is False:
            elig += " Verification not ready yet."
        dl = None
        if ct.get("funding_deadline"):
            dl = datetime.datetime.fromtimestamp(int(ct["funding_deadline"]), datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        req = ["wallet_evm"] + (["bond"] if bond else [])
        if int(b.get("required_external_spend") or 0):
            req.append("purchase")
        out.append(item("agentbounties", b["bounty_id"][:18], doc.get("title") or b["bounty_id"], reward, "USDC",
                        f"https://agentbounties.app/bounties/{b['bounty_id']}", dl, elig, "base",
                        {"claim_bond_usdc": bond}, req, 1, None, None,
                        "Agent Bounties API: status=claimable, funded_amount >= target_amount"))
    return out


MONEY = re.compile(r"\$\s?(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s?(USDC|USDT|USD)\b", re.I)


def colony():
    out = []
    d = get("https://thecolony.ai/api/v1/posts?post_type=paid_task&limit=50")
    for p in d.get("items", []):
        t = p.get("title") or ""
        if t.lower().startswith("for hire") or "for-hire" in (p.get("tags") or []):
            continue  # service offers, not bounties
        if p.get("status") != "open" or p.get("accepting_submissions") is False or p.get("closed_at"):
            drop("colony: closed / not accepting submissions")
            continue
        m = MONEY.search(t)
        if not m:
            continue
        amt = float(m.group(1) or m.group(2))
        if amt <= 0:
            continue
        req = ["agent_account"] + text_requires(t + " " + (p.get("body") or "")[:3000])
        if "purchase" in req:
            drop("asks the solver to buy/hold a token")
            continue
        elig = f"Colony paid_task post by @{(p.get('author') or {}).get('username')}; reward parsed from the title (not escrowed), read the post for exact terms; {p.get('comment_count',0)} replies so far."
        out.append(item("colony", p["id"][:8], t, amt, "USD", f"https://thecolony.ai/post/{p['id']}", None, elig, None,
                        {"colony": p.get("colony_name"), "escrowed": False}, req, None,
                        {"replies": p.get("comment_count", 0)}, None, "Colony API: status=open, accepting_submissions"))
    return out


def superteam():
    out = []
    d = get("https://superteam.fun/api/listings?take=100")
    for x in d if isinstance(d, list) else d.get("listings", []):
        if x.get("status") != "OPEN" or x.get("isWinnersAnnounced") or past(x.get("deadline")):
            drop("superteam: closed / winners announced / past deadline")
            continue
        if x.get("agentAccess") == "HUMAN_ONLY":
            drop("human-only listing")
            continue
        amt = x.get("rewardAmount") or 0
        if not amt:
            continue
        elig = f"Superteam Earn {x.get('type')}; agentAccess={x.get('agentAccess')}; sponsor {(x.get('sponsor') or {}).get('name')}. Usually contest-style (winners picked by sponsor)."
        out.append(item("superteam", x.get("slug"), x.get("title"), amt, x.get("token") or "USDC",
                        f"https://superteam.fun/earn/listing/{x.get('slug')}", x.get("deadline"), elig, "solana", None,
                        ["agent_account", "wallet_solana"], None, None, None, "Superteam API: OPEN, agent access, before deadline"))
    return out


def licium():
    out = []
    d = get("https://www.licium.ai/v1/bounties?status=open&limit=200")
    for b in d.get("data", []):
        amt = float(b.get("solver_payout_usd") or b.get("amount_usd") or 0)
        if amt <= 0 or not (b.get("funding") or {}).get("funded"):
            drop("unfunded / no escrow")
            continue
        if past(b.get("closes_at")):
            drop("expired (deadline passed)")
            continue
        out.append(item("licium", b["id"][:8], b.get("title"), amt, "USD", f"https://www.licium.ai/bounties/{b['id']}",
                        b.get("closes_at"), f"Licium {b.get('selection_mode')}; category {b.get('category')}.", None, None,
                        ["agent_account"], None, None, None, "Licium API: open and funded"))
    return out


# ---- Algora bounties on GitHub (via the bot's authenticated gh CLI; read-only search + comments)
ALGORA_BOT = "algora-pbc[bot]"
ALGORA_AMT = re.compile(r"##\s*💎\s*\$([\d,]+(?:\.\d+)?)\s*bounty(?:\s*\[•\s*([^\]]+)\]\((https://algora\.io/[^)]+)\))?")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def gh(*args):
    import subprocess
    env = dict(os.environ)
    env.setdefault("GH_CONFIG_DIR", "/home/box/daily-dollar/accounts/gh-bot")
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=60, env=env)
    if r.returncode != 0:
        raise RuntimeError(clean(r.stderr, 160))
    return json.loads(r.stdout)


def algora():
    import time
    os.makedirs(CACHE, exist_ok=True)
    cpath = os.path.join(CACHE, "algora-repo-track.json")
    try:
        rtrack = json.load(open(cpath))
    except Exception:
        rtrack = {}
    since = (NOW - datetime.timedelta(days=365)).date().isoformat()
    q = f'label:"💎 Bounty" state:open is:issue commenter:app/algora-pbc -label:"💰 Rewarded" updated:>{since}'
    issues, page = [], 1
    while page <= 3:
        d = gh("-X", "GET", "search/issues", "-f", f"q={q}", "-f", "per_page=100", "-f", f"page={page}", "-f", "sort=updated")
        issues += d.get("items", [])
        if len(d.get("items", [])) < 100:
            break
        page += 1
    out = []
    for iss in issues:
        labels = [l["name"] for l in iss.get("labels", [])]
        low = " ".join(labels).lower()
        if iss.get("state") != "open" or "rewarded" in low or "on-hold" in low or "on hold" in low or iss.get("locked"):
            drop("algora: rewarded / on hold / locked")
            continue
        repo = iss["repository_url"].split("/repos/")[1]
        try:
            cs = gh(f"repos/{repo}/issues/{iss['number']}/comments?per_page=100")
        except Exception:
            drop("algora: comments unreadable")
            continue
        bot = [c for c in cs if c.get("user", {}).get("login") == ALGORA_BOT]
        amt, sponsor, sponsor_url = None, None, None
        posted = None
        for c in bot:
            m = ALGORA_AMT.search(c.get("body") or "")
            if m:
                amt = float(m.group(1).replace(",", "")); sponsor = (m.group(2) or "").strip() or None; sponsor_url = m.group(3)
                posted = c.get("created_at")
        if not amt:
            drop("algora: no bounty amount from Algora bot")
            continue
        joined = " ".join(c.get("body") or "" for c in bot).lower()
        if "has been rewarded" in joined or "bounty was cancelled" in joined or "bounty has been cancelled" in joined:
            drop("algora: rewarded / cancelled per Algora bot")
            continue
        attempts = sum(1 for c in cs if re.search(r"(?m)^\s*/attempt\b", c.get("body") or ""))
        claims = sum(1 for c in bot if "claims the bounty" in (c.get("body") or ""))
        if repo not in rtrack or rtrack[repo].get("at", "") < (NOW - datetime.timedelta(days=1)).isoformat():
            try:
                time.sleep(2.2)  # search API: 30 req/min
                n = gh("-X", "GET", "search/issues", "-f", f'q=repo:{repo} label:"💰 Rewarded"', "-f", "per_page=1")["total_count"]
                ri = gh(f"repos/{repo}")
                rtrack[repo] = {"rewarded": n, "archived": bool(ri.get("archived")), "pushed_at": ri.get("pushed_at"), "at": NOW.isoformat()}
            except Exception:
                pass
        tr = {"repo_rewarded_bounties": rtrack[repo]["rewarded"], "basis": "issues in this repo labelled 💰 Rewarded by Algora"} if repo in rtrack else None
        if rtrack.get(repo, {}).get("archived"):
            drop("algora: repository archived")
            continue
        pushed = rtrack.get(repo, {}).get("pushed_at") or ""
        if pushed and pushed < (NOW - datetime.timedelta(days=180)).isoformat():
            drop("algora: repo inactive >180 days (bounty likely abandoned)")
            continue
        if not tr or not tr["repo_rewarded_bounties"]:
            # Quality gate: repos that have never paid an Algora bounty (some post hundreds of unpaid "bounties") are not listed.
            drop("algora: repo has never paid an Algora bounty")
            continue
        req = ["github", "kyc"] + (["human_only"] if "humans only" in low or "human only" in low else [])
        elig = (f"Algora bounty on GitHub ({repo}); sponsor {sponsor or 'see issue'}. Comment /attempt #{iss['number']}, then open a PR with /claim #{iss['number']}. "
                f"Paid in USD via Algora (Stripe payout, needs KYC). Bounty posted {(posted or '?')[:10]}; {attempts} /attempt comments, {claims} claiming PRs so far.")
        if "ai only" in low or "ai agent friendly" in low:
            elig += " Labelled AI-agent friendly."
        out.append(item("algora", f"{repo}#{iss['number']}", iss.get("title"), amt, "USD", iss["html_url"], None, elig, None,
                        {"repo": repo, "labels": labels, "sponsor_url": sponsor_url, "bounty_posted_at": posted, "issue_updated_at": iss.get("updated_at"), "repo_pushed_at": rtrack.get(repo, {}).get("pushed_at")},
                        req, None, {"attempts": attempts, "claiming_prs": claims, "comments": iss.get("comments")}, tr,
                        "GitHub: issue open, 💎 Bounty label, amount from the algora-pbc[bot] comment, not rewarded/on-hold"))
    json.dump(rtrack, open(cpath, "w"))
    return out


SOURCES = {
    "frantic": ("https://gofrantic.com", frantic),
    "taskmarket": ("https://taskmarket.dev", taskmarket),
    "basedagents": ("https://basedagents.ai", basedagents),
    "agentbounties": ("https://agentbounties.app", agentbounties),
    "colony": ("https://thecolony.ai", colony),
    "superteam": ("https://superteam.fun/earn", superteam),
    "licium": ("https://www.licium.ai", licium),
    "algora": ("https://algora.io", algora),
}
NOT_INCLUDED = {
    "near-agent-market": "market.near.ai job board needs an API token to read; not included in the free feed.",
    "hashn": "hashn store is prose, not structured paid bounties; not included.",
    "github-other-bounty-labels": "Generic 'bounty' / '$' labels on GitHub are mostly unfunded or abandoned; only Algora-backed bounties (amount confirmed by the algora-pbc bot) are listed.",
}


def to_usd(it):
    return it.get("est_usd") or 0


def make_stats(items, status):
    by = {}
    for i in items:
        s = by.setdefault(i["source"], {"items": 0, "usd": 0.0})
        s["items"] += 1
        s["usd"] = round(s["usd"] + to_usd(i), 2)
    for name, st in status.items():
        by.setdefault(name, {"items": 0, "usd": 0.0})["ok"] = st["ok"]
    day = (NOW - datetime.timedelta(days=1)).isoformat().replace("+00:00", "Z")
    req = {}
    for i in items:
        for r in i["requires"]:
            req[r] = req.get(r, 0) + 1
    return {
        "items": len(items),
        "total_usd": round(sum(to_usd(i) for i in items), 2),
        "by_source": by,
        "new_last_24h": sum(1 for i in items if (i.get("first_seen") or "") >= day),
        "no_bond_no_stake_no_kyc": sum(1 for i in items if not set(i["requires"]) & {"bond", "stake", "kyc", "purchase", "human_only"}),
        "requires_counts": dict(sorted(req.items())),
        "dropped_this_refresh": dict(sorted(DROPS.items(), key=lambda kv: -kv[1])),
        "last_refresh": NOW_S,
        "refresh_interval": "hourly",
    }


# ---------------------------------------------------------------- writers
def write_all(items, status):
    os.makedirs(OUT, exist_ok=True)
    total = round(sum(to_usd(i) for i in items), 2)
    stats = make_stats(items, status)
    feed = {
        "name": "Agent Bounty Feed",
        "description": "Open, claimable, paid bounties for AI agents, collected hourly from public agent bounty boards.",
        "home_page_url": SITE + "/",
        "feed_url": SITE + "/feed.json",
        "schema_version": "1.1",
        "generated_at": NOW_S,
        "count": len(items),
        "total_open_usd_equiv": total,
        "stats": stats,
        "requires_vocabulary": REQUIRES_VOCAB,
        "sources": status,
        "not_included": NOT_INCLUDED,
        "sponsored": [],
        "tip_address": {"network": "base", "token": "USDC", "address": TIP},
        "contact": CONTACT,
        "paid_endpoint": ({"url": PAID + "/v1/bounties", "protocol": "x402", "price": "0.01", "token": "USDC", "network": "base",
                           "pay_to": TIP, "facilitator": "https://facilitator.payai.network",
                           "filters": ["source", "min_usd", "network", "no_bond", "exclude_requires", "since", "sort", "limit"], "info": PAID + "/"} if PAID else None),
        "mcp_endpoint": (PAID + "/mcp" if PAID else None),
        "items": items,
    }
    with open(os.path.join(OUT, "feed.json"), "w") as f:
        json.dump(feed, f, indent=1, ensure_ascii=False)

    # RSS
    def fs(i):
        try:
            return format_datetime(datetime.datetime.fromisoformat(i["first_seen"].replace("Z", "+00:00")))
        except Exception:
            return format_datetime(NOW)
    rss = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>',
           "<title>Agent Bounty Feed</title>", f"<link>{SITE}/</link>",
           f'<atom:link href="{SITE}/feed.xml" rel="self" type="application/rss+xml"/>',
           "<description>Open, claimable, paid bounties for AI agents (hourly).</description>",
           f"<lastBuildDate>{format_datetime(NOW)}</lastBuildDate>"]
    for i in items:
        r = f"{i['reward']:g} {i['currency']}" if i["reward"] is not None else "?"
        desc = f"[{i['source']}] {r}. Deadline: {i['deadline'] or 'none listed'}. Requires: {', '.join(i['requires']) or 'nothing special'}. {i['eligibility']}"
        rss.append("<item>" + f"<title>{html.escape(f'{r} · {i['title']}')}</title><link>{html.escape(i['url'])}</link>"
                   + f'<guid isPermaLink="false">{html.escape(i["id"])}</guid><category>{i["source"]}</category><pubDate>{fs(i)}</pubDate>'
                   + f"<description>{html.escape(desc)}</description></item>")
    rss.append("</channel></rss>")
    with open(os.path.join(OUT, "feed.xml"), "w") as f:
        f.write("\n".join(rss))

    # llms.txt
    def short(i):
        bits = [f"requires: {', '.join(i['requires']) or 'nothing special'}"]
        if i.get("slots_left") is not None:
            bits.append(f"slots left {i['slots_left']}")
        if i.get("competition"):
            bits.append("competition " + ", ".join(f"{k} {v}" for k, v in i["competition"].items() if v is not None))
        t = i.get("payout_track_record")
        if t:
            bits.append("track record " + ", ".join(f"{k} {v}" for k, v in t.items() if k != "basis"))
        bits.append(f"first seen {i.get('first_seen')}")
        return "; ".join(bits)

    L = ["# Agent Bounty Feed", "",
         "> Open, claimable, paid bounties for AI agents, collected hourly from public agent bounty boards and Algora (GitHub). "
         "Every item is re-checked each refresh (open, funded/escrowed where the board exposes it, slots left, not expired). "
         "Free, read-only, no auth. Machine-readable: " + SITE + "/feed.json (JSON) and " + SITE + "/feed.xml (RSS)."
         + (f" MCP server (Streamable HTTP, free): {PAID}/mcp" if PAID else ""), "",
         f"Updated: {NOW_S} · {len(items)} open bounties · ~${total:g} total (USD-equivalent) · {stats['new_last_24h']} new in the last 24 h · "
         f"{stats['no_bond_no_stake_no_kyc']} need no bond, stake or KYC.", "",
         "Each item: source, id, title, reward, currency, est_usd, network, deadline, url, eligibility, requires[], slots_left, "
         "competition, payout_track_record, verified, first_seen, fetched_at. requires[] values: "
         + "; ".join(f"{k} = {v}" for k, v in REQUIRES_VOCAB.items()) + ". "
         "Always confirm terms on the source board before working; this feed only links out.", "",
         "## Sources", ""]
    for s, st in status.items():
        L.append(f"- {s}: {st['count']} items, ${stats['by_source'].get(s, {}).get('usd', 0):g} ({'ok' if st['ok'] else 'unreachable: ' + st.get('error','')}) — {st['home']}")
    for s, why in NOT_INCLUDED.items():
        L.append(f"- {s}: not included — {why}")
    if DROPS:
        L += ["", "Dropped this refresh (not listed): " + "; ".join(f"{k}: {v}" for k, v in stats["dropped_this_refresh"].items()) + "."]
    L += ["", "## Open bounties (largest reward first)", ""]
    for i in items:
        r = f"{i['reward']:g} {i['currency']}"
        L.append(f"- [{r}] [{i['title']}]({i['url']}) — {i['source']}; deadline {i['deadline'] or 'none listed'}; {short(i)}. {i['eligibility']}")
    L += ["", "## Sponsored", "", f"(empty) Clearly-labelled sponsored slot for agent bounty boards and agent tooling. Contact {CONTACT}.", "",
          "## Support", "", f"Tips (USDC on Base): {TIP}", ""]
    if PAID:
        L += ["## MCP server (free)", "",
              f"Remote MCP endpoint (Streamable HTTP, no auth): {PAID}/mcp — tools: list_bounties, get_new_bounties, get_bounty, get_feed_stats. "
              "Serves this same hourly feed. Claude Code: `claude mcp add --transport http agent-bounty-feed " + PAID + "/mcp`.", "",
              "## Paid filtered endpoint (x402)", "",
              f"GET {PAID}/v1/bounties — same data, filtered server-side: source (csv), min_usd, network, no_bond=1, exclude_requires (csv, e.g. kyc,stake,bond), "
              "since (ISO-8601; returns only items first seen after it, newest first), sort (first_seen|reward), limit. Responses include next_since for polling. "
              f"$0.01 USDC on Base per call via x402 (HTTP 402; v1 X-PAYMENT or v2 PAYMENT-SIGNATURE; facilitator PayAI). "
              f"Unpaid requests get a 402 with payment requirements; x402 clients pay and retry automatically. Bad parameters get a free 400. Free info: {PAID}/ · health: {PAID}/health. "
              "The free feed above stays free.", ""]
    with open(os.path.join(OUT, "llms.txt"), "w") as f:
        f.write("\n".join(L))

    # index.html
    def cell_req(i):
        return " ".join(f'<span class="tag{" warn" if r in ("bond","stake","kyc","purchase","human_only") else ""}" title="{html.escape(REQUIRES_VOCAB.get(r, r))}">{r}</span>' for r in i["requires"]) or "—"

    def cell_track(i):
        t = i.get("payout_track_record")
        s = ", ".join(f"{k.replace('_',' ')} {v}" for k, v in (t or {}).items() if k != "basis") if t else "—"
        c = i.get("competition") or {}
        cs = ", ".join(f"{k.replace('_',' ')} {v}" for k, v in c.items() if v is not None)
        sl = "" if i.get("slots_left") is None else f"<b>{i['slots_left']}</b> slots left<br>"
        return sl + html.escape(s) + (f"<br><small>{html.escape(cs)}</small>" if cs else "")

    rows = "\n".join(
        f"<tr><td>{html.escape(f'{i['reward']:g} {i['currency']}')}</td><td><a href=\"{html.escape(i['url'])}\">{html.escape(i['title'])}</a>"
        f"<br><small>{html.escape(i['eligibility'])}</small></td>"
        f"<td>{i['source']}</td><td>{cell_req(i)}</td><td>{cell_track(i)}</td><td>{html.escape(str(i['deadline'] or '—'))[:10]}</td><td>{html.escape((i.get('first_seen') or '')[:10])}</td></tr>" for i in items)
    srcs = " · ".join(f"{s}: {st['count']} (${stats['by_source'].get(s, {}).get('usd', 0):g}){'' if st['ok'] else ' (down)'}" for s, st in status.items())
    drops = "; ".join(f"{k}: {v}" for k, v in stats["dropped_this_refresh"].items())
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "Dataset", "name": "Agent Bounty Feed",
        "description": "Open, claimable, paid bounties for AI agents, verified and collected hourly from public agent bounty boards and Algora.",
        "url": SITE + "/", "isAccessibleForFree": True, "dateModified": NOW_S,
        "creator": {"@type": "Organization", "name": "dailydollar-bot", "url": "https://github.com/dailydollar-bot"},
        "distribution": [
            {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": SITE + "/feed.json"},
            {"@type": "DataDownload", "encodingFormat": "application/rss+xml", "contentUrl": SITE + "/feed.xml"},
            {"@type": "DataDownload", "encodingFormat": "text/plain", "contentUrl": SITE + "/llms.txt"}],
    }).replace("</", "<\\/")
    paid_html = (f'''<h2>Use it from an agent</h2>
<p><b>MCP server (free):</b> <code>{html.escape(PAID)}/mcp</code> (Streamable HTTP, no auth). Tools: <code>list_bounties</code>, <code>get_new_bounties</code>, <code>get_bounty</code>, <code>get_feed_stats</code>.<br>
Claude Code: <code>claude mcp add --transport http agent-bounty-feed {html.escape(PAID)}/mcp</code><br>
Cursor / other clients: <code>{{"mcpServers":{{"agent-bounty-feed":{{"url":"{html.escape(PAID)}/mcp"}}}}}}</code></p>
<p><b>Paid, filtered endpoint (x402):</b> <code>GET {html.escape(PAID)}/v1/bounties?since=2026-10-24T00:00:00Z&amp;exclude_requires=kyc,stake,bond</code> — $0.01 USDC on Base per call, paid with <a href="https://x402.org">x402</a>. Filters: <code>source</code>, <code>min_usd</code>, <code>network</code>, <code>no_bond=1</code>, <code>exclude_requires</code>, <code>since</code> (new items only, newest first, with <code>next_since</code> for polling), <code>sort</code>, <code>limit</code>. <a href="{html.escape(PAID)}/">Info</a> · <a href="{html.escape(PAID)}/health">health</a>. The free feed stays free.</p>
''' if PAID else "")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Bounty Feed — open paid bounties for AI agents ({len(items)} open, ${total:g})</title>
<meta name="description" content="Hourly, verified feed of {len(items)} open, claimable, paid bounties for AI agents (${total:g} total) from Frantic, Taskmarket, Algora, Agent Bounties, The Colony, BasedAgents, Superteam Earn and Licium. JSON, RSS, llms.txt and a free MCP server.">
<link rel="alternate" type="application/rss+xml" title="Agent Bounty Feed" href="feed.xml">
<link rel="alternate" type="application/json" title="Agent Bounty Feed (JSON)" href="feed.json">
<link rel="alternate" type="text/plain" title="Agent Bounty Feed (llms.txt)" href="llms.txt">
<link rel="canonical" href="{SITE}/">
<script type="application/ld+json">{ld}</script>
<style>body{{font-family:system-ui,sans-serif;max-width:1200px;margin:2em auto;padding:0 1em;color:#222}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border-bottom:1px solid #ddd;padding:6px;vertical-align:top;text-align:left}}th{{background:#f4f4f4}}.sp{{border:2px dashed #bbb;padding:1em;margin:1em 0;color:#555}}code{{background:#f4f4f4;padding:1px 4px}}small{{color:#666}}.tag{{display:inline-block;background:#eef;border-radius:3px;padding:0 4px;margin:1px;font-size:12px}}.warn{{background:#fde8d8}}.stats{{display:flex;gap:1.5em;flex-wrap:wrap;background:#f7f7f7;padding:.8em 1em;border-radius:6px}}.stats div b{{display:block;font-size:22px}}</style></head><body>
<h1>Agent Bounty Feed</h1>
<p>Open, claimable, <b>paid</b> bounties for AI agents, refreshed and re-verified hourly from public boards. Free and read-only: <a href="feed.json"><code>feed.json</code></a> · <a href="feed.xml"><code>feed.xml</code></a> (RSS) · <a href="llms.txt"><code>llms.txt</code></a>{f' · <a href="{html.escape(PAID)}/mcp"><code>MCP</code></a>' if PAID else ''} · <a href="https://github.com/dailydollar-bot/agent-bounty-feed">source &amp; schema</a></p>
<div class="stats"><div><b>{len(items)}</b>open bounties</div><div><b>${total:g}</b>total (USD eq.)</div><div><b>{stats['new_last_24h']}</b>new in 24 h</div><div><b>{stats['no_bond_no_stake_no_kyc']}</b>no bond / stake / KYC</div><div><b>{len([s for s in status.values() if s['ok']])}/{len(status)}</b>sources up</div><div><b>{NOW_S[11:16]} UTC</b>{NOW_S[:10]} refresh</div></div>
<p><small>By source — {srcs}.{(' Dropped this refresh (not listed): ' + html.escape(drops) + '.') if drops else ''}</small></p>
<div class="sp"><b>Sponsored</b> — this slot is empty. Agent boards and agent tooling can sponsor a clearly-labelled listing here: {CONTACT}</div>
<table><tr><th>Reward</th><th>Bounty</th><th>Board</th><th>Requires</th><th>Slots · payout record · competition</th><th>Deadline</th><th>First seen</th></tr>
{rows}
</table>
{paid_html}<p>Always confirm terms on the source board; this page only links out. Payout track records are what each board exposes (e.g. Frantic per-bounty paid/rejected counts, Taskmarket requester award history, Algora repo rewards), not a guarantee. Tips (USDC on Base): <code>{TIP}</code></p>
</body></html>"""
    with open(os.path.join(OUT, "index.html"), "w") as f:
        f.write(page)

    # discovery: sitemap.xml + robots.txt (allow all)
    urls = ["/", "/llms.txt", "/feed.json", "/feed.xml"]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sm.append(f"<url><loc>{SITE}{u}</loc><lastmod>{NOW_S}</lastmod><changefreq>hourly</changefreq></url>")
    sm.append("</urlset>")
    with open(os.path.join(OUT, "sitemap.xml"), "w") as f:
        f.write("\n".join(sm) + "\n")
    with open(os.path.join(OUT, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")


def main():
    items, status = [], {}
    for name, (home, fn) in SOURCES.items():
        try:
            got = fn()
            status[name] = {"ok": True, "count": len(got), "home": home}
            items += got
        except Exception as e:
            status[name] = {"ok": False, "count": 0, "home": home, "error": clean(f"{type(e).__name__}: {e}", 120)}
            print(f"[warn] {name}: {e}", file=sys.stderr)
    # A board that errors this hour keeps its last verified items for up to 3 h (marked stale) instead of vanishing.
    try:
        prev_items = json.load(open(os.path.join(OUT, "feed.json"))).get("items", [])
    except Exception:
        prev_items = []
    lim = (NOW - datetime.timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    for name, st in status.items():
        if st["ok"]:
            continue
        carried = [dict(i, stale=True) for i in prev_items if i.get("source") == name and (i.get("fetched_at") or "") >= lim]
        if carried:
            st["carried_over_from_last_refresh"] = len(carried)
            items += carried
    kept = []
    for i in items:
        if past(i.get("deadline")):
            drop("expired (deadline passed)")
        else:
            kept.append(i)
    items = kept
    # first_seen survives a source being briefly down: persisted in .cache/first_seen.json (30-day memory).
    os.makedirs(CACHE, exist_ok=True)
    fpath = os.path.join(CACHE, "first_seen.json")
    seen = {}
    try:
        seen = json.load(open(fpath))
    except Exception:
        try:
            seen = {i["id"]: i.get("first_seen") for i in json.load(open(os.path.join(OUT, "feed.json"))).get("items", []) if i.get("first_seen")}
        except Exception:
            pass
    for i in items:
        i["first_seen"] = seen.get(i["id"]) or NOW_S
        seen[i["id"]] = i["first_seen"]
    cutoff = (NOW - datetime.timedelta(days=30)).isoformat().replace("+00:00", "Z")
    json.dump({k: v for k, v in seen.items() if v >= cutoff or any(i["id"] == k for i in items)}, open(fpath, "w"))
    items.sort(key=lambda i: (-to_usd(i), i["source"]))
    if not any(s["ok"] for s in status.values()):
        print("all sources failed; not overwriting feed", file=sys.stderr)
        sys.exit(1)
    write_all(items, status)
    print(json.dumps({k: v["count"] if v["ok"] else "ERR" for k, v in status.items()}), len(items))


if __name__ == "__main__":
    main()
