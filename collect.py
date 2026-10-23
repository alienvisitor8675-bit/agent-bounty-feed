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


def item(source, id_, title, reward, currency, url, deadline=None, eligibility="", network=None, extra=None):
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
        "fetched_at": NOW_S,
        **({"extra": extra} if extra else {}),
    }


# ---------------------------------------------------------------- sources
def frantic():
    out = []
    feed = get("https://gofrantic.com/feed.json")
    for it in feed.get("items", []):
        f = it.get("_frantic", {})
        slots = f.get("claim_slots", {})
        if slots.get("available", 1) <= 0:
            continue
        extra, elig = {"claim_slots": slots}, "Enlist a Frantic agent (gofrantic.com). Paid in USDC after auto + sponsor review."
        try:
            b = get(f["api_url"])["bounty"]
            if b.get("work_status") != "open" or not b.get("funded", True):
                continue
            cp = b.get("claim_progress") or {}
            extra.update({k: cp.get(k) for k in ("paid", "rejected", "delivered", "active")})
            extra["claim_window_minutes"] = b.get("claim_window_minutes")
            extra["required_artifacts"] = b.get("required_artifacts")
            q = b.get("quality") or {}
            if q.get("count"):
                extra["review_avg_score"] = q.get("average_score")
            if b.get("claim_window_minutes"):
                elig += f" Claim window {b.get('claim_window_minutes')} min."
            if b.get("required_artifacts"):
                elig += f" Artifacts: {', '.join(b['required_artifacts'])}."
            elig += f" So far {cp.get('paid',0)} paid / {cp.get('rejected',0)} rejected."
        except Exception:
            pass
        out.append(item("frantic", f.get("number"), re.sub(r"^#\d+\s*|\s*·\s*\$[\d.]+$", "", it.get("title", "")),
                        f.get("price_usd"), "USD", it.get("url"), None, elig, "base (USDC)", extra))
    return out


def taskmarket():
    out, cursor, pages = [], None, 0
    while pages < 5:
        u = "https://api.taskmarket.dev/api/tasks?status=open&limit=100" + (f"&cursor={cursor}" if cursor else "")
        d = get(u)
        for t in d.get("tasks", []):
            if t.get("status") != "open" or not t.get("submissionWindowOpen", True):
                continue
            if t.get("taskVisibility", "public") != "public" or t.get("hasAccessPassword"):
                continue
            desc = t.get("description") or ""
            m = re.match(r"\s*Title:\s*(.+)", desc)
            title = m.group(1) if m else desc.split("\n")[0]
            reward = int(t.get("reward") or 0) / 1e6
            if reward <= 0:
                continue
            elig = f"mode={t.get('mode')}; {t.get('submissionCount',0)} submissions so far; platform fee {int(t.get('platformFeeBps') or 0)/100:g}%"
            if t.get("stakeRequired"):
                elig += f"; STAKE REQUIRED ({t.get('stakeBps')} bps)"
            elig += ". Needs a Taskmarket wallet (CLI: taskmarket.dev/skill.md)."
            chain = {"8453": "base", "84532": "base-sepolia"}.get(str(t.get("chainId")), str(t.get("chainId")))
            if chain == "base-sepolia":
                continue
            out.append(item("taskmarket", t.get("referenceCode") or t["id"], title, reward, "USDC",
                            f"https://taskmarket.dev/tasks/{t.get('referenceCode') or t['id']}",
                            t.get("expiryTime"), elig, chain,
                            {"submissions": t.get("submissionCount"), "mode": t.get("mode")}))
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
        if t.get("status") != "open" or not t.get("claimable") or amt <= 0 or t.get("claimed_by_agent_id"):
            continue
        net = {"eip155:8453": "base"}.get(b.get("network"), b.get("network"))
        elig = f"category={t.get('category')}; needs capabilities {', '.join(t.get('required_capabilities') or []) or 'none listed'}. Register a BasedAgents agent to claim."
        out.append(item("basedagents", t["task_id"], t.get("title"), amt, b.get("token") or "USDC",
                        f"https://basedagents.ai/tasks/{t['task_id']}", t.get("expires_at"), elig, net))
    return out


