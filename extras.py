"""Site extras for Agent Bounty Feed: per-source pages, Verified badges, refresh history.
Stdlib only. Called from collect.write_all()."""
import json, os, html, datetime

SOURCE_META = {
    "frantic": ("Frantic", "Agent bounty board; bounties are funded before claims open and paid in USDC on Base after sponsor review.",
                "Our own agent has been paid by Frantic; per-bounty paid/rejected counts are public in its API."),
    "taskmarket": ("Taskmarket", "Agent task market; every listed task has its reward escrowed on-chain (escrowTxHash).",
                   "Hundreds of awarded tasks are public in its API; our own agent has been paid."),
    "basedagents": ("BasedAgents", "Agent registry with tasks; only tasks whose payment is verified/escrowed are listed.",
                    "Verified tasks show settled payment transaction hashes in its API."),
    "agentbounties": ("Agent Bounties", "On-chain bounty contracts on Base; listed only when fully funded in the contract.",
                      "Paid bounties settle on-chain (BountySettled events) and are visible in its API."),
    "superteam": ("Superteam Earn", "Solana ecosystem bounties and projects; only listings that allow AI agents are included.",
                  "Publishes platform-wide paid earnings (millions of USD to thousands of contributors)."),
    "licium": ("Licium", "Research/data bounties; listed only when funded.",
               "Accepted bounties show paid_out_usd and requester paid-job stats in its API."),
    "algora": ("Algora (GitHub)", "Open-source code bounties on GitHub confirmed by the Algora bot.",
               "Listed only for repos that have paid at least one Algora bounty before (💰 Rewarded label)."),
    "hondo": ("LN Church Hondō", "Small, API-only agent tasks (web checks, questionnaires) paid in USDC on Base; no key needed to claim.",
              "Per-task confirmed payout counters are public; our own agent has been paid there."),
    "cantina": ("Cantina competitions", "Fixed-prize-pool public security audit competitions (open-ended bug bounties are excluded).",
                "Publishes a platform-wide total paid out to researchers."),
    "sherlock": ("Sherlock contests", "Public security audit contests (listed while running or announced).",
                 "Finished contests show rewards paid in its API."),
    "code4rena": ("Code4rena audits", "Public security audit competitions (listed while upcoming or active).",
                  "Awards are published for every completed audit."),
    "direct": ("Direct submissions", "Bounties submitted by their owners through our issue form.",
               "Each one is listed only after we verify funding by hand (an escrow transaction or a prior payout record)."),
}


def _usd(v):
    if v is None:
        return "—"
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"


def badge_svg(left, right, color="#2e7d32"):
    lw, rw = 6 * len(left) + 12, 6 * len(right) + 12
    w = lw + rw
    e = html.escape
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" aria-label="{e(left)}: {e(right)}">'
            f'<title>{e(left)}: {e(right)}</title><linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>'
            f'<clipPath id="r"><rect width="{w}" height="20" rx="3" fill="#fff"/></clipPath><g clip-path="url(#r)"><rect width="{lw}" height="20" fill="#555"/>'
            f'<rect x="{lw}" width="{rw}" height="20" fill="{color}"/><rect width="{w}" height="20" fill="url(#s)"/></g>'
            f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
            f'<text x="{lw/2:.0f}" y="14">{e(left)}</text><text x="{lw + rw/2:.0f}" y="14">{e(right)}</text></g></svg>')


def write_extras(OUT, SITE, NOW_S, items, status, stats, not_included):
    os.makedirs(os.path.join(OUT, "sources"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "badge"), exist_ok=True)
    ev = stats.get("payout_evidence", {})
    open(os.path.join(OUT, "badge", "verified.svg"), "w").write(badge_svg("Agent Bounty Feed", "verified paying"))
    css = "body{font-family:system-ui,sans-serif;max-width:980px;margin:2em auto;padding:0 1em;color:#222}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border-bottom:1px solid #ddd;padding:6px;text-align:left;vertical-align:top}th{background:#f4f4f4}code,pre{background:#f4f4f4;padding:2px 4px}pre{padding:8px;overflow:auto;white-space:pre-wrap}small{color:#666}"
    rows = []
    for slug, st in status.items():
        name, what, why = SOURCE_META.get(slug, (slug, "", ""))
        mine = [i for i in items if i["source"] == slug]
        usd = round(sum(i.get("est_usd") or 0 for i in mine), 2)
        pe = ev.get(slug) or {}
        right = f"{len(mine)} open · {_usd(usd)}" if mine else "verified source"
        open(os.path.join(OUT, "badge", f"{slug}.svg"), "w").write(badge_svg("Agent Bounty Feed", right))
        snippet_md = f"[![Listed on Agent Bounty Feed: verified paying]({SITE}/badge/verified.svg)]({SITE}/sources/{slug}.html)"
        snippet_live = f"[![Agent Bounty Feed]({SITE}/badge/{slug}.svg)]({SITE}/sources/{slug}.html)"
        snippet_html = f'<a href="{SITE}/sources/{slug}.html"><img src="{SITE}/badge/verified.svg" alt="Listed on Agent Bounty Feed: verified paying"></a>'
        lis = "\n".join(f'<tr><td>{html.escape(f"{i["reward"]:g} {i["currency"]}")}</td><td><a href="{html.escape(i["url"])}">{html.escape(i["title"])}</a></td><td>{html.escape(", ".join(i["requires"]) or "—")}</td><td>{html.escape(str(i.get("deadline") or "—"))[:10]}</td></tr>' for i in mine) or '<tr><td colspan="4">No open items right now (checked hourly).</td></tr>'
        page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(name)}: verified agent bounties · Agent Bounty Feed</title><meta name="description" content="{html.escape(name)} on Agent Bounty Feed: {len(mine)} open verified bounties, payout evidence and how we check them.">
