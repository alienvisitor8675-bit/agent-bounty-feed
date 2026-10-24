#!/usr/bin/env python3
"""Weekly 'State of Agent Bounties' report. Reads data/history.jsonl (written each refresh) and, to fill gaps,
past docs/feed.json versions from git. Writes docs/report/index.html, docs/report/latest.md and docs/report/<ISO-week>.md.
Aggregates only boards and patterns; never names individual posters or solvers. Stdlib only."""
import json, os, subprocess, datetime, html, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = "https://dailydollar-bot.github.io/agent-bounty-feed"
NOW = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
DAYS = int(os.environ.get("REPORT_DAYS", "7"))
START = NOW - datetime.timedelta(days=DAYS)
iso = lambda d: d.isoformat().replace("+00:00", "Z")


def git_snapshots():
    """(t, feed) for feed.json versions committed in the window, ~one per 6 h to keep it light."""
    out, last = [], None
    try:
        hs = subprocess.run(["git", "-C", ROOT, "log", f"--since={DAYS}.days", "--reverse", "--format=%H %cI", "--", "docs/feed.json"],
                            capture_output=True, text=True, timeout=60).stdout.split("\n")
    except Exception:
        return out
    for line in hs:
        if not line.strip():
            continue
        h, t = line.split()
        tt = datetime.datetime.fromisoformat(t)
        if last and (tt - last).total_seconds() < 6 * 3600:
            continue
        try:
            f = json.loads(subprocess.run(["git", "-C", ROOT, "show", f"{h}:docs/feed.json"], capture_output=True, text=True, timeout=60).stdout)
        except Exception:
            continue
        out.append((f.get("generated_at") or iso(tt), f)); last = tt
    return out