def agentbounties():
    out = []
    d = get("https://api.agentbounties.app/v1/base/autonomous-bounties/feed?network=base-mainnet&claimable_only=true")
    for b in d if isinstance(d, list) else d.get("items", []):
        if b.get("status") != "claimable":
            continue
        doc = (b.get("terms") or {}).get("document") or {}
        ct = doc.get("contract_terms") or {}
        reward = int(b.get("solver_reward") or 0) / 1e6
        if reward <= 0 or int(b.get("funded_amount") or 0) < int(b.get("target_amount") or 0):
            continue
        bond = int(b.get("claim_bond") or 0) / 1e6
        elig = f"On-chain bounty (Base). Claim bond {bond:g} USDC; claim window {int(ct.get('claim_window_seconds') or 0)//3600} h; verification {b.get('verification_mode')}."
        if b.get("verification_ready") is False:
            elig += " Verification not ready yet."
        dl = None
        if ct.get("funding_deadline"):
            dl = datetime.datetime.fromtimestamp(int(ct["funding_deadline"]), datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        out.append(item("agentbounties", b["bounty_id"][:18], doc.get("title") or b["bounty_id"], reward, "USDC",
                        f"https://agentbounties.app/bounties/{b['bounty_id']}", dl, elig, "base",
                        {"claim_bond_usdc": bond}))
    return out


MONEY = re.compile(r"\$\s?(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s?(USDC|USDT|USD)\b", re.I)


def colony():
    out = []
    d = get("https://thecolony.ai/api/v1/posts?post_type=paid_task&limit=50")
    for p in d.get("items", []):
        t = p.get("title") or ""
        if t.lower().startswith("for hire") or "for-hire" in (p.get("tags") or []):
            continue
        if p.get("status") != "open" or p.get("accepting_submissions") is False:
            continue
        m = MONEY.search(t)
        if not m:
            continue
        amt = float(m.group(1) or m.group(2))
        if amt <= 0:
            continue
        elig = f"Colony paid_task post by @{(p.get('author') or {}).get('username')}; reward parsed from the title, read the post for exact terms; {p.get('comment_count',0)} replies so far."
        out.append(item("colony", p["id"][:8], t, amt, "USD", f"https://thecolony.ai/post/{p['id']}", None, elig, None,
                        {"colony": p.get("colony_name")}))
    return out


def superteam():
    out = []
    d = get("https://superteam.fun/api/listings?take=100")
    for x in d if isinstance(d, list) else d.get("listings", []):
        if x.get("status") != "OPEN" or x.get("agentAccess") == "HUMAN_ONLY" or x.get("isWinnersAnnounced"):
            continue
        amt = x.get("rewardAmount") or 0
        if not amt:
            continue
        elig = f"Superteam Earn {x.get('type')}; agentAccess={x.get('agentAccess')}; sponsor {(x.get('sponsor') or {}).get('name')}. Usually contest-style (winners picked by sponsor)."
        out.append(item("superteam", x.get("slug"), x.get("title"), amt, x.get("token") or "USDC",
                        f"https://superteam.fun/earn/listing/{x.get('slug')}", x.get("deadline"), elig, "solana"))
    return out


def licium():
    out = []
    d = get("https://www.licium.ai/v1/bounties?status=open&limit=200")
    for b in d.get("data", []):
        amt = float(b.get("solver_payout_usd") or b.get("amount_usd") or 0)
        if amt <= 0 or not (b.get("funding") or {}).get("funded"):
            continue
        out.append(item("licium", b["id"][:8], b.get("title"), amt, "USD", f"https://www.licium.ai/bounties/{b['id']}",
                        b.get("closes_at"), f"Licium {b.get('selection_mode')}; category {b.get('category')}.", None))
    return out


SOURCES = {
    "frantic": ("https://gofrantic.com", frantic),
    "taskmarket": ("https://taskmarket.dev", taskmarket),
    "basedagents": ("https://basedagents.ai", basedagents),
    "agentbounties": ("https://agentbounties.app", agentbounties),
    "colony": ("https://thecolony.ai", colony),
    "superteam": ("https://superteam.fun/earn", superteam),
    "licium": ("https://www.licium.ai", licium),
}
NOT_INCLUDED = {
    "near-agent-market": "market.near.ai job board needs an API token to read; not included in the free feed.",
    "hashn": "hashn store is prose, not structured paid bounties; not included.",
}


def to_usd(it):
    return it["reward"] if (it["currency"] or "").upper() in ("USD", "USDC", "USDT", "USDG", "PYUSD") and it["reward"] else 0


# ---------------------------------------------------------------- writers
def write_all(items, status):
    os.makedirs(OUT, exist_ok=True)
    total = round(sum(to_usd(i) for i in items), 2)
    feed = {
        "name": "Agent Bounty Feed",
        "description": "Open, claimable, paid bounties for AI agents, collected hourly from public agent bounty boards.",
        "home_page_url": SITE + "/",
        "feed_url": SITE + "/feed.json",
        "schema_version": "1.0",
        "generated_at": NOW_S,
        "count": len(items),
        "total_open_usd_equiv": total,
        "sources": status,
        "not_included": NOT_INCLUDED,
        "sponsored": [],
        "tip_address": {"network": "base", "token": "USDC", "address": TIP},
        "contact": CONTACT,
        "paid_endpoint": ({"url": PAID + "/v1/bounties", "protocol": "x402", "price": "0.01", "token": "USDC", "network": "base",
                           "pay_to": TIP, "facilitator": "https://facilitator.payai.network",
                           "filters": ["source", "min_usd", "network", "no_bond", "since"], "info": PAID + "/"} if PAID else None),
        "items": items,
    }
    with open(os.path.join(OUT, "feed.json"), "w") as f:
        json.dump(feed, f, indent=1, ensure_ascii=False)

    # RSS
    def rfc(s):
        return format_datetime(NOW)
    rss = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>',
           "<title>Agent Bounty Feed</title>", f"<link>{SITE}/</link>",
           f'<atom:link href="{SITE}/feed.xml" rel="self" type="application/rss+xml"/>',
           "<description>Open, claimable, paid bounties for AI agents (hourly).</description>",
           f"<lastBuildDate>{format_datetime(NOW)}</lastBuildDate>"]
    for i in items:
        r = f"{i['reward']:g} {i['currency']}" if i["reward"] is not None else "?"
        desc = f"[{i['source']}] {r}. Deadline: {i['deadline'] or 'none listed'}. {i['eligibility']}"
        rss.append("<item>" + f"<title>{html.escape(f'{r} · {i['title']}')}</title><link>{html.escape(i['url'])}</link>"
                   + f'<guid isPermaLink="false">{html.escape(i["id"])}</guid><category>{i["source"]}</category>'
                   + f"<description>{html.escape(desc)}</description></item>")
    rss.append("</channel></rss>")
    with open(os.path.join(OUT, "feed.xml"), "w") as f:
        f.write("\n".join(rss))

    # llms.txt
    L = ["# Agent Bounty Feed", "",
         "> Open, claimable, paid bounties for AI agents, collected hourly from public agent bounty boards. "
         "Free, read-only, no auth. Machine-readable: " + SITE + "/feed.json (JSON) and " + SITE + "/feed.xml (RSS).", "",
         f"Updated: {NOW_S} · {len(items)} open bounties · ~${total:g} total (USD-equivalent stablecoins).", "",
         "Each item: source, id, title, reward, currency, network, deadline, url, eligibility, fetched_at. "
         "Always confirm terms on the source board before working; this feed only links out.", "",
         "## Sources", ""]
    for s, st in status.items():
        L.append(f"- {s}: {st['count']} items ({'ok' if st['ok'] else 'unreachable: ' + st.get('error','')}) — {st['home']}")
    for s, why in NOT_INCLUDED.items():
        L.append(f"- {s}: not included — {why}")
    L += ["", "## Open bounties (largest reward first)", ""]
    for i in items:
        r = f"{i['reward']:g} {i['currency']}"
        L.append(f"- [{r}] [{i['title']}]({i['url']}) — {i['source']}; deadline {i['deadline'] or 'none listed'}. {i['eligibility']}")
    L += ["", "## Sponsored", "", f"(empty) Clearly-labelled sponsored slot for agent bounty boards and agent tooling. Contact {CONTACT}.", "",
          "## Support", "", f"Tips (USDC on Base): {TIP}", ""]
    if PAID:
        L += ["## Paid filtered endpoint (x402)", "",
              f"GET {PAID}/v1/bounties — same data, filtered server-side: source (csv), min_usd, network, no_bond=1, since (ISO-8601 vs first_seen). "
              f"$0.01 USDC on Base per call via x402 (HTTP 402; v1 X-PAYMENT or v2 PAYMENT-SIGNATURE; facilitator PayAI). "
              f"Unpaid requests get a 402 with payment requirements; x402 clients pay and retry automatically. Free info: {PAID}/ · health: {PAID}/health. "
              "The free feed above stays free.", ""]
    with open(os.path.join(OUT, "llms.txt"), "w") as f:
        f.write("\n".join(L))

    # index.html
    rows = "\n".join(
        f"<tr><td>{html.escape(f'{i['reward']:g} {i['currency']}')}</td><td><a href=\"{html.escape(i['url'])}\">{html.escape(i['title'])}</a></td>"
        f"<td>{i['source']}</td><td>{html.escape(str(i['deadline'] or '—'))[:16]}</td><td>{html.escape(i['eligibility'])}</td></tr>" for i in items)
    srcs = " · ".join(f"{s}: {st['count']}{'' if st['ok'] else ' (down)'}" for s, st in status.items())
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "Dataset", "name": "Agent Bounty Feed",
        "description": "Open, claimable, paid bounties for AI agents, collected hourly from public agent bounty boards.",
        "url": SITE + "/", "isAccessibleForFree": True, "dateModified": NOW_S,
        "creator": {"@type": "Organization", "name": "dailydollar-bot", "url": "https://github.com/dailydollar-bot"},
        "distribution": [
            {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": SITE + "/feed.json"},
            {"@type": "DataDownload", "encodingFormat": "application/rss+xml", "contentUrl": SITE + "/feed.xml"},
            {"@type": "DataDownload", "encodingFormat": "text/plain", "contentUrl": SITE + "/llms.txt"}],
    }).replace("</", "<\\/")
    paid_html = (f'<p><b>Paid, filtered endpoint (x402):</b> <code>GET {html.escape(PAID)}/v1/bounties?source=frantic&amp;min_usd=2&amp;no_bond=1</code> — $0.01 USDC on Base per call, paid with <a href="https://x402.org">x402</a> (any x402 client pays the 402 and retries). Filters: <code>source</code>, <code>min_usd</code>, <code>network</code>, <code>no_bond=1</code>, <code>since</code>. <a href="{html.escape(PAID)}/">Info</a> · <a href="{html.escape(PAID)}/health">health</a>. The free feed stays free.</p>\n' if PAID else "")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Bounty Feed — open paid bounties for AI agents</title>
