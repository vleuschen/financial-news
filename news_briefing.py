#!/usr/bin/env python3
"""
Daily News Briefing — standalone script for GitHub Actions + Server酱 (ServerChan).

Fetches from multiple sources, translates English → Chinese, summarizes,
and pushes a single clean briefing to WeChat.

Usage:
  # Test locally
  python news_briefing.py

  # Push to Server酱
  SERVER_CHAN_KEY=your_key python news_briefing.py --push

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
import urllib3
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

# ── UTF-8 Fix for Windows ─────────────────────────────────────────────────

if sys.platform == "win32":
    for s in [sys.stdout, sys.stderr]:
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

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

# ── Emoji Mapping ──────────────────────────────────────────────────────────

TOPIC_EMOJIS = [
    (r"ai|llm|gpt|claude|openai|anthropic|模型|人工智能|大模型|fable|mythos", "🤖"),
    (r"spacex|space|太空|马斯克|musk|starship|龙飞船|卫星|火箭", "🚀"),
    (r"apple|iphone|mac|ipad|vision|库克", "🍎"),
    (r"google|alphabet|pixel|谷歌|deepmind|gemini", "🔍"),
    (r"meta|facebook|instagram|whatsapp|threads|扎克伯格", "👓"),
    (r"nvidia|英伟达|gpu|显卡|黄仁勋|cuda|hopper|blackwell", "🖥️"),
    (r"microsoft|windows|azure|surface|纳德拉|msft", "🪟"),
    (r"github|git.*hub|代码|开源|open.source|repository|仓库|commit|pr|developer", "🐙"),
    (r"创业|融资|创投|独角兽|ipo|天使轮|a轮|b轮|startup|venture|投资机构", "💎"),
    (r"stock|股市|基金|投资|a股|港股|纳斯达克|道指|标普|沪深|上证|深证|证券", "📈"),
    (r"bitcoin|btc|eth|ethereum|区块链|web3|nft|defi|加密|数字货币|币价", "₿"),
    (r"芯片|半导体|台积电|tsmc|intel|amd|光刻|晶圆|制程|chip|processor", "🔬"),
    (r"数据|隐私|安全|泄露|hack|cyber|黑客|勒索|网络攻击|密码", "🔒"),
    (r"5g|6g|通信|华为|中兴|基站|网络|带宽|光纤|物联网|iot", "📡"),
    (r"石油|原油|能源|天然气|gas|新能源|光伏|风电|储能|电池|碳中和|green", "⛽"),
    (r"汽车|ev|电车|特斯拉|tesla|比亚迪|byd|蔚来|小鹏|理想|自动驾驶|智驾|新能源车", "🚗"),
    (r"机器人|人形|humanoid|机器狗|机械臂|仿生|robotics|automation", "🦾"),
    (r"quantum|量子|比特|qubit", "⚛️"),
    (r"基因|医疗|药物|疫苗|health|健康|制药|bio|生物|临床试验|手术", "🧬"),
    (r"气候|环保|碳排放|全球变暖|厄尔尼诺|极端天气|污染|绿色|可持续", "🌍"),
    (r"游戏|gaming|nintendo|sony|playstation|xbox|steam|任天堂|switch", "🎮"),
    (r"视频|youtube|tiktok|抖音|b站|bilibili|短视频|直播|流媒体", "🎬"),
    (r"播客|podcast|lex|fridman|latent.space", "🎙️"),
    (r"中国|北京|上海|中央|国务院|习近平|两会|央行|政策|监管|法规", "🇨🇳"),
    (r"美国|华盛顿|白宫|拜登|trump|特朗普|美联储|fed|硅谷|华尔街", "🇺🇸"),
    (r"俄罗斯|putin|普京|莫斯科|俄乌", "🇷🇺"),
    (r"乌克兰|基辅|泽连斯基", "🇺🇦"),
    (r"欧洲|eu|欧盟|德国|法国|英国|uk|伦敦|巴黎|柏林|脱欧", "🇪🇺"),
    (r"日本|tokyo|东京|索尼|丰田|日经|日元|日本央行", "🇯🇵"),
    (r"韩国|samsung|三星|现代|首尔|韩元", "🇰🇷"),
    (r"台湾|tsmc|台积电|联发科|富士康|鸿海", "🇹🇼"),
    (r"香港|hong.kong|恒生|港股", "🇭🇰"),
    (r"伊朗|以色列|巴勒斯坦|哈马斯|真主党|霍尔木兹|中东|沙特|石油输出国", "🌍"),
    (r"战争|军事|导弹|制裁|防御|冲突|北约|国防|军队|武器", "⚔️"),
    (r"地震|洪水|台风|灾害|暴雨|飓风|海啸", "🌊"),
    (r"选举|大选|投票|民调|campaign|竞选", "🗳️"),
    (r"教育|学校|高考|gaokao|学生|大学|培训|学位", "📚"),
    (r"法律|法规|监管|合规|反垄断|罚款|诉讼|立法|政策|判决|法院", "⚖️"),
    (r"物价|通胀|cpi|ppi|工资|房价|租金|消费|零售|电商|购物", "🏷️"),
    (r"产品|发布|launch|新品|beta|测试版|producthunt|product.hunt", "🆕"),
    (r"新闻|资讯|报道|日报|周刊|newsletter|tldr|import.ai|aihot", "📨"),
]


def get_topic_emoji(title, source=""):
    """Match a news item to its best emoji."""
    text = f"{title} {source}".lower()
    for pattern, emoji in TOPIC_EMOJIS:
        if re.search(pattern, text):
            return emoji
    return "📰"


# ── Translation Engine (Google Translate, no API key) ──────────────────────


_HAS_CHINESE_RE = re.compile(r'[一-鿿㐀-䶿\U00020000-\U0002a6df]')


def has_chinese(text):
    """Check if text contains Chinese characters."""
    return bool(_HAS_CHINESE_RE.search(text))


def _google_translate(text, target="zh-cn", retries=2):
    """Call Google Translate API. Returns translated text or None on failure."""
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": target,
        "dt": "t",
        "q": text[:3000],
    }
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            result = r.json()
            translated = "".join(part[0] for part in result[0] if part[0])
            return translated if translated else None
        except Exception as e:
            if attempt < retries:
                time.sleep(1)
                continue
            print(f"  ⚠️ Translate error: {e}", file=sys.stderr)
    return None


def translate_batch(texts):
    """Translate a list of texts in one API call.

    Google Translate preserves newlines as paragraph separators,
    so we join English texts with a sentinel, translate once, and split.
    """
    if not texts:
        return texts

    ENTRY_SEP = "\n<<-->>\n"

    # Find items that need translation
    indices = [i for i, t in enumerate(texts) if t and not has_chinese(t)]
    if not indices:
        return texts

    # Batch translate: join all English texts with a separator
    eng_texts = [texts[i] for i in indices]
    combined = ENTRY_SEP.join(eng_texts)
    translated = _google_translate(combined)

    if translated is None or translated == combined:
        return texts  # Fallback: keep original

    # Split back
    parts = translated.split(ENTRY_SEP)
    result = list(texts)
    for i, part in zip(indices, parts):
        part = part.strip()
        if part and i < len(result):
            result[i] = part
    return result


# ── Text Cleaning & Summarization ─────────────────────────────────────────


def clean_html(raw):
    """Strip HTML tags, return clean text."""
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def extract_summary(text, max_chars=120):
    """Extract a clean ~20-30 word summary from raw text."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) <= max_chars:
        return text
    # Try to cut at sentence boundary
    truncated = text[:max_chars]
    for sep in ["。", "！", "？", "；", ". ", "! ", "? "]:
        idx = truncated.rfind(sep)
        if idx > max_chars // 3:
            return truncated[: idx + 1]
    # Fallback: cut at last space
    idx = truncated.rfind(" ")
    if idx > max_chars // 3:
        return truncated[:idx] + "…"
    return truncated + "…"


