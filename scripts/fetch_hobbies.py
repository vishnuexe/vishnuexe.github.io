#!/usr/bin/env python3
"""Refresh data/games.json and data/films.json for the casual page.

- Films  : Letterboxd RSS (reliable, no browser needed) -> 5 most recent.
- Games  : Backloggd via a real headless browser (Playwright) to get past
           Cloudflare -> up to 5 "top" (favourite) games + currently "playing".

Design rule: never overwrite a file with empty results. If a source fails
(Cloudflare block, layout change, network error), we keep the last-good data.
"""
import datetime
import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

BACKLOGGD_USER = "v_shnuexe"
LETTERBOXD_USER = "vishnuexe"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TODAY = datetime.date.today().isoformat()


def load(name):
    p = DATA / name
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save(name, data):
    (DATA / name).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {name}")


# ---------------------------------------------------------------- films (RSS)
def fetch_films(limit=5):
    req = urllib.request.Request(
        f"https://letterboxd.com/{LETTERBOXD_USER}/rss/",
        headers={"User-Agent": UA})
    xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    items = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def tag(name):
            m = re.search(rf"<(?:letterboxd:)?{name}>(.*?)</(?:letterboxd:)?{name}>",
                          block, re.S)
            return (m.group(1).strip() if m else "")
        title = tag("filmTitle")
        if not title:
            continue
        year = tag("filmYear")
        rating = tag("memberRating")
        link = tag("link").replace("<![CDATA[", "").replace("]]>", "").strip()
        img = re.search(r'<img src="([^"]+)"', block)
        poster = (img.group(1) if img else "").replace("&amp;", "&")
        items.append({
            "title": title,
            "year": year,
            "rating": float(rating) if rating else None,
            "poster": poster,
            "url": link,
        })
        if len(items) >= limit:
            break
    return items


# ----------------------------------------------------------- games (Backloggd)
def _covers_on(page, limit):
    """Return [{title, cover, url}] for every IGDB game cover currently in the DOM."""
    # nudge lazy-loaded images
    for _ in range(6):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(700)
    rows = page.eval_on_selector_all(
        "img",
        """els => els
            .filter(e => ((e.currentSrc || e.src || '').includes('igdb')))
            .map(e => ({
                title: (e.alt || '').trim(),
                cover: e.currentSrc || e.src,
                url: (e.closest('a') ? e.closest('a').href : '')
            }))""")
    seen, out = set(), []
    for r in rows:
        key = r.get("url") or r.get("cover")
        if not r.get("cover") or key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def fetch_games(top_limit=5, playing_limit=6):
    from playwright.sync_api import sync_playwright
    top, playing = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 1600})
        page = ctx.new_page()

        # favourites / top games live on the profile page
        page.goto(f"https://backloggd.com/u/{BACKLOGGD_USER}/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3500)
        top = _covers_on(page, top_limit)

        # currently playing
        try:
            page.goto(f"https://backloggd.com/u/{BACKLOGGD_USER}/games/type:playing/",
                      wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3500)
            playing = _covers_on(page, playing_limit)
        except Exception as e:
            print(f"playing fetch failed: {e}", file=sys.stderr)

        browser.close()
    return top, playing


# ------------------------------------------------------------------------ main
def main():
    # films
    try:
        films = fetch_films()
    except Exception as e:
        films = []
        print(f"films fetch failed: {e}", file=sys.stderr)
    if films:
        save("films.json", {"updated": TODAY, "source": "letterboxd",
                            "user": LETTERBOXD_USER, "items": films})
    else:
        print("keeping existing films.json (no new data)")

    # games
    try:
        top, playing = fetch_games()
    except Exception as e:
        top, playing = [], []
        print(f"games fetch failed: {e}", file=sys.stderr)
    if top or playing:
        prev = load("games.json")
        save("games.json", {
            "updated": TODAY,
            "source": "backloggd",
            "user": BACKLOGGD_USER,
            "top": top or prev.get("top", []),
            "playing": playing if playing or not prev else prev.get("playing", []),
        })
    else:
        print("keeping existing games.json (no new data)")


if __name__ == "__main__":
    main()