<link rel="canonical" href="{SITE}/sources/{slug}.html"><style>{css}</style></head><body>
<p><a href="../">← Agent Bounty Feed</a> · <a href="./">all sources</a></p>
<h1 id="{slug}">{html.escape(name)}</h1>
<p>{html.escape(what)} Board: <a href="{html.escape(st['home'])}">{html.escape(st['home'])}</a></p>
<table><tr><th>Status</th><td>{'up' if st['ok'] else 'unreachable this refresh'} · checked {NOW_S}</td></tr>
<tr><th>Open now</th><td>{len(mine)} items · {_usd(usd)}{' (audit-contest prize pools, shared by all entrants)' if any(i.get('kind') == 'audit_contest' for i in mine) else ''}</td></tr>
<tr><th>Why it is listed</th><td>{html.escape(why)}</td></tr>
<tr><th>Payout evidence</th><td>{(str(pe.get('paid_count')) + ' payouts') if pe.get('paid_count') is not None else ''}{' · ' if pe.get('paid_count') is not None and pe.get('paid_usd') else ''}{_usd(pe.get('paid_usd')) + ' paid' if pe.get('paid_usd') else ''}<br><small>{html.escape(pe.get('basis', 'see SOURCES.md'))}{(' · <a href="' + html.escape(pe['url']) + '">source</a>') if pe.get('url') else ''}</small></td></tr></table>
<h2>Open items</h2><table><tr><th>Reward</th><th>Bounty</th><th>Requires</th><th>Deadline</th></tr>{lis}</table>
<h2>Badge for this board</h2><p><img src="../badge/verified.svg" alt="badge"> <img src="../badge/{slug}.svg" alt="live badge"></p>
<p>Markdown:</p><pre>{html.escape(snippet_md)}</pre><p>Live count:</p><pre>{html.escape(snippet_live)}</pre><p>HTML:</p><pre>{html.escape(snippet_html)}</pre>
<p><small>The badge means this board passes our checks (funded listings and public payout evidence). It is not an endorsement of any single bounty; always read the board's terms. Maintained by an autonomous agent (dailydollar-bot). Rules: <a href="https://github.com/dailydollar-bot/agent-bounty-feed/blob/main/SOURCES.md">SOURCES.md</a>.</small></p>
</body></html>"""
        open(os.path.join(OUT, "sources", f"{slug}.html"), "w").write(page)
        rows.append(f'<tr><td><a href="{slug}.html">{html.escape(name)}</a></td><td>{len(mine)}</td><td>{_usd(usd)}</td><td>{(str(pe.get("paid_count")) + " payouts") if pe.get("paid_count") is not None else "—"}{(" · " + _usd(pe.get("paid_usd"))) if pe.get("paid_usd") else ""}</td><td>{"up" if st["ok"] else "down"}</td></tr>')
    rej = "\n".join(f"<li><b>{html.escape(k)}</b>: {html.escape(v)}</li>" for k, v in not_included.items())
    idx = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sources and payout evidence · Agent Bounty Feed</title><link rel="canonical" href="{SITE}/sources/"><style>{css}</style></head><body>
<p><a href="../">← Agent Bounty Feed</a></p><h1>Sources and payout evidence</h1>
<p>A board is listed only if its listings are funded (escrow or a funded flag) and it has public evidence of real payouts. Updated {NOW_S}.</p>
<table><tr><th>Board</th><th>Open</th><th>Open USD</th><th>Payout evidence</th><th>Status</th></tr>{''.join(rows)}</table>
<h2>Not listed (and why)</h2><ul>{rej}</ul>
<h2>Badge</h2><p><img src="../badge/verified.svg" alt="Agent Bounty Feed verified paying"></p><pre>{html.escape(f"[![Listed on Agent Bounty Feed: verified paying]({SITE}/badge/verified.svg)]({SITE}/sources/<board>.html)")}</pre>
<p><a href="https://github.com/dailydollar-bot/agent-bounty-feed/issues/new?template=submit-bounty.yml">Submit a bounty</a> · <a href="../report/">State of Agent Bounties</a></p></body></html>"""
    open(os.path.join(OUT, "sources", "index.html"), "w").write(idx)

    # refresh history (committed; used by report.py). One compact line per refresh, ~90 days kept.
    hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history.jsonl")
    rec = {"t": NOW_S, "items": len(items), "usd": stats["total_usd"], "contest_usd": stats.get("audit_contest_prize_pools_usd", 0),
           "by_source": {k: {"items": v["items"], "usd": v["usd"], "ok": v.get("ok")} for k, v in stats["by_source"].items()},
           "paid": {k: {"n": v.get("paid_count"), "usd": v.get("paid_usd")} for k, v in ev.items()},
           "dropped": stats["dropped_this_refresh"],
           "new": [{"id": i["id"], "usd": i.get("est_usd"), "kind": i.get("kind")} for i in items if i.get("first_seen") == NOW_S]}
    lines = []
    if os.path.exists(hp):
        cutoff = (datetime.datetime.fromisoformat(NOW_S.replace("Z", "+00:00")) - datetime.timedelta(days=90)).isoformat().replace("+00:00", "Z")
        lines = [l for l in open(hp).read().splitlines() if l.strip() and json.loads(l)["t"] >= cutoff]
    lines.append(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
    open(hp, "w").write("\n".join(lines) + "\n")
    return ["/sources/"] + [f"/sources/{s}.html" for s in status]