def fetch_url_text(url, max_chars=1500):
    """Fetch URL and extract clean text content."""
    if not url or not url.startswith("http"):
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars]
    except Exception:
        return ""


# ── Content Fetching Pipeline ──────────────────────────────────────────────


def fetch_missing_content(items):
    """Fetch article content for items that lack summaries (parallel)."""
    # For GitHub items: extract description from title
    for item in items:
        title = item.get("title", "")
        if item.get("source") == "GitHub Trending" and " — " in title:
            parts = title.split(" — ", 1)
            item["fetched_content"] = parts[1]

    # Fetch URL content for items without any summary
    to_fetch = [
        it for it in items
        if not it.get("summary") and not it.get("fetched_content")
        and it.get("url") and it["url"].startswith("http")
        and ("news.ycombinator.com/" not in it["url"]
             or "item?id=" not in it["url"])
    ]

    if not to_fetch:
        return

    def fetch_one(item):
        content = fetch_url_text(item["url"])
        if content:
            item["fetched_content"] = content

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        ex.map(fetch_one, to_fetch)


def process_and_summarize(items):
    """Main pipeline: translate + summarize all items in batch."""
    if not items:
        return items

    fetch_missing_content(items)

    # Separate Chinese vs English items
    chinese_items = []
    english_items = []
    for item in items:
        title = item.get("title", "")
        if has_chinese(title):
            chinese_items.append(item)
        else:
            english_items.append(item)

    # ── Batch translate English titles ──
    eng_titles = [it["title"] for it in english_items if it.get("title")]
    translated_titles = translate_batch(eng_titles)
    for item, cn_title in zip(english_items, translated_titles):
        item["title_cn"] = cn_title

    # ── Batch translate English summaries ──
    eng_summaries = []
    for item in english_items:
        src = item.get("summary") or item.get("fetched_content", "")
        if src and has_chinese(src):
            # Already Chinese (e.g. AIHOT)
            item["summary_cn"] = extract_summary(src)
            eng_summaries.append(None)
        elif src:
            eng_summaries.append(extract_summary(src, max_chars=400))
        else:
            eng_summaries.append(None)

    eng_summaries_to_translate = [s for s in eng_summaries if s]
    if eng_summaries_to_translate:
        translated = translate_batch(eng_summaries_to_translate)
        trans_iter = iter(translated)
        for item in english_items:
            if item.get("summary_cn") is None:
                continue  # already set
            src = item.get("summary") or item.get("fetched_content", "")
            if src and has_chinese(src):
                continue  # already set
            if src:
                item["summary_cn"] = extract_summary(next(trans_iter))

    # ── Summarize Chinese items ──
    for item in chinese_items:
        title = item.get("title", "")
        summary = item.get("summary") or item.get("fetched_content", "")
        item["title_cn"] = title
        if summary:
            item["summary_cn"] = extract_summary(summary)
        else:
            item["summary_cn"] = ""

    return items


