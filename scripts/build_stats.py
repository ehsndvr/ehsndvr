#!/usr/bin/env python3
"""
Render the profile activity card (dark + light SVG) from public GitHub data.

    python scripts/build_stats.py [out_dir]        # default: dist/

Environment:
    PROFILE_USER   GitHub login to render (default: ehsndvr)
    GITHUB_TOKEN   optional; enables the GraphQL source and higher rate limits

Standard library only. The contribution calendar comes from GraphQL when a
token is present and falls back to the public contributions page otherwise.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request
from html import escape

USER = os.environ.get("PROFILE_USER", "ehsndvr")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "dist"
UA = "profile-stats-card/1.0 (+https://github.com/ehsndvr/ehsndvr)"

Day = tuple[str, int]  # (YYYY-MM-DD, contributions)


# --------------------------------------------------------------------------- #
# Data                                                                        #
# --------------------------------------------------------------------------- #
def fetch(url: str, data: bytes | None = None, headers: dict | None = None) -> str:
    h = {"User-Agent": UA, "Accept": "application/json"}
    if TOKEN and "api.github.com" in url:
        h["Authorization"] = f"Bearer {TOKEN}"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def calendar_graphql() -> list[list[Day]]:
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            weeks { contributionDays { date contributionCount } }
          }
        }
      }
    }"""
    body = json.dumps({"query": query, "variables": {"login": USER}}).encode()
    res = json.loads(fetch("https://api.github.com/graphql", body, {"Content-Type": "application/json"}))
    if res.get("errors"):
        raise RuntimeError(res["errors"])
    weeks = res["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [[(d["date"], int(d["contributionCount"])) for d in w["contributionDays"]] for w in weeks]


def calendar_html() -> list[list[Day]]:
    """Parse the public contributions calendar (no auth required)."""
    page = fetch(f"https://github.com/users/{USER}/contributions", headers={"Accept": "text/html"})
    tips = dict(re.findall(r'<tool-tip[^>]*\sfor="([^"]+)"[^>]*>([^<]*)</tool-tip>', page))
    weeks: dict[int, list[Day]] = {}
    for tag in re.findall(r"<td[^>]*\sdata-date=[^>]*>", page):
        date = re.search(r'data-date="(\d{4}-\d{2}-\d{2})"', tag)
        cid = re.search(r'\sid="([^"]+)"', tag)
        if not (date and cid):
            continue
        col = re.search(r"-(\d+)-(\d+)$", cid.group(1))  # ...-<weekday>-<week>
        if not col:
            continue
        m = re.match(r"\s*([\d,]+)\s+contribution", tips.get(cid.group(1), ""))
        count = int(m.group(1).replace(",", "")) if m else 0
        weeks.setdefault(int(col.group(2)), []).append((date.group(1), count))
    if not weeks:
        raise RuntimeError("no calendar cells found in contributions page")
    return [sorted(weeks[k]) for k in sorted(weeks)]


def calendar() -> list[list[Day]]:
    if TOKEN:
        try:
            return calendar_graphql()
        except Exception as e:  # noqa: BLE001 - fall back to the public page
            print(f"graphql failed ({e}); falling back to html", file=sys.stderr)
    return calendar_html()


def profile() -> dict[str, int | None]:
    try:
        u = json.loads(fetch(f"https://api.github.com/users/{USER}"))
        stars, page = 0, 1
        while True:
            repos = json.loads(fetch(f"https://api.github.com/users/{USER}/repos?per_page=100&page={page}"))
            stars += sum(r["stargazers_count"] for r in repos if not r.get("fork"))
            if len(repos) < 100:
                break
            page += 1
        return {"followers": u["followers"], "repos": u["public_repos"], "stars": stars}
    except Exception as e:  # noqa: BLE001 - the card still renders without these
        print(f"profile lookup failed ({e})", file=sys.stderr)
        return {"followers": None, "repos": None, "stars": None}


def streaks(days: list[Day]) -> tuple[int, int]:
    longest = run = 0
    for _, c in days:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)
    current, i = 0, len(days) - 1
    if i >= 0 and days[i][1] == 0:  # an empty *today* does not break the streak
        i -= 1
    while i >= 0 and days[i][1] > 0:
        current += 1
        i -= 1
    return current, longest


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #
THEMES = {
    "dark": dict(bg1="#0B0F19", bg2="#0F1626", border="#FFFFFF", border_op="0.09",
                 text="#F1F5F9", muted="#94A3B8", faint="#64748B",
                 rule="#FFFFFF", rule_op="0.08", grid="#FFFFFF", grid_op="0.035",
                 a1="#7C5CFF", a2="#2DD4BF", zero="#FFFFFF", zero_op="0.08",
                 glow1="0.20", glow2="0.16"),
    "light": dict(bg1="#FFFFFF", bg2="#F3F6FB", border="#D0D7DE", border_op="1",
                  text="#0F172A", muted="#475569", faint="#64748B",
                  rule="#0F172A", rule_op="0.08", grid="#0F172A", grid_op="0.045",
                  a1="#6D4AFF", a2="#0D9488", zero="#0F172A", zero_op="0.08",
                  glow1="0.14", glow2="0.12"),
}
SANS = "Inter,'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,'Helvetica Neue',Arial,sans-serif"
MONO = "'JetBrains Mono','Cascadia Code','SF Mono',Menlo,Consolas,'Liberation Mono',monospace"
W, H = 1200, 300


def fmt(n: int | None) -> str:
    return "—" if n is None else f"{n:,}"


