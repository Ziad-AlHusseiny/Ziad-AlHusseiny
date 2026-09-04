"""Render self-hosted GitHub stats cards as animated SVG.

Queries the GitHub GraphQL API for the owner's public stats and writes
assets/stats-dark.svg and assets/stats-light.svg. Runs in CI so the
profile never depends on a third-party badge service.
"""
import json
import os
import urllib.request

API = "https://api.github.com/graphql"
TOKEN = os.environ["GH_TOKEN"]
USER = os.environ["GH_USER"]

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false,
                 orderBy: {field: STARGAZERS, direction: DESC}) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def fetch():
    body = json.dumps({"query": QUERY, "variables": {"login": USER}}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]["user"]


def summarise(user):
    repos = user["repositories"]["nodes"]
    contrib = user["contributionsCollection"]
    langs = {}
    for repo in repos:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            entry = langs.setdefault(name, {"size": 0, "color": edge["node"]["color"]})
            entry["size"] += edge["size"]
    total = sum(v["size"] for v in langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: kv[1]["size"], reverse=True)[:5]
    return {
        "stars": sum(r["stargazerCount"] for r in repos),
        "repos": user["repositories"]["totalCount"],
        "followers": user["followers"]["totalCount"],
        "commits": contrib["totalCommitContributions"],
        "prs": contrib["totalPullRequestContributions"],
        "issues": contrib["totalIssueContributions"],
        "langs": [
            (name, GRAY_RAMP[i % len(GRAY_RAMP)], round(v["size"] / total * 100, 1))
            for i, (name, v) in enumerate(top)
        ],
    }


THEMES = {
    "mono": {
        "text": "#ffffff", "muted": "#8a8a8a", "accent": "#c8c8c8",
        "panel": "#0b0b0b", "line": "#242424",
    },
}

# Language bars are drawn on a grayscale ramp so the card stays monochrome.
GRAY_RAMP = ["#ffffff", "#c4c4c4", "#909090", "#5f5f5f", "#3b3b3b"]


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render(stats, theme_name):
    t = THEMES[theme_name]

    candidates = [
        ("Public repos", stats["repos"]),
        ("Commits this year", stats["commits"]),
        ("Pull requests", stats["prs"]),
        ("Stars earned", stats["stars"]),
        ("Followers", stats["followers"]),
        ("Issues opened", stats["issues"]),
    ]
    # Drop empty metrics so the card never shows a row of zeros.
    tiles = [c for c in candidates if c[1]][:6]
    if len(tiles) < 3:
        tiles = candidates[:3]

    rows = (len(tiles) + 2) // 3
    W = 840
    last_label_y = 82 + (rows - 1) * 74 + 20
    divider_y = last_label_y + 30
    by = divider_y + 26
    H = by + 40

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" role="img" aria-label="GitHub statistics">',
        "<title>GitHub statistics</title>",
        "<defs><style>",
        ".lbl{font:500 13px 'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif;fill:%s}" % t["muted"],
        ".val{font:700 30px 'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif;fill:%s}" % t["text"],
        ".hd{font:600 14px 'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif;fill:%s;letter-spacing:2px}" % t["accent"],
        ".lg{font:500 13px 'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif;fill:%s}" % t["text"],
        ".f{opacity:0;animation:f .7s ease-out forwards}",
        "@keyframes f{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}",
        ".bar{transform:scaleX(0);transform-origin:left center;animation:g 1.1s cubic-bezier(.2,.8,.3,1) forwards}",
        "@keyframes g{to{transform:scaleX(1)}}",
        "</style></defs>",
        f'<rect width="{W}" height="{H}" rx="14" fill="{t["panel"]}"/>',
        f'<text class="hd" x="30" y="38">GITHUB STATS</text>',
    ]

    # stat tiles, 3 columns x 2 rows
    for i, (label, value) in enumerate(tiles):
        col, row = i % 3, i // 3
        x = 30 + col * 268
        y = 82 + row * 74
        delay = 0.1 + i * 0.08
        parts.append(f'<g class="f" style="animation-delay:{delay:.2f}s">')
        parts.append(f'<text class="val" x="{x}" y="{y}">{value}</text>')
        parts.append(f'<text class="lbl" x="{x}" y="{y + 20}">{esc(label)}</text>')
        parts.append("</g>")

    # language bar
    parts.append(f'<line x1="30" y1="{divider_y}" x2="{W - 30}" y2="{divider_y}" stroke="{t["line"]}" stroke-width="1"/>')
    bar_w = W - 60
    cursor = 30.0
    total_pct = sum(p for _, _, p in stats["langs"]) or 1
    for i, (name, color, pct) in enumerate(stats["langs"]):
        seg = bar_w * (pct / total_pct)
        parts.append(
            f'<rect class="bar" x="{cursor:.1f}" y="{by - 12}" width="{seg:.1f}" height="8" '
            f'rx="4" fill="{color}" style="animation-delay:{0.5 + i * 0.1:.2f}s"/>'
        )
        cursor += seg + 2

    lx = 30
    for i, (name, color, pct) in enumerate(stats["langs"]):
        parts.append(f'<g class="f" style="animation-delay:{0.8 + i * 0.07:.2f}s">')
        parts.append(f'<circle cx="{lx + 5}" cy="{by + 14}" r="5" fill="{color}"/>')
        parts.append(f'<text class="lg" x="{lx + 16}" y="{by + 19}">{esc(name)} {pct}%</text>')
        parts.append("</g>")
        lx += 22 + len(name) * 7.6 + 42

    parts.append("</svg>")
    return "\n".join(parts)


def main():
    stats = summarise(fetch())
    os.makedirs("assets", exist_ok=True)
    path = "assets/stats.svg"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(stats, "mono"))
    print(f"wrote {path}")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