# ── Helpers ────────────────────────────────────────────────────────────────


def clean_text(text):
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r'^\s*<!\[CDATA\[|\]\]>\s*$', '', text).strip()
    return text


def filter_keywords(items, keyword_str):
    if not keyword_str:
        return items
    keywords = [k.strip() for k in keyword_str.split(",") if k.strip()]
    if not keywords:
        return items
    pattern = "|".join(re.escape(k) for k in keywords)
    regex = rf'(?i)({pattern})'
    return [it for it in items if re.search(regex, it.get("title", ""))]


def filter_by_hours(items, hours=24):
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
            pub = entry.find(["pubdate", "published", "updated", "dc:date"])
            time_str = clean_text(pub.get_text()) if pub else ""
            desc_tag = entry.find("description") or entry.find("summary")
            summary = ""
            if desc_tag:
                raw = desc_tag.get_text()
                summary = clean_html(raw)[:600]
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
    items = []
    if keyword:
        try:
            ts = int(time.time() - 24 * 3600)
            kws = [k.strip() for k in keyword.split(",")]
            quoted = [f'"{k}"' if " " in k else k for k in kws]
            q = " OR ".join(quoted)
            url = (f"https://hn.algolia.com/api/v1/search_by_date"
                   f"?tags=story&numericFilters=created_at_i>{ts}"
                   f"&hitsPerPage={limit * 2}&query={urllib.parse.quote(q)}")
            hits = requests.get(url, timeout=10).json().get("hits", [])
            if not hits and kws:
                url2 = (f"https://hn.algolia.com/api/v1/search_by_date"
                        f"?tags=story&numericFilters=created_at_i>{ts}"
                        f"&hitsPerPage={limit * 2}&query={urllib.parse.quote(kws[0])}")
                hits = requests.get(url2, timeout=10).json().get("hits", [])
            for hit in hits:
                items.append({
                    "source": "Hacker News",
                    "title": hit.get("title", ""),
                    "url": (hit.get("url") or
                            f"https://news.ycombinator.com/item?id={hit['objectID']}"),
                    "heat": f"{hit.get('points', 0)} points",
                    "time": "Today",
                })
            if items:
                return items[:limit]
        except Exception as e:
            print(f"  [HN Algolia] {e}", file=sys.stderr)

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
    items = []
    try:
        url = ("https://api-one.wallstcn.com/apiv1/content/"
               "information-flow?channel=global-channel&accept=article&limit=30")
        r = requests.get(url, timeout=10)
        data = r.json()
        for item in data.get("data", {}).get("items", []):
            res = item.get("resource")
            if res and (res.get("title") or res.get("content_short")):
                ts = res.get("display_time", 0)
                time_str = (datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                            if ts else "")
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
    items = fetch_rss("https://www.producthunt.com/feed", "Product Hunt", limit * 2)
    for it in items:
        it["heat"] = "Trending"
    if keyword:
        items = filter_keywords(items, keyword)
    return items[:limit]


def fetch_weibo(limit=5, keyword=None):
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
                "url": (f"https://s.weibo.com/weibo?q="
                        f"{urllib.parse.quote(title)}&Refer=top"),
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
    ("Lex Fridman Podcast", "https://lexfridman.com/feed/podcast"),
    ("80,000 Hours", "https://feeds.transistor.fm/80-000-hours-podcast"),
    ("Latent Space", "https://latent.space/feed"),
]


