#!/usr/bin/env python3
"""
Daily News Briefing — standalone script for GitHub Actions + Server酱 (ServerChan).

Fetches from 4 profiles (综合/财经/科技/AI深度), caps at 10 items each,
formats as Chinese markdown, pushes to WeChat via Server酱.

Usage:
  # Test locally (prints to stdout)
  python news_briefing.py

  # Push to Server酱
  SERVER_CHAN_KEY=your_key_here python news_briefing.py --push

  # Single profile
  python news_briefing.py --profile finance

  # Custom Server酱 API endpoint (for alternative implementations)
  SERVER_CHAN_KEY=xxx SERVER_CHAN_URL=https://others.example.com/send python news_briefing.py --push

Requirements: pip install requests beautifulsoup4 lxml
"""

import io
import json
import os
import re
import sys
import time
import concurrent.futures
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup
import urllib3
from bs4 import XMLParsedAsHTMLWarning
import warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# ── Constants ──────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}

SERVER_CHAN_URL = os.environ.get(
    "SERVER_CHAN_URL",
    "https://sctapi.ftqq.com/{key}.send"
)

# ── Helpers ────────────────────────────────────────────────────────────────


def clean_text(text):
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r'^\s*<!\[CDATA\[|\]\]>\s*$', '', text).strip()
    return text


def filter_keywords(items, keyword_str):
    """Filter items whose title matches any of the comma-separated keywords."""
    if not keyword_str:
        return items
    keywords = [k.strip() for k in keyword_str.split(",") if k.strip()]
    if not keywords:
        return items
    pattern = "|".join(re.escape(k) for k in keywords)
    regex = rf'(?i)({pattern})'
    return [it for it in items if re.search(regex, it.get("title", ""))]


