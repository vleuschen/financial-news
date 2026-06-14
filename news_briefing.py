#!/usr/bin/env python3
"""
Daily News Briefing — standalone script for GitHub Actions + Server酱 (ServerChan).

Fetches from multiple sources, consolidates into 3 categories (综合/财经/科技),
formats as human-readable Chinese briefing, pushes to WeChat via Server酱.

Usage:
  # Test locally (prints to stdout)
  python news_briefing.py

  # Push to Server酱
  SERVER_CHAN_KEY=your_key_here python news_briefing.py --push

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

WEEKDAY_NAMES = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# ── Emoji Helpers ──────────────────────────────────────────────────────────

# Keyword → emoji mapping for news items (checked in order)
TOPIC_EMOJIS = [
    (r"ai|llm|gpt|claude|openai|anthropic|模型|人工智能|大模型|fable|mythos", "🤖"),
    (r"spacex|space|太空|马斯克|musk|starship|龙飞船", "🚀"),
    (r"apple|iphone|mac|ipad|vision|库克", "🍎"),
    (r"google|alphabet|pixel|谷歌|deepmind|gemini", "🔍"),
    (r"meta|facebook|instagram|whatsapp|threads|扎克伯格", "👓"),
    (r"nvidia|英伟达|gpu|显卡|黄仁勋|cuda|hopper|blackwell", "🖥️"),
    (r"microsoft|windows|azure|surface|纳德拉|msft", "🪟"),
    (r"github|git.*hub|代码|开源|open.source|repository|仓库|commit|pr", "🐙"),
    (r"startup|创业|融资|创投|独角兽|ipo|天使轮|a轮|b轮", "💎"),
    (r"stock|股市|基金|投资|a股|港股|纳斯达克|道指|标普|沪深|上证|深证", "📈"),
    (r"crypto|bitcoin|btc|eth|ethereum|区块链|web3|nft|defi|币|加密", "₿"),
    (r"chip|芯片|半导体|台积电|tsmc|intel|amd|光刻|晶圆|制程", "🔬"),
    (r"data|数据|隐私|安全|泄露|hack|cyber|网络攻击|勒索", "🔒"),
    (r"5g|6g|通信|华为|中兴|基站|网络", "📡"),
    (r"oil|原油|石油|能源|天然气|gas|新能源|光伏|风电|储能|电池", "⛽"),
    (r"car|ev|电车|特斯拉|tesla|比亚迪|byd|蔚来|小鹏|理想|自动驾驶|智驾", "🚗"),
    (r"robot|机器人|人形|humanoid|机器狗", "🦾"),
    (r"quantum|量子|比特", "⚛️"),
    (r"bio|基因|医疗|药物|疫苗|health|健康|制药", "🧬"),
    (r"climate|气候|环保|carbon|碳排放|环境|全球变暖|厄尔尼诺", "🌍"),
    (r"game|游戏|gaming|nintendo|sony|playstation|xbox|steam|任天堂", "🎮"),
    (r"video|youtube|tiktok|抖音|b站|bilibili|短视频|直播", "🎬"),
    (r"podcast|播客|lex|fridman|latent.space", "🎙️"),
    (r"china|中国|北京|上海|中央|国务院|政策|习近平|两会", "🇨🇳"),
    (r"us|usa|美国|华盛顿|白宫|拜登|trump|特朗普|美联储|fed", "🇺🇸"),
    (r"russia|俄罗斯|putin|普京|莫斯科", "🇷🇺"),
    (r"ukraine|乌克兰|基辅|泽连斯基", "🇺🇦"),
    (r"europe|eu|欧盟|欧洲|德国|法国|英国|uk|伦敦|巴黎|柏林", "🇪🇺"),
    (r"japan|日本|tokyo|东京|索尼|丰田", "🇯🇵"),
    (r"korea|韩国|samsung|三星|现代|首尔", "🇰🇷"),
    (r"taiwan|tsmc|台积电|台湾|联发科", "🇹🇼"),
    (r"hong.kong|香港", "🇭🇰"),
    (r"middle.east|伊朗|以色列|巴勒斯坦|哈马斯|真主党|霍尔木兹|美伊|黎巴嫩", "🌍"),
    (r"war|战争|军事|导弹|制裁|防御|冲突", "⚔️"),
    (r"earthquake|地震|洪水|台风|灾害|暴雨", "🌊"),
    (r"election|选举|大选|投票|民调", "🗳️"),
    (r"education|教育|学校|高考|gaokao|学生|大学", "📚"),
    (r"law|法规|监管|合规|反垄断|罚款|诉讼|立法|政策|regulation|ban|禁止", "⚖️"),
    (r"space|nasa|卫星|火箭|发射|space", "🌌"),
    (r"price|涨价|降价|通胀|cpi|ppi|物价|工资|inflation", "🏷️"),
    (r"product.hunt|producthunt|新产品|发布|launch", "🆕"),
    (r"tldr|import.ai|aihot|newsletter|资讯|简报|日报|周刊", "📨"),
]


def get_topic_emoji(title, source=""):
    """Match a news item to its best emoji based on title and source."""
    text = f"{title} {source}".lower()
    for pattern, emoji in TOPIC_EMOJIS:
        if re.search(pattern, text):
            return emoji
    return "📰"


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


def deduplicate(items):
    """Remove duplicates by URL then by title."""
    seen_url = set()
    seen_title = set()
    result = []
    for item in items:
        url = item.get("url", "") or ""
        title = item.get("title", "") or ""
        if url and url in seen_url:
            continue
        if title and title in seen_title:
            continue
        if url:
            seen_url.add(url)
        if title:
            seen_title.add(title)
        result.append(item)
    return result


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
    ("Interconnects (Nathan Lambert)", "https://www.interconnects.ai/feed"),
    ("One Useful Thing (Ethan Mollick)", "https://www.oneusefulthing.org/feed"),
    ("ChinAI (Jeffrey Ding)", "https://chinai.substack.com/feed"),
    ("Memia (Ben Reid)", "https://memia.substack.com/feed"),
    ("AI to ROI", "https://ai2roi.substack.com/feed"),
    ("KDnuggets", "https://www.kdnuggets.com/feed"),
]

PODCAST_FEEDS = [
    ("Lex Fridman Podcast", "https://lexfridman.com/feed/podcast"),
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

PROFILES = {
    "general": {
        "emoji": "🌅",
        "name": "综合早报",
        "sources": [
            (fetch_hackernews, 6, None),
            (fetch_36kr, 4, None),
            (fetch_github_trending, 3, None),
            (fetch_wallstreetcn, 3, None),
            (fetch_producthunt, 2, None),
            (fetch_weibo, 2, None),
        ],
    },
    "finance": {
        "emoji": "💰",
        "name": "财经早报",
        "sources": [
            (fetch_wallstreetcn, 8, None),
            (fetch_36kr, 4, "财报,营收,上市,IPO,投资,基金,股市"),
            (fetch_tencent, 3, "财经,股票,基金,市场,经济"),
            (fetch_hackernews, 3, "Economy,Inflation,Fed,Stock,Finance,Bank,Market"),
        ],
    },
    "tech": {
        "emoji": "🤖",
        "name": "科技早报",
        "sources": [
            (fetch_hackernews, 5, "AI,LLM,GPT,Claude,Model,Robot,Startup,Tech,Apple,Google,Meta,Microsoft"),
            (fetch_github_trending, 4, None),
            (fetch_producthunt, 3, "Developer Tools,Coding,API,AI,Tech"),
            (fetch_36kr, 2, "融资,首发,独角兽,创投,科技"),
            (fetch_ai_newsletters, 4, None),
            (fetch_aihot, 3, None),
            (fetch_tldr_ai, 3, None),
            (fetch_import_ai, 1, None),
        ],
    },
}


# ── Fetch & Format ─────────────────────────────────────────────────────────


def run_profile(profile_key, max_items=15):
    """Execute a single profile and return (profile_info, deduplicated items)."""
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

    deduped = deduplicate(all_items)
    print(f"    → Total: {len(all_items)}, After dedup: {len(deduped)}", file=sys.stderr)
    return cfg, deduped[:max_items]


def format_news_item(idx, item):
    """Format a single news item in clean WeChat-friendly style."""
    title = item.get("title", "Untitled")
    url = item.get("url", "")
    source = item.get("source", "")
    heat = item.get("heat", "")
    time_str = item.get("time", "")

    # Pick emoji
    emoji = get_topic_emoji(title, source)

    # Build line 1: number + emoji + title
    lines = [f"{idx}. {emoji} {title}"]

    # Build line 2: source tag + metadata
    meta_parts = []
    if source:
        meta_parts.append(f"📰 {source}")
    if heat:
        heat_clean = re.sub(r"\s+points$", "", heat)
        heat_clean = re.sub(r"\s+stars$", "⭐", heat_clean)
        meta_parts.append(f"🔥 {heat_clean}")
    if time_str and time_str not in ("Today", "Real-time", "Hot", ""):
        # Normalize time formatting
        t = time_str
        try:
            parsed = parsedate_to_datetime(str(t))
            local = parsed.replace(tzinfo=timezone.utc).astimezone()
            t = local.strftime("%m-%d %H:%M")
        except Exception:
            # Fallback: just take first 10 chars if it's a date string
            if len(t) > 16:
                t = t[:10]
        meta_parts.append(f"🕐 {t}")

    if meta_parts:
        lines.append(f"   {' '.join(meta_parts)}")

    # Line 3: URL
    if url:
        lines.append(f"   🔗 {url}")

    return "\n".join(lines)


def format_section_header(cfg, count):
    """Format a section header with title and item count."""
    emoji = cfg["emoji"]
    name = cfg["name"]
    return f"{emoji} **{name}** · 共 {count} 条" + "\n" + "─" * 30


def generate_combined_briefing():
    """Fetch all profiles and generate a single consolidated briefing."""
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    weekday = WEEKDAY_NAMES[now.weekday()]

    header = (
        f"📬 **每日新闻简报**\n"
        f"{date_str} {weekday}\n"
    )

    # Fetch all profiles
    sections = []
    total_count = 0

    profile_keys = ["general", "finance", "tech"]
    for pk in profile_keys:
        cfg, items = run_profile(pk, max_items=15)
        if not items:
            continue

        lines = [""]
        lines.append(format_section_header(cfg, len(items)))
        lines.append("")
        for i, item in enumerate(items, 1):
            lines.append(format_news_item(i, item))
            lines.append("")

        sections.append("\n".join(lines))
        total_count += len(items)

    # Footer
    now_str = now.strftime("%m-%d %H:%M")
    footer = (
        f"───\n"
        f"📡 数据源: Hacker News / GitHub Trending / 36氪 / 华尔街见闻 "
        f"/ Product Hunt / 腾讯新闻 / 微博热搜 / AI Newsletters\n"
        f"🤖 由 News Briefing Bot 于 {now_str} 自动生成"
    )

    return header + "".join(sections) + "\n" + footer, total_count


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


def push_combined():
    """Fetch all profiles and push ONE combined message to Server酱."""
    key = os.environ.get("SERVER_CHAN_KEY", "")
    if not key:
        print("❌ SERVER_CHAN_KEY not set", file=sys.stderr)
        return False

    now = datetime.now()
    title = now.strftime("📬 每日新闻简报 | %Y年%m月%d日")

    print("📡 Fetching all profiles...", file=sys.stderr)
    briefing, total_count = generate_combined_briefing()

    print(f"📊 Total items: {total_count}", file=sys.stderr)
    print(f"📤 Pushing to Server酱...", file=sys.stderr)

    return push_to_serverchan(key, title, briefing)


# ── CLI Entry Point ────────────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Daily News Briefing")
    parser.add_argument(
        "--profile", "-p",
        default="all",
        help="Profile(s): general,finance,tech or 'all' (default: all)"
    )
    parser.add_argument(
        "--push", action="store_true",
        help="Push to Server酱 (requires SERVER_CHAN_KEY env var)"
    )
    args = parser.parse_args()

    if args.push:
        success = push_combined()
        sys.exit(0 if success else 1)
    else:
        briefing, total_count = generate_combined_briefing()
        print(briefing)
        print(f"\n📊 共 {total_count} 条新闻", file=sys.stderr)


if __name__ == "__main__":
    main()