def render(theme: str, weeks: list[list[Day]], stats: dict) -> str:
    t = THEMES[theme]
    totals = [sum(c for _, c in w) for w in weeks]
    peak = max(totals) or 1
    n = len(totals)
    x0, x1 = 64, W - 64
    slot = (x1 - x0) / n
    bar_w = max(4.0, slot * 0.62)
    base, top = 262, 180

    bars, labels, seen = [], [], set()
    for i, (w, total) in enumerate(zip(weeks, totals)):
        x = x0 + i * slot + (slot - bar_w) / 2
        h = 3 if total == 0 else max(4.0, (base - top) * total / peak)
        fill = f'fill="{t["zero"]}" fill-opacity="{t["zero_op"]}"' if total == 0 else 'fill="url(#bar)"'
        bars.append(
            f'<rect class="b" style="animation-delay:{i * 18}ms" x="{x:.1f}" y="{base - h:.1f}" '
            f'width="{bar_w:.1f}" height="{h:.1f}" rx="2" {fill}>'
            f"<title>{escape(w[0][0])} to {escape(w[-1][0])}: {total} contributions</title></rect>"
        )
        month = w[0][0][:7]
        if month not in seen and i > 0 and w[0][0][8:] <= "07":
            seen.add(month)
            labels.append(
                f'<text x="{x0 + i * slot:.1f}" y="{base + 22}" font-family="{MONO}" font-size="11" '
                f'fill="{t["faint"]}">{dt.date.fromisoformat(w[0][0]).strftime("%b")}</text>'
            )

    tiles = [
        (fmt(stats["contributions"]), "contributions · 12 months"),
        (fmt(stats["current"]), "day streak · current"),
        (fmt(stats["longest"]), "day streak · longest"),
        (fmt(stats["stars"]), "stars earned"),
        (fmt(stats["followers"]), "followers"),
    ]
    tw = (x1 - x0) / len(tiles)
    tile_svg = []
    for i, (value, label) in enumerate(tiles):
        x = x0 + i * tw
        if i:
            tile_svg.append(f'<path d="M{x:.1f} 92V150" stroke="{t["rule"]}" stroke-opacity="{t["rule_op"]}"/>')
        pad = 0 if i == 0 else 24
        tile_svg.append(
            f'<text x="{x + pad:.1f}" y="124" font-family="{SANS}" font-size="36" font-weight="700" '
            f'letter-spacing="-1" fill="{t["text"]}">{value}</text>'
            f'<text x="{x + pad:.1f}" y="148" font-family="{SANS}" font-size="13" fill="{t["muted"]}">{label}</text>'
        )

    updated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    contributions, current, longest = stats["contributions"], stats["current"], stats["longest"]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">
  <title id="t">GitHub activity — @{escape(USER)}</title>
  <desc id="d">{contributions} contributions in the last 12 months, {current}-day current streak, {longest}-day longest streak.</desc>
  <defs>
    <clipPath id="card"><rect width="{W}" height="{H}" rx="24"/></clipPath>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{t['bg1']}"/><stop offset="1" stop-color="{t['bg2']}"/></linearGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{t['a2']}"/><stop offset="1" stop-color="{t['a1']}"/></linearGradient>
    <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0V32" fill="none" stroke="{t['grid']}" stroke-opacity="{t['grid_op']}"/></pattern>
    <filter id="blur" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="70"/></filter>
    <style>
      .b{{transform-box:fill-box;transform-origin:bottom;transform:scaleY(0);animation:grow .7s cubic-bezier(.2,.7,.2,1) forwards}}
      @keyframes grow{{to{{transform:scaleY(1)}}}}
      @media (prefers-reduced-motion:reduce){{.b{{animation:none;transform:none}}}}
    </style>
  </defs>
  <g clip-path="url(#card)">
    <rect width="{W}" height="{H}" fill="url(#bg)"/>
    <rect width="{W}" height="{H}" fill="url(#grid)"/>
    <circle cx="80" cy="300" r="200" fill="{t['a1']}" fill-opacity="{t['glow1']}" filter="url(#blur)"/>
    <circle cx="1140" cy="0" r="190" fill="{t['a2']}" fill-opacity="{t['glow2']}" filter="url(#blur)"/>
  </g>
  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="24" fill="none" stroke="{t['border']}" stroke-opacity="{t['border_op']}"/>

  <text x="{x0}" y="56" font-family="{SANS}" font-size="14" font-weight="600" fill="{t['muted']}">Activity</text>
  <text x="{x0 + 74}" y="56" font-family="{SANS}" font-size="14" fill="{t['faint']}">· last 12 months</text>
  <text x="{x1}" y="56" text-anchor="end" font-family="{MONO}" font-size="12" fill="{t['faint']}">updated {updated}</text>

  {"".join(tile_svg)}

  <path d="M{x0} {base + 0.5}H{x1}" stroke="{t['rule']}" stroke-opacity="{t['rule_op']}"/>
  {"".join(bars)}
  {"".join(labels)}
</svg>
"""


def main() -> None:
    weeks = calendar()
    days = [d for w in weeks for d in w]
    current, longest = streaks(days)
    stats = {"contributions": sum(c for _, c in days), "current": current, "longest": longest, **profile()}
    print(json.dumps({"user": USER, "weeks": len(weeks), **stats}))

    os.makedirs(OUT_DIR, exist_ok=True)
    for theme in THEMES:
        path = os.path.join(OUT_DIR, f"stats-{theme}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(render(theme, weeks, stats))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