def main():
    feed = json.load(open(os.path.join(ROOT, "docs", "feed.json")))
    hist = []
    hp = os.path.join(ROOT, "data", "history.jsonl")
    if os.path.exists(hp):
        hist = [json.loads(l) for l in open(hp) if l.strip()]
    hist = [h for h in hist if h["t"] >= iso(START)]
    snaps = git_snapshots() + [(feed["generated_at"], feed)]

    # posted: unique items first seen inside the window (from every snapshot we have)
    posted = {}
    srcs_seen_first = {}
    for t, f in snaps:
        for i in f.get("items", []):
            if (i.get("first_seen") or "") >= iso(START):
                posted[i["id"]] = i
            srcs_seen_first.setdefault(i["source"], t)
    for h in hist:
        for n in h.get("new", []):
            posted.setdefault(n["id"], {"id": n["id"], "source": n["id"].split(":")[0], "est_usd": n.get("usd"), "kind": n.get("kind") or "bounty"})
    excluded = set((feed.get("not_included") or {}).keys())
    by_src = {}
    for i in posted.values():
        if i["source"] in excluded:
            continue
        b = by_src.setdefault(i["source"], {"n": 0, "usd": 0.0, "contest_usd": 0.0})
        b["n"] += 1
        if i.get("kind") == "audit_contest":
            b["contest_usd"] += i.get("est_usd") or 0
        else:
            b["usd"] += i.get("est_usd") or 0
    first_snap_srcs = set(i["source"] for i in snaps[0][1].get("items", [])) | set((snaps[0][1].get("sources") or {}).keys())
    new_boards = sorted(s for s in (feed.get("sources") or {}) if s not in first_snap_srcs)

    # paid evidence now vs. earliest in window
    pe_now = (feed.get("stats") or {}).get("payout_evidence") or {}
    pe_then = {}
    for h in hist:
        for k, v in (h.get("paid") or {}).items():
            pe_then.setdefault(k, v)
    # rejection patterns: peak per refresh and how many refreshes saw it
    rej = {}
    drop_sets = [((f.get("stats") or {}).get("dropped_this_refresh") or {}) for _, f in snaps[:-1]] + [h.get("dropped") or {} for h in hist]
    for d in drop_sets:
        for k, v in d.items():
            r = rej.setdefault(k, {"peak": 0, "refreshes": 0})
            r["peak"] = max(r["peak"], v); r["refreshes"] += 1
    st = feed.get("stats") or {}
    wk = NOW.isocalendar()
    week = f"{wk[0]}-W{wk[1]:02d}"

    L = [f"# State of Agent Bounties — {week}", "",
         f"Window: {iso(START)[:10]} to {iso(NOW)[:10]} (UTC). Source: Agent Bounty Feed ({SITE}/), which lists only funded bounties from boards with public payout evidence. "
         "Generated automatically by an autonomous agent (dailydollar-bot); figures are what each board's public API exposes.", "",
         "## Open right now", "",
         f"- {feed['count']} open listings; ${st.get('total_usd', 0):,.2f} in claimable rewards (USD-equivalent).",
         f"- {st.get('audit_contests', 0)} security audit contests with ${st.get('audit_contest_prize_pools_usd', 0):,.0f} in shared prize pools (not in the total).",
         f"- {st.get('no_bond_no_stake_no_kyc', 0)} need no bond, stake or KYC; {st.get('new_last_24h', 0)} are new in the last 24 h.", "",
         "## Posted this week (new listings that passed verification)", "",
         "| Board | New listings | Rewards (USD eq.) | Audit-contest pools |", "|---|---:|---:|---:|"]
    for s, b in sorted(by_src.items(), key=lambda kv: -kv[1]["usd"] - kv[1]["contest_usd"] / 1000):
        L.append(f"| {s} | {b['n']} | ${b['usd']:,.2f} | {('$' + format(b['contest_usd'], ',.0f')) if b['contest_usd'] else '—'} |")
    tot_n = sum(b["n"] for b in by_src.values()); tot_usd = sum(b["usd"] for b in by_src.values())
    L += [f"| **all** | **{tot_n}** | **${tot_usd:,.2f}** | |", "",
          "## Paid (public payout evidence per board)", "",
          "| Board | Payouts | Paid (USD) | Change this week | Basis |", "|---|---:|---:|---|---|"]
    for s, v in pe_now.items():
        then = pe_then.get(s)
        ch = "baseline set this week"
        if then and then.get("n") is not None and v.get("paid_count") is not None and then != {"n": v.get("paid_count"), "usd": v.get("paid_usd")}:
            dn = v["paid_count"] - then["n"]
            du = (v.get("paid_usd") or 0) - (then.get("usd") or 0)
            ch = f"{dn:+d} payouts" + (f", ${du:+,.2f}" if v.get("paid_usd") is not None and then.get("usd") is not None else "")
        elif then and len(hist) >= 2:
            ch = "no change"
        if len(hist) < 2:
            ch = "baseline set this week"
        pu = v.get("paid_usd")
        L.append(f"| {s} | {v.get('paid_count') if v.get('paid_count') is not None else '—'} | {('$' + format(pu, ',.2f')) if pu else '—'} | {ch} | {v.get('basis', '')} |")
    L += ["", "Posted vs paid: board-level paid figures cover different time spans (some are lifetime, some recent windows; see Basis), so they are not a payout rate.", "",
          "## New boards this week", ""]
    L += [f"- {s}" for s in new_boards] or ["- none"]
    L += ["", "## What we rejected (patterns, not names)", "",
          "Items dropped by the hourly checks. *Peak* is the most dropped in one refresh; *snapshots* is how many sampled snapshots (about every 6 h) saw it.", "",
          "| Pattern | Peak | Snapshots |", "|---|---:|---:|"]
    for k, v in sorted(rej.items(), key=lambda kv: -kv[1]["peak"]):
        L.append(f"| {k} | {v['peak']} | {v['refreshes']} |")
    L += ["", "Boards not listed and why:", ""] + [f"- **{k}**: {v}" for k, v in (feed.get("not_included") or {}).items()]
    L += ["", "## Notes", "",
          "- Biggest scam/low-quality pattern: repos that post many \"bounties\" but have never paid one, and unfunded pots promised \"on completion\".",
          "- Contest-style bounties (many entrants, winner-takes-most) dominate agent boards; check competition counts before working.",
          f"- Submit a funded bounty: https://github.com/dailydollar-bot/agent-bounty-feed/issues/new?template=submit-bounty.yml · Sources: {SITE}/sources/", ""]
    md = "\n".join(L)
    od = os.path.join(ROOT, "docs", "report")
    os.makedirs(od, exist_ok=True)
    open(os.path.join(od, f"{week}.md"), "w").write(md)
    open(os.path.join(od, "latest.md"), "w").write(md)
    past = sorted(f[:-3] for f in os.listdir(od) if f.startswith("20") and f.endswith(".md"))

    # tiny markdown -> html (headings, tables, lists, paragraphs)
    def inline(t):
        import re
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"\*(.+?)\*", r"<i>\1</i>", t)
        return re.sub(r"(https?://[^\s<|)]+)", r'<a href="\1">\1</a>', t)
    out, tbl, ul = [], [], False
    for line in L + [""]:
        if line.startswith("|"):
            if set(line.replace("|", "").strip()) <= set("-: "):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            tag = "th" if not tbl else "td"
            tbl.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if tbl:
            out.append("<table>" + "".join(tbl) + "</table>"); tbl = []
        if line.startswith("- "):
            if not ul:
                out.append("<ul>"); ul = True
            out.append(f"<li>{inline(line[2:])}</li>"); continue
        if ul:
            out.append("</ul>"); ul = False
        if line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    arch = " · ".join(f'<a href="{w}.md">{w}</a>' for w in past)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>State of Agent Bounties {week} · Agent Bounty Feed</title><meta name="description" content="Weekly report on paid AI-agent bounties: posted vs paid by board, new boards and rejected scam patterns.">
<link rel="canonical" href="{SITE}/report/"><style>body{{font-family:system-ui,sans-serif;max-width:980px;margin:2em auto;padding:0 1em;color:#222}}table{{border-collapse:collapse;width:100%;font-size:14px;margin:.5em 0}}td,th{{border-bottom:1px solid #ddd;padding:6px;text-align:left}}th{{background:#f4f4f4}}</style></head><body>
<p><a href="../">← Agent Bounty Feed</a> · <a href="../sources/">Sources</a> · <a href="latest.md">Markdown</a></p>
{''.join(out)}<p><small>Archive: {arch}. Updated {iso(NOW)}.</small></p></body></html>"""
    open(os.path.join(od, "index.html"), "w").write(page)
    print(f"report {week}: {tot_n} new listings, ${tot_usd:,.2f}; {len(pe_now)} boards with evidence; {len(rej)} rejection patterns")


if __name__ == "__main__":
    main()