def fetch_ai_newsletters(limit=5, keyword=None):
    all_items = []
    per_source = max(1, limit // 2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fetch_rss, url, name, per_source): name
                   for name, url in AI_NEWSLETTER_FEEDS}
        for f in concurrent.futures.as_completed(futures):
            all_items.extend(f.result())
    if keyword:
        all_items = filter_keywords(all_items, keyword)
    return all_items[:limit]


def fetch_tldr_ai(limit=3, keyword=None):
    items = fetch_rss("https://tldr.tech/api/rss/ai", "TLDR AI", limit * 2)
    items = filter_by_hours(items, hours=48)
    if keyword:
        items = filter_keywords(items, keyword)
    return items[:limit]


def fetch_import_ai(limit=2, keyword=None):
    items = fetch_rss("https://importai.substack.com/feed", "Import AI", limit * 2)
    items = filter_by_hours(items, hours=168)
    if keyword:
        items = filter_keywords(items, keyword)
    return items[:limit]


def fetch_aihot(limit=5, keyword=None):
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


# ── Run Pipeline ───────────────────────────────────────────────────────────


def run_profile(profile_key, max_items=15):
    """Fetch, deduplicate, translate, and summarize items for a profile."""
    cfg = PROFILES[profile_key]
    all_items = []

    print(f"  [{cfg['name']}] Fetching {len(cfg['sources'])} sources...", file=sys.stderr)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
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
    print(f"    → Raw: {len(all_items)}, Deduped: {len(deduped)}", file=sys.stderr)

    # Translate & summarize
    processed = process_and_summarize(deduped)
    return cfg, processed[:max_items]


# ── Formatting ─────────────────────────────────────────────────────────────


def format_briefing():
    """Fetch all profiles and format as a clean Chinese briefing."""
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    weekday = WEEKDAY_NAMES[now.weekday()]

    lines = [
        f"📬 **每日新闻简报**",
        f"{date_str} {weekday}",
        "",
    ]

    total_count = 0
    profile_keys = ["general", "finance", "tech"]

    for pk in profile_keys:
        cfg, items = run_profile(pk, max_items=15)
        if not items:
            continue

        lines.append(f"{cfg['emoji']} **{cfg['name']}** · 共 {len(items)} 条")
        lines.append("")
        for i, item in enumerate(items, 1):
            emoji = get_topic_emoji(
                item.get("title_cn") or item.get("title", ""),
                item.get("source", "")
            )
            title_cn = item.get("title_cn") or item.get("title", "")
            summary_cn = item.get("summary_cn", "")

            lines.append(f"{i}. {emoji} {title_cn}")
            if summary_cn:
                lines.append(f"   {summary_cn}")
        lines.append("")
        total_count += len(items)

    # Footer
    now_str = now.strftime("%H:%M")
    lines.append("───")
    lines.append(f"📡 数据源: Hacker News / GitHub / 36氪 / 华尔街见闻 / "
                 f"Product Hunt / 腾讯新闻 / 微博热搜 / AI Newsletters")
    lines.append(f"🤖 共 {total_count} 条 · {now_str} 自动生成")

    return "\n".join(lines), total_count


# ── Server酱 Push ─────────────────────────────────────────────────────────


def push_to_serverchan(key, title, content):
    url = SERVER_CHAN_URL.format(key=key)
    try:
        r = requests.post(url, data={"title": title, "desp": content}, timeout=30)
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
    key = os.environ.get("SERVER_CHAN_KEY", "")
    if not key:
        print("❌ SERVER_CHAN_KEY not set", file=sys.stderr)
        return False

    now = datetime.now()
    title = now.strftime("📬 每日新闻简报 | %Y年%m月%d日")

    print("📡 Fetching all profiles...", file=sys.stderr)
    briefing, total_count = format_briefing()

    print(f"📊 Total: {total_count} items", file=sys.stderr)
    print(f"📤 Pushing to Server酱...", file=sys.stderr)
    return push_to_serverchan(key, title, briefing)


# ── CLI ────────────────────────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Daily News Briefing")
    parser.add_argument("--push", action="store_true",
                        help="Push to Server酱 (requires SERVER_CHAN_KEY env var)")
    args = parser.parse_args()

    if args.push:
        success = push_combined()
        sys.exit(0 if success else 1)
    else:
        briefing, total_count = format_briefing()
        # Print to stdout for local testing
        # (encode errors are replaced to handle Windows console)
        try:
            print(briefing)
        except UnicodeEncodeError:
            print(briefing.encode("utf-8", errors="replace").decode("utf-8"))
        print(f"\n📊 共 {total_count} 条", file=sys.stderr)


if __name__ == "__main__":
    main()