def filter_by_hours(items, hours=24):
    """Keep items published within last N hours; unparseable time kept as-is."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    kept = []
    for item in items:
        t = item.get("time", "")
        try:
            pub = parsedate_to_datetime(str(t))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub >= cutoff:
                kept.append(item)
        except Exception:
            kept.append(item)
    return kept


def fetch_url_text(url, max_chars=1500):
    """Fetch a URL and extract readable text (first max_chars chars)."""
    if not url or not url.startswith("http"):
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = " ".join(c for c in chunks if c)
        return text[:max_chars]
    except Exception:
        return ""


# ── RSS Parser ─────────────────────────────────────────────────────────────


def parse_rss(content, source_name, limit=10):
    """Parse RSS/Atom XML string into a list of item dicts."""
    items = []
    try:
        soup = BeautifulSoup(content, "html.parser")
        for entry in soup.find_all(["item", "entry"]):
            title_tag = entry.find("title")
            if not title_tag:
                continue
            title = clean_text(title_tag.get_text())
            if not title:
                continue

            # Link
            link = ""
            link_tag = entry.find("link")
            if link_tag:
                if link_tag.has_attr("href"):
                    link = link_tag["href"]
                elif link_tag.get_text(strip=True):
                    link = link_tag.get_text(strip=True)
            if not link:
                guid = entry.find("guid")
                if guid and guid.get_text(strip=True).startswith("http"):
                    link = guid.get_text(strip=True)

            # Time
            pub = entry.find(["pubdate", "published", "updated", "dc:date"])
            time_str = clean_text(pub.get_text()) if pub else ""

            # Summary
            desc_tag = entry.find("description") or entry.find("summary")
            summary = ""
            if desc_tag:
                raw = desc_tag.get_text()
                s = BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)
                summary = s[:300] + "..." if len(s) > 300 else s

            items.append({
                "source": source_name,
                "title": title,
                "url": link,
                "time": time_str,
                "summary": summary,
            })
            if len(items) >= limit:
                break
    except Exception as e:
        print(f"  [RSS Parse Error] {source_name}: {e}", file=sys.stderr)
    return items


def fetch_rss(url, source_name, limit=10):
    """Fetch an RSS feed with retries."""
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return parse_rss(r.content, source_name, limit)
        except Exception as e:
            if attempt < 2:
                time.sleep(1 + attempt)
            else:
                print(f"  [RSS Fail] {url}: {e}", file=sys.stderr)
    return []


# ── Source Fetchers ────────────────────────────────────────────────────────


def fetch_hackernews(limit=5, keyword=None):
    """Hacker News via Algolia API (keyword) + front-page scrape fallback."""
    items = []

    # Try Algolia API first
    if keyword:
        try:
            ts = int(time.time() - 24 * 3600)
            kws = [k.strip() for k in keyword.split(",")]
            quoted = [f'"{k}"' if " " in k else k for k in kws]
            q = " OR ".join(quoted)
            url = (
                f"https://hn.algolia.com/api/v1/search_by_date"
                f"?tags=story&numericFilters=created_at_i>{ts}"
                f"&hitsPerPage={limit * 2}&query={urllib.parse.quote(q)}"
            )
            data = requests.get(url, timeout=10).json()
            hits = data.get("hits", [])

            if not hits and kws:
                # Fallback: just first keyword
                url2 = (
                    f"https://hn.algolia.com/api/v1/search_by_date"
                    f"?tags=story&numericFilters=created_at_i>{ts}"
                    f"&hitsPerPage={limit * 2}"
                    f"&query={urllib.parse.quote(kws[0])}"
                )
                hits = requests.get(url2, timeout=10).json().get("hits", [])

            for hit in hits:
                items.append({
                    "source": "Hacker News",
                    "title": hit.get("title", ""),
                    "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}",
                    "heat": f"{hit.get('points', 0)} points",
                    "time": "Today",
                })
            if items:
                return items[:limit]
        except Exception as e:
            print(f"  [HN Algolia] {e}", file=sys.stderr)

    # Front-page scrape fallback
    try:
        r = requests.get("https://news.ycombinator.com/news", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select(".athing"):
            title_line = row.select_one(".titleline a")
            if not title_line:
                continue
            title = title_line.get_text()
            link = title_line.get("href")
            if link and link.startswith("item?id="):
                link = f"https://news.ycombinator.com/{link}"
            items.append({
                "source": "Hacker News",
                "title": title,
                "url": link,
                "heat": "",
                "time": "Today",
            })
        if keyword:
            items = filter_keywords(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [HN Scrape] {e}", file=sys.stderr)
    return items[:limit]


def fetch_github_trending(limit=5, keyword=None):
    """GitHub Trending repos."""
    items = []
    try:
        r = requests.get("https://github.com/trending", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for article in soup.select("article.Box-row"):
            h2 = article.select_one("h2 a")
            if not h2:
                continue
            title = h2.get_text(strip=True).replace("\n", "").replace(" ", "")
            link = "https://github.com" + h2["href"]
            desc = article.select_one("p")
            desc_text = desc.get_text(strip=True) if desc else ""
            stars = article.select_one('a[href$="/stargazers"]')
            star_str = stars.get_text(strip=True) if stars else ""
            items.append({
                "source": "GitHub Trending",
                "title": f"{title} — {desc_text}" if desc_text else title,
                "url": link,
                "heat": f"{star_str} stars",
                "time": "Today",
            })
        if keyword:
            items = filter_keywords(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [GitHub] {e}", file=sys.stderr)
    return items[:limit]


def fetch_36kr(limit=5, keyword=None):
    """36氪 快讯."""
    items = []
    try:
        r = requests.get("https://36kr.com/newsflashes", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".newsflash-item"):
            title_el = item.select_one(".item-title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://36kr.com" + href
            time_el = item.select_one(".time")
            time_str = time_el.get_text(strip=True) if time_el else ""
            items.append({
                "source": "36氪",
                "title": title,
                "url": href,
                "time": time_str,
                "heat": "",
            })
        if keyword:
            items = filter_keywords(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [36Kr] {e}", file=sys.stderr)
    return items[:limit]


def fetch_tencent(limit=5, keyword=None):
    """腾讯新闻科技频道."""
    items = []
    try:
        url = "https://i.news.qq.com/web_backend/v2/getTagInfo?tagId=aEWqxLtdgmQ%3D"
        r = requests.get(url, headers={"Referer": "https://news.qq.com/"}, timeout=10)
        data = r.json()
        for news in data.get("data", {}).get("tabs", [{}])[0].get("articleList", []):
            items.append({
                "source": "腾讯新闻",
                "title": news.get("title", ""),
                "url": news.get("url") or news.get("link_info", {}).get("url", ""),
                "time": news.get("pub_time", "") or news.get("publish_time", ""),
                "heat": "",
            })
        if keyword:
            items = filter_keywords(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [Tencent] {e}", file=sys.stderr)
    return items[:limit]


def fetch_wallstreetcn(limit=5, keyword=None):
    """华尔街见闻 全球快讯."""
    items = []
    try:
        url = "https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&accept=article&limit=30"
        r = requests.get(url, timeout=10)
        data = r.json()
        for item in data.get("data", {}).get("items", []):
            res = item.get("resource")
            if res and (res.get("title") or res.get("content_short")):
                ts = res.get("display_time", 0)
                time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
                items.append({
                    "source": "华尔街见闻",
                    "title": res.get("title") or res.get("content_short"),
                    "url": res.get("uri", ""),
                    "time": time_str,
                    "heat": "",
                })
        if keyword:
            items = filter_keywords(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [WallStreetCN] {e}", file=sys.stderr)
    return items[:limit]


def fetch_producthunt(limit=5, keyword=None):
    """Product Hunt via RSS."""
    items = fetch_rss("https://www.producthunt.com/feed", "Product Hunt", limit * 2)
    for it in items:
        it["heat"] = "Trending"
    if keyword:
        items = filter_keywords(items, keyword)
    return items[:limit]


def fetch_v2ex(limit=5, keyword=None):
    """V2EX 热门话题."""
    items = []
    try:
        data = requests.get("https://www.v2ex.com/api/topics/hot.json", headers=HEADERS, timeout=10).json()
        for t in data:
            items.append({
                "source": "V2EX",
                "title": t.get("title", ""),
                "url": t.get("url", ""),
                "heat": f"{t.get('replies', 0)} 回复",
                "time": "Hot",
            })
        if keyword:
            items = filter_keywords(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [V2EX] {e}", file=sys.stderr)
    return items[:limit]


def fetch_weibo(limit=5, keyword=None):
    """微博热搜."""
    items = []
    try:
        url = "https://weibo.com/ajax/side/hotSearch"
        r = requests.get(url, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://weibo.com/",
        }, timeout=10)
        raw = r.json()
        for item in raw.get("data", {}).get("realtime", []):
            title = item.get("note", "") or item.get("word", "")
            if not title:
                continue
            heat = item.get("num", 0)
            items.append({
                "source": "微博热搜",
                "title": title,
                "url": f"https://s.weibo.com/weibo?q={urllib.parse.quote(title)}&Refer=top",
                "heat": str(heat),
                "time": "Real-time",
            })
        if keyword:
            items = filter_keywords(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [Weibo] {e}", file=sys.stderr)
    return items[:limit]


# ── RSS-based Aggregate Sources ────────────────────────────────────────────

AI_NEWSLETTER_FEEDS = [
    ("Interconnects", "https://www.interconnects.ai/feed"),
    ("One Useful Thing", "https://www.oneusefulthing.org/feed"),
    ("ChinAI", "https://chinai.substack.com/feed"),
    ("Memia", "https://memia.substack.com/feed"),
    ("AI to ROI", "https://ai2roi.substack.com/feed"),
    ("KDnuggets", "https://www.kdnuggets.com/feed"),
]

PODCAST_FEEDS = [
    ("Lex Fridman", "https://lexfridman.com/feed/podcast"),
    ("80,000 Hours", "https://feeds.transistor.fm/80-000-hours-podcast"),
    ("Latent Space", "https://latent.space/feed"),
]


def fetch_ai_newsletters(limit=5, keyword=None):
    """Aggregate AI newsletters."""
    all_items = []
    per_source = max(1, limit // 2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fetch_rss, url, name, per_source): name for name, url in AI_NEWSLETTER_FEEDS}
        for f in concurrent.futures.as_completed(futures):
            all_items.extend(f.result())
    if keyword:
        all_items = filter_keywords(all_items, keyword)
    return all_items[:limit]


def fetch_podcasts(limit=5, keyword=None):
    """Aggregate podcasts."""
    all_items = []
    per_source = max(1, limit // 2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fetch_rss, url, name, per_source): name for name, url in PODCAST_FEEDS}
        for f in concurrent.futures.as_completed(futures):
            all_items.extend(f.result())
    if keyword:
        all_items = filter_keywords(all_items, keyword)
    return all_items[:limit]


def fetch_tldr_ai(limit=3, keyword=None):
    """TLDR AI daily digest."""
    items = fetch_rss("https://tldr.tech/api/rss/ai", "TLDR AI", limit * 2)
    items = filter_by_hours(items, hours=48)
    if keyword:
        items = filter_keywords(items, keyword)
    return items[:limit]


def fetch_import_ai(limit=2, keyword=None):
    """Import AI weekly by Jack Clark."""
    items = fetch_rss("https://importai.substack.com/feed", "Import AI", limit * 2)
    items = filter_by_hours(items, hours=168)
    if keyword:
        items = filter_keywords(items, keyword)
    return items[:limit]


def fetch_aihot(limit=5, keyword=None):
    """AIHOT 中文 AI 精选."""
    items = fetch_rss("https://aihot.virxact.com/rss", "AIHOT", limit * 2)
    items = filter_by_hours(items, hours=24)
    if keyword:
        items = filter_keywords(items, keyword)
    return items[:limit]


# ── Profile Definitions ────────────────────────────────────────────────────
# Each profile: list of (fetcher_func, fetch_limit, keyword_or_None)
# Total output capped at 10 items per profile.

PROFILES = {
    "general": {
        "emoji": "🌅",
        "name": "综合早报",
        "sources": [
            (fetch_hackernews, 3, None),
            (fetch_36kr, 2, None),
            (fetch_github_trending, 2, None),
            (fetch_wallstreetcn, 2, None),
            (fetch_producthunt, 1, None),
        ],
    },
    "finance": {
        "emoji": "💰",
        "name": "财经早报",
        "sources": [
            (fetch_wallstreetcn, 4, None),
            (fetch_36kr, 2, "财报,营收,上市,IPO,投资"),
            (fetch_tencent, 2, "财经,股票,基金,市场"),
            (fetch_hackernews, 2, "Economy,Inflation,Fed,Stock,Finance"),
        ],
    },
    "tech": {
        "emoji": "🤖",
        "name": "科技早报",
        "sources": [
            (fetch_hackernews, 4, "AI,LLM,Transformer,Model,Robot,Startup"),
            (fetch_github_trending, 3, None),
            (fetch_producthunt, 2, "Developer Tools,Coding,API,AI"),
            (fetch_36kr, 1, "融资,首发,独角兽,创投"),
        ],
    },
    "ai_daily": {
        "emoji": "🧠",
        "name": "AI 深度日报",
        "sources": [
            (fetch_ai_newsletters, 4, None),
            (fetch_tldr_ai, 3, None),
            (fetch_aihot, 2, None),
            (fetch_import_ai, 1, None),
        ],
    },
}


def run_profile(profile_key):
    """Execute a single profile and return (profile_info, items)."""
    cfg = PROFILES[profile_key]
    all_items = []

    print(f"  [{cfg['name']}] Fetching {len(cfg['sources'])} sources...", file=sys.stderr)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        future_map = {}
        for fetcher, limit, kw in cfg["sources"]:
            f = ex.submit(fetcher, limit, kw)
            future_map[f] = fetcher.__name__

        for f in concurrent.futures.as_completed(future_map):
            try:
                items = f.result()
                all_items.extend(items)
                print(f"    {future_map[f]}: {len(items)} items", file=sys.stderr)
            except Exception as e:
                print(f"    {future_map[f]}: ERROR {e}", file=sys.stderr)

    # Deduplicate
    seen = set()
    deduped = []
    for item in all_items:
        key = item.get("url", "") or item.get("title", "")
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)

    # Cap at 10
    return cfg, deduped[:10]


def format_item(idx, item):
    """Format a single news item as markdown."""
    title = item.get("title", "Untitled")
    url = item.get("url", "")
    source = item.get("source", "")
    heat = item.get("heat", "")
    time_str = item.get("time", "")
    summary = item.get("summary", "")

    parts = [f"**{idx}.** [{title}]({url})"]

    meta_parts = []
    if source:
        meta_parts.append(f"📰 {source}")
    if time_str:
        meta_parts.append(f"🕐 {time_str}")
    if heat:
        meta_parts.append(f"🔥 {heat}")

    if meta_parts:
        parts.append(f"> `{' | '.join(meta_parts)}`")

    if summary:
        # Truncate long summaries
        s = summary[:200] + "..." if len(summary) > 200 else summary
        parts.append(f"> {s}")

    return "\n".join(parts)


def format_briefing(profile_key):
    """Run a profile and format as markdown section."""
    cfg, items = run_profile(profile_key)

    if not items:
        return f"{cfg['emoji']} **{cfg['name']}**\n\n_暂无数据_\n\n"

    lines = [f"{cfg['emoji']} **{cfg['name']}** ({len(items)} 条)"]
    for i, item in enumerate(items, 1):
        lines.append("")
        lines.append(format_item(i, item))
    lines.append("")
    return "\n".join(lines)


def generate_full_briefing(profiles=None):
    """Run all specified profiles and generate a complete markdown briefing."""
    if profiles is None:
        profiles = list(PROFILES.keys())

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        f"# 📬 每日新闻简报 | {now}",
        "",
    ]

    all_items_count = 0
    for pk in profiles:
        if pk not in PROFILES:
            continue
        section = format_briefing(pk)
        parts.append(section)
        # Count items
        for line in section.split("\n"):
            m = re.match(r".*\*\*(\d+)\.\*\*", line)
            if m:
                all_items_count += 1

    parts.append("---")
    parts.append(f"*共 {all_items_count} 条 · 由 News Briefing Bot 自动生成*")

    return "\n".join(parts)


def push_to_serverchan(key, title, content):
    """Send markdown content to Server酱."""
    url = SERVER_CHAN_URL.format(key=key)
    try:
        r = requests.post(url, data={
            "title": title,
            "desp": content,
        }, timeout=30)
        result = r.json()
        if r.status_code == 200 and result.get("code") == 0:
            print(f"  ✅ Push success: {result.get('message', 'OK')}", file=sys.stderr)
            return True
        else:
            print(f"  ❌ Push failed: {result}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  ❌ Push error: {e}", file=sys.stderr)
        return False


def push_multi_profile(profiles):
    """Push each profile as a separate Server酱 message (better for WeChat reading)."""
    key = os.environ.get("SERVER_CHAN_KEY", "")
    if not key:
        print("❌ SERVER_CHAN_KEY not set", file=sys.stderr)
        return False

    success = True
    now = datetime.now().strftime("%m/%d %H:%M")

    for pk in profiles:
        if pk not in PROFILES:
            continue
        cfg = PROFILES[pk]
        section = format_briefing(pk)
        title = f"{cfg['emoji']} {cfg['name']} | {now}"

        print(f"  Pushing {cfg['name']}...", file=sys.stderr)
        if not push_to_serverchan(key, title, section):
            success = False

    # Also send a summary digest
    summary_lines = [f"📬 简报已送达 | {now}", ""]
    for pk in profiles:
        if pk not in PROFILES:
            continue
        cfg = PROFILES[pk]
        # count items from a quick run
        _, items = run_profile(pk)
        summary_lines.append(f"{cfg['emoji']} {cfg['name']}: {len(items)} 条")

    summary = "\n".join(summary_lines)
    push_to_serverchan(key, f"📬 简报汇总 | {now}", summary)

    return success


# ── CLI Entry Point ────────────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Daily News Briefing")
    parser.add_argument(
        "--profile", "-p",
        default="all",
        help="Profile(s): general,finance,tech,ai_daily or 'all' (default: all)"
    )
    parser.add_argument(
        "--push", action="store_true",
        help="Push to Server酱 (requires SERVER_CHAN_KEY env var)"
    )
    args = parser.parse_args()

    if args.profile == "all":
        profiles = list(PROFILES.keys())
    else:
        profiles = [p.strip() for p in args.profile.split(",") if p.strip() in PROFILES]

    if not profiles:
        print("❌ No valid profiles specified.", file=sys.stderr)
        sys.exit(1)

    print(f"🔍 Profiles: {', '.join(profiles)}", file=sys.stderr)
    print(f"📤 Push mode: {'ON' if args.push else 'OFF'}", file=sys.stderr)

    if args.push:
        push_multi_profile(profiles)
    else:
        # Generate full combined briefing to stdout
        briefing = generate_full_briefing(profiles)
        print(briefing)


if __name__ == "__main__":
    main()