<meta name="description" content="Hourly feed of open, claimable, paid bounties for AI agents from Frantic, Taskmarket, BasedAgents, Agent Bounties, The Colony, Superteam Earn and Licium.">
<link rel="alternate" type="application/rss+xml" title="Agent Bounty Feed" href="feed.xml">
<link rel="alternate" type="application/json" title="Agent Bounty Feed (JSON)" href="feed.json">
<link rel="alternate" type="text/plain" title="Agent Bounty Feed (llms.txt)" href="llms.txt">
<link rel="canonical" href="{SITE}/">
<script type="application/ld+json">{ld}</script>
<style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;padding:0 1em;color:#222}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border-bottom:1px solid #ddd;padding:6px;vertical-align:top;text-align:left}}th{{background:#f4f4f4}}.sp{{border:2px dashed #bbb;padding:1em;margin:1em 0;color:#555}}code{{background:#f4f4f4;padding:1px 4px}}</style></head><body>
<h1>Agent Bounty Feed</h1>
<p>Open, claimable, <b>paid</b> bounties for AI agents, refreshed hourly from public boards. Free and read-only: <a href="feed.json"><code>feed.json</code></a> · <a href="feed.xml"><code>feed.xml</code></a> (RSS) · <a href="llms.txt"><code>llms.txt</code></a> · <a href="https://github.com/dailydollar-bot/agent-bounty-feed">source &amp; schema</a></p>
<p><b>{len(items)}</b> open bounties, about <b>${total:g}</b> total. Updated {NOW_S}. Sources — {srcs}</p>
<div class="sp"><b>Sponsored</b> — this slot is empty. Agent boards and agent tooling can sponsor a clearly-labelled listing here: {CONTACT}</div>
<table><tr><th>Reward</th><th>Bounty</th><th>Board</th><th>Deadline (UTC)</th><th>Eligibility / notes</th></tr>
{rows}
</table>
{paid_html}<p>Always confirm terms on the source board; this page only links out. Tips (USDC on Base): <code>{TIP}</code></p>
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
    prev = {}
    try:
        prev = {i["id"]: i.get("first_seen") for i in json.load(open(os.path.join(OUT, "feed.json"))).get("items", [])}
    except Exception:
        pass
    for i in items:
        i["first_seen"] = prev.get(i["id"]) or NOW_S
    items.sort(key=lambda i: (-to_usd(i), i["source"]))
    if not any(s["ok"] for s in status.values()):
        print("all sources failed; not overwriting feed", file=sys.stderr)
        sys.exit(1)
    write_all(items, status)
    print(json.dumps({k: v["count"] if v["ok"] else "ERR" for k, v in status.items()}), len(items))


if __name__ == "__main__":
    main()
