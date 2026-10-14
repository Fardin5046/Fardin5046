#!/usr/bin/env python3
"""Make a 2026-only square-eating contribution snake (standard-library only).

The calendar is fetched from GitHub's GraphQL contributionsCollection using a
FIXED calendar-year date range, not the rolling 365-day profile view.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import html
import json
import math
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

GRAPHQL_URL = "https://api.github.com/graphql"
QUERY = """
query ContributionYear($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks {
          contributionDays { date contributionCount }
        }
      }
    }
  }
}
"""

COLORS = {
    "dark": {
        "background": "#0D1117",
        "text": "#E6EDF3",
        "muted": "#8B949E",
        "empty": "#161B22",
        "dots": ["#161B22", "#0E4429", "#006D32", "#26A641", "#39D353"],
        "stroke": "#263444",
        "snake": ["#2DD4BF", "#35D8BC", "#4BE0C6", "#75E3D3", "#A7F3D0", "#D5FAEE"],
    },
    "light": {
        "background": "#FFFFFF",
        "text": "#24292F",
        "muted": "#57606A",
        "empty": "#EBEDF0",
        "dots": ["#EBEDF0", "#9BE9A8", "#40C463", "#30A14E", "#216E39"],
        "stroke": "#D0D7DE",
        "snake": ["#0F766E", "#15847A", "#19A08A", "#2CAD96", "#6AC9B8", "#A1E3D3"],
    },
}


def fetch_calendar(username: str, year: int, token: str) -> dict[str, int]:
    payload = json.dumps({
        "query": QUERY,
        "variables": {
            "login": username,
            "from": f"{year}-01-01T00:00:00Z",
            "to": f"{year}-12-31T23:59:59Z",
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "fardin-calendar-year-snake/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as result:
            data = json.load(result)
    except (urllib.error.URLError, ValueError) as exc:
        raise RuntimeError(f"Unable to query GitHub's contributions calendar: {exc}") from exc
    if data.get("errors"):
        raise RuntimeError("GitHub GraphQL returned errors: " + json.dumps(data["errors"]))
    user = (data.get("data") or {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user {username!r} could not be found")
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    result: dict[str, int] = {}
    for week in weeks:
        for day in week["contributionDays"]:
            if str(day["date"]).startswith(f"{year}-"):
                result[day["date"]] = max(0, int(day["contributionCount"]))
    return result


def contribution_level(count: int) -> int:
    # Visual buckets, not GitHub's official percentile coloring.
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count <= 3:
        return 2
    if count <= 7:
        return 3
    return 4


def make_svg(username: str, year: int, counts: dict[str, int], mode: str) -> str:
    palette = COLORS[mode]
    first = dt.date(year, 1, 1)
    last = dt.date(year, 12, 31)
    # Sunday-start weeks, just like GitHub's contribution grid.
    start_sunday = first - dt.timedelta(days=(first.weekday() + 1) % 7)
    weeks = ((last - start_sunday).days // 7) + 1
    step, square = 16, 12
    left, top = 66, 82
    width = left + weeks * step + 25
    height = top + 7 * step + 38
    username_esc = html.escape(username, quote=True)

    result: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{username_esc} GitHub contribution snake, year {year} only">',
        f'<title>{username_esc} — {year} Contribution Snake</title>',
        '<desc>Animated snake eats colored contribution squares in a fixed calendar year. Eaten squares return when the animation loops. Some contributions may be synthetic.</desc>',
        f'<rect width="100%" height="100%" rx="11" fill="{palette["background"]}" stroke="{palette["stroke"]}"/>',
        f'<text x="{left}" y="26" font-family="monospace" font-size="16" font-weight="bold" fill="{palette["text"]}">&gt; github contributions --year {year}</text>',
        f'<text x="{left}" y="45" font-family="monospace" font-size="11" fill="{palette["muted"]}">{username_esc} / calendar-year view</text>',
    ]
    for day_index, name in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
        y = top + day_index * step + 10
        result.append(f'<text x="{left-12}" y="{y}" text-anchor="end" font-family="monospace" font-size="10" fill="{palette["muted"]}">{name}</text>')

    for month in range(1, 13):
        d = dt.date(year, month, 1)
        col = (d - start_sunday).days // 7
        x = left + col * step
        result.append(f'<text x="{x}" y="66" font-family="monospace" font-size="10" fill="{palette["muted"]}">{calendar.month_abbr[month]}</text>')

    # All 365 days remain visible in the fixed-year calendar, including future
    # empty days. The snake only travels through days up to today (UTC), so it
    # spends its time eating visible contributions, not future placeholders.
    all_cells: list[tuple[int, int, dt.date]] = []
    for day_offset in range((last - first).days + 1):
        d = first + dt.timedelta(days=day_offset)
        col = (d - start_sunday).days // 7
        row = (d.weekday() + 1) % 7
        all_cells.append((col, row, d))

    today_utc = dt.datetime.now(dt.timezone.utc).date()
    active_cells = [cell for cell in all_cells if cell[2] <= today_utc]
    # The year hasn't started yet: produce the fixed calendar and a stationary
    # (non-eating) snake rather than constructing an empty motion path.
    if not active_cells:
        active_cells = all_cells[:1]

    # Snake crawls through each row, reversing direction on alternating rows.
    # Connecting row endpoints makes the route continuous (no teleport between
    # weeks), and the same route controls both the head and square fading.
    sorted_cells = sorted(active_cells, key=lambda cell: (cell[1], cell[0] if cell[1] % 2 == 0 else -cell[0]))
    route = [(left + c * step + square / 2, top + r * step + square / 2) for c, r, _ in sorted_cells]
    traversed = [0.0]
    for previous, current in zip(route, route[1:]):
        traversed.append(traversed[-1] + math.hypot(current[0] - previous[0], current[1] - previous[1]))
    total_distance = max(traversed[-1], 1.0)
    arrivals = {cell[2].isoformat(): length / total_distance for cell, length in zip(sorted_cells, traversed)}
    duration = 24.0

    # The green overlays disappear and reveal the empty square when eaten.
    # They reappear at the start of the next 24-second cycle. No GitHub data or contributions are changed.
    for col, row, day in all_cells:
        x, y = left + col * step, top + row * step
        count = counts.get(day.isoformat(), 0)
        # Draw an always-visible dark/gray empty cell BELOW the green square.
        # The animated colored overlay disappears when eaten; the empty cell
        # remains clearly visible. This makes the effect readable on GitHub.
        result.append(
            f'<rect x="{x}" y="{y}" width="{square}" height="{square}" rx="2" '
            f'fill="{palette["empty"]}"/>'
        )
        if count > 0:
            color = palette["dots"][contribution_level(count)]
            result.append(f'<rect x="{x}" y="{y}" width="{square}" height="{square}" rx="2" fill="{color}">')
            result.append(f'<title>{day.isoformat()}: {count} contribution(s)</title>')
            if day.isoformat() in arrivals:
                progress = arrivals[day.isoformat()]
                fade_start = max(0.001, min(0.994, progress - 0.001))
                fade_end = min(0.999, fade_start + 0.005)
                result.append(
                    f'<animate attributeName="opacity" values="1;1;0;0" '
                    f'keyTimes="0;{fade_start:.6f};{fade_end:.6f};1" '
                    f'dur="{duration:g}s" repeatCount="indefinite" calcMode="linear"/>'
                )
            result.append('</rect>')

    # The motion path is relative to the first cell because each segment is
    # positioned there before animateMotion begins.
    path = "M 0,0 " + " ".join(f"L {x - route[0][0]:g},{y - route[0][1]:g}" for x, y in route[1:])
    result.append('<g aria-hidden="true">')
    for segment in range(5, -1, -1):
        # Head (segment 0) moves first, with the five tail segments following.
        result.append(
            f'<rect x="{route[0][0]-5:g}" y="{route[0][1]-5:g}" width="10" height="10" '
            f'rx="3" fill="{palette["snake"][segment]}" opacity="{1-segment*0.11:.2f}">'
            f'<animateMotion dur="{duration:g}s" begin="{0.17*segment:.2f}s" '
            f'repeatCount="indefinite" calcMode="linear" path="{path}"/>'
            '</rect>'
        )
    result.append('</g>')
    result.append(f'<text x="{left}" y="{height-15}" font-family="monospace" font-size="10" fill="{palette["muted"]}">Jan 1 – Dec 31, {year}  |  generated from GitHub calendar</text>')
    result.append('</svg>')
    return "\n".join(result) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description="Generate fixed-year GitHub contribution snake SVGs")
    p.add_argument("--year", type=int, default=int(os.environ.get("SNAKE_YEAR", "2026")))
    p.add_argument("--username", default=os.environ.get("GITHUB_USERNAME", "Fardin5046"))
    p.add_argument("--out-dir", type=Path, default=Path("dist"))
    p.add_argument("--fixture", type=Path, help="Local test data: JSON object mapping YYYY-MM-DD to count")
    a = p.parse_args()
    if not 2000 <= a.year <= 2100:
        p.error("Year must be between 2000 and 2100")
    if a.fixture:
        counts = json.loads(a.fixture.read_text(encoding="utf-8"))
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            p.error("GH_TOKEN or GITHUB_TOKEN is required (unless using --fixture)")
        counts = fetch_calendar(a.username, a.year, token)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    files = [("github-snake.svg", "light"), ("github-snake-dark.svg", "dark")]
    for name, mode in files:
        path = a.out_dir / name
        path.write_text(make_svg(a.username, a.year, counts, mode), encoding="utf-8")
        print(f"Generated {path} ({a.year} contributions only)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, KeyError, TypeError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)
