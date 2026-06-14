#!/usr/bin/env python3
"""
Daily News Briefing — GitHub Actions + Server酱.
抓取新闻 → 提取正文 → 翻译中文 → 30字摘要 → 推送微信.

Usage:
  python news_briefing.py                # 本地测试
  SERVER_CHAN_KEY=xxx python news_briefing.py --push  # 推送
"""

import io, os, re, sys, time
import concurrent.futures, urllib.parse, urllib3
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

if sys.platform == "win32":
    for s in [sys.stdout, sys.stderr]:
        try: s.reconfigure(encoding="utf-8")
        except: pass

SERVER_CHAN_URL = os.environ.get("SERVER_CHAN_URL", "https://sctapi.ftqq.com/{key}.send")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"}
WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# ── 36氪 标题垃圾前缀 ─────────────────────────────────────────
_36KR_PREFIXES = [
    "36氪Auto", "数字时氪", "未来消费", "智能涌现", "未来城市",
    "启动Power on", "36氪出海", "36氪", "新经济IPO", "Meta",
    "风向", "To B产业真探", "硬氪", "新能源",
]

def clean_title(title, source=""):
    t = (title or "").strip()
    if "36氪" in source or "36kr" in source:
        for p in _36KR_PREFIXES:
            if t.startswith(p):
                t = t[len(p):].strip()
                break
        t = re.sub(r'^\||\|\s*$', '', t).strip()
    t = re.sub(r'^(首页|\||专题|•|●|·)\s*', '', t).strip()
    t = re.sub(r'\s*\|\s*$', '', t).strip()
    return re.sub(r'\s+', ' ', t).strip()

# ── Emoji ─────────────────────────────────────────────────────────────
TOPIC_EMOJIS = [
    (r"ai|llm|gpt|claude|openai|anthropic|模型|人工智能|大模型|fable|mythos|chatgpt|deepseek|agent", "🤖"),
    (r"spacex|space|太空|马斯克|musk|starship|龙飞船|卫星|火箭|nasa|space", "🚀"),
    (r"apple|iphone|mac|ipad|vision|库克|airpods|watch|ios", "🍎"),
    (r"google|alphabet|pixel|谷歌|deepmind|gemini|gmail|chrome|android", "🔍"),
    (r"meta|facebook|instagram|whatsapp|threads|扎克伯格|llama", "👓"),
    (r"nvidia|英伟达|gpu|显卡|黄仁勋|cuda|hopper|blackwell|rtx", "🖥️"),
    (r"microsoft|windows|azure|surface|纳德拉|msft|office|copilot", "🪟"),
    (r"github|git|代码|开源|open.source|repository|仓库|commit|pr|developer", "🐙"),
    (r"创业|融资|创投|独角兽|ipo|天使轮|a轮|b轮|startup|venture|vc|pe", "💎"),
    (r"股票|股市|基金|投资|a股|港股|纳斯达克|道指|标普|沪深|上证|深证|证券|牛市|熊市", "📈"),
    (r"bitcoin|btc|eth|ethereum|区块链|web3|nft|加密|数字货币|币价|比特币|以太坊", "₿"),
    (r"芯片|半导体|台积电|tsmc|intel|amd|光刻|晶圆|制程|chip|processor|骁龙|麒麟", "🔬"),
    (r"数据|隐私|安全|泄露|hack|cyber|黑客|勒索|网络攻击|密码|防火墙", "🔒"),
    (r"5g|6g|通信|华为|中兴|基站|网络|带宽|光纤|物联网|iot|starlink", "📡"),
    (r"石油|原油|能源|天然气|新能源|光伏|风电|储能|电池|碳中和|green|氢能", "⛽"),
    (r"汽车|ev|电车|特斯拉|tesla|比亚迪|byd|蔚来|小鹏|理想|自动驾驶|智驾|新能源车", "🚗"),
    (r"机器人|人形|humanoid|机器狗|机械臂|仿生|robotics|automation|宇树", "🦾"),
    (r"quantum|量子|比特|qubit", "⚛️"),
    (r"基因|医疗|药物|疫苗|health|健康|制药|bio|生物|临床试验|手术|诊断", "🧬"),
    (r"气候|环保|碳排放|全球变暖|厄尔尼诺|极端天气|污染|绿色|可持续", "🌍"),
    (r"游戏|gaming|nintendo|sony|playstation|xbox|steam|任天堂|switch|epic", "🎮"),
    (r"视频|youtube|tiktok|抖音|b站|bilibili|短视频|直播|流媒体|netflix|disney", "🎬"),
    (r"播客|podcast|lex|fridman|latent.space", "🎙️"),
    (r"中国|北京|上海|中央|国务院|习近平|两会|央行|政策|监管|法规|发改委|商务部", "🇨🇳"),
    (r"美国|华盛顿|白宫|拜登|trump|特朗普|美联储|fed|硅谷|华尔街|参议院|众议院", "🇺🇸"),
    (r"俄罗斯|putin|普京|莫斯科|俄乌|俄军", "🇷🇺"),
    (r"乌克兰|基辅|泽连斯基|乌军", "🇺🇦"),
    (r"欧洲|eu|欧盟|德国|法国|英国|uk|伦敦|巴黎|柏林|脱欧|欧元|欧洲央行", "🇪🇺"),
    (r"日本|tokyo|东京|索尼|丰田|日经|日元|日本央行|软银|三菱", "🇯🇵"),
    (r"韩国|samsung|三星|现代|首尔|韩元|lg|sk", "🇰🇷"),
    (r"台湾|tsmc|台积电|联发科|富士康|鸿海", "🇹🇼"),
    (r"香港|hong.kong|恒生|港股|港交所", "🇭🇰"),
    (r"伊朗|以色列|巴勒斯坦|哈马斯|真主党|霍尔木兹|中东|沙特|opec|胡塞", "🌍"),
    (r"战争|军事|导弹|制裁|防御|冲突|北约|国防|军队|武器|航母|战机", "⚔️"),
    (r"地震|洪水|台风|灾害|暴雨|飓风|海啸|山火", "🌊"),
    (r"选举|大选|投票|民调|campaign|竞选|连任", "🗳️"),
    (r"教育|学校|高考|gaokao|学生|大学|培训|学位|考研|留学|教材", "📚"),
    (r"法律|法规|监管|合规|反垄断|罚款|诉讼|立法|政策|判决|法院|仲裁", "⚖️"),
    (r"物价|通胀|cpi|ppi|工资|房价|租金|消费|零售|电商|购物|双11|618", "🏷️"),
    (r"手机|xiaomi|小米|oppo|vivo|荣耀|honor|oneplus|一加|pixel|samsung", "📱"),
]

def get_emoji(title, source=""):
    t = f"{title} {source}".lower()
    for pat, emo in TOPIC_EMOJIS:
        if re.search(pat, t): return emo
    return "📰"

# ── 翻译 ─────────────────────────────────────────────────────────────
_HAS_CN = re.compile(r'[一-鿿㐀-䶿\U00020000-\U0002a6df]')

def has_chinese(text):
    return bool(_HAS_CN.search(text))

KEEP_WORDS = [
    "Claude Code", "Claude", "Codex", "Cursor", "GitHub Copilot",
    "ChatGPT", "Gemini", "Perplexity", "Midjourney", "Stable Diffusion",
    "Sora", "Mythos", "Fable", "Hacker News", "Product Hunt",
    "Reddit", "SpaceX", "Tesla", "OpenAI", "Anthropic", "DeepMind",
    "AlphaFold", "Transformer", "RAG", "LoRA", "Agentic", "MCP",
    "A2A", "AGI", "ASI", "Llama", "Mixtral", "Qwen", "Bloomberg",
    "Reuters", "BBC", "CNN", "NYT", "WSJ", "WaPo", "PlayStation",
    "Xbox", "Nintendo", "Spotify", "Netflix", "Uber", "Airbnb",
    "Python", "JavaScript", "TypeScript", "Rust", "Kubernetes",
    "Docker", "Linux", "GitHub", "GitLab", "BitBucket", "npm", "PyPI",
    "iPhone", "iPad", "MacBook", "AirPods", "Apple Watch", "Vision Pro",
    "DALL-E",
]

def translate_to_cn(text):
    """英译中，保护专有名词。单个英文词不翻。"""
    if not text or not text.strip() or has_chinese(text):
        return text
    t = text.strip()
    # 单个英文词→不翻
    if ' ' not in t and t.isascii() and len(t) > 1:
        return t

    # 专有名词保护：用 @@K0@@ @@K1@@ 之类安全占位符
    kept = {}
    ordered = sorted(KEEP_WORDS, key=len, reverse=True)
    for i, w in enumerate(ordered):
        if w.lower() in t.lower():
            ph = f"@@K{i}@@"
            kept[ph] = w
            # 大小写不敏感替换
            t = re.sub(re.escape(w), ph, t, flags=re.IGNORECASE)

    for attempt in range(3):
        try:
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "zh-cn",
                        "dt": "t", "q": t[:3000]},
                timeout=15
            )
            r.raise_for_status()
            result = r.json()
            translated = "".join(p[0] for p in result[0] if p[0])
            if translated:
                for ph, orig in kept.items():
                    translated = translated.replace(ph, orig)
                return translated
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
                continue
    return text

# ── 正文提取 ───────────────────────────────────────────────────────
def _try_extract(url):
    """尝试提取文章正文。失败返回空字符串，不抛异常。"""
    if not url or "item?id=" in url:
        return ""
    try:
        import trafilatura
        downloaded = trafilatura.fetch_url(url, timeout=12)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_links=False, include_tables=False) or ""
        text = text.strip()
        if len(text) < 50:
            return ""
        # 取第一段
        for sep in ["\n\n", "\n\r\n", "\r\n\r\n", "\n"]:
            if sep in text:
                first_p = [p.strip() for p in text.split(sep) if len(p.strip()) > 30]
                if first_p:
                    return first_p[0][:500]
        return text[:500]
    except Exception:
        return ""

# ── RSS ─────────────────────────────────────────────────────────────
def parse_rss(content, src, limit=10):
    items = []
    try:
        soup = BeautifulSoup(content, "lxml")
        for entry in soup.find_all(["item", "entry"]):
            tag = entry.find("title")
            if not tag: continue
            title = re.sub(r'^\s*<!\[CDATA\[|\]\]>\s*$', '', tag.get_text(strip=True) or "").strip()
            if not title: continue
            link = ""
            lt = entry.find("link")
            if lt:
                if lt.has_attr("href"): link = lt["href"]
                elif lt.get_text(strip=True): link = lt.get_text(strip=True)
            if not link:
                g = entry.find("guid")
                if g and g.get_text(strip=True).startswith("http"): link = g.get_text(strip=True)
            pub = entry.find(["pubdate", "published", "updated", "dc:date"])
            ts = pub.get_text(strip=True) if pub else ""
            desc = entry.find("description") or entry.find("summary")
            summary = ""
            if desc:
                raw = re.sub(r'^\s*<!\[CDATA\[|\]\]>\s*$', '', desc.get_text() or "").strip()
                summary = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)[:1000]
            items.append({"source": src, "title": title, "url": link, "time": ts, "summary": summary})
            if len(items) >= limit: break
    except Exception as e:
        print(f"  [RSS] {src}: {e}", file=sys.stderr)
    return items

def fetch_rss(url, src, limit=10):
    for a in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return parse_rss(r.content, src, limit)
        except Exception as e:
            if a < 2: time.sleep(1 + a)
            else: print(f"  [RSS] {url}: {e}", file=sys.stderr)
    return []

# ── 数据源 ─────────────────────────────────────────────────────────

def fetch_hackernews(limit=5, keyword=None):
    items = []
    if keyword:
        try:
            ts = int(time.time() - 24 * 3600)
            kws = [k.strip() for k in keyword.split(",")]
            quoted = [f'"{k}"' if " " in k else k for k in kws]
            hits = requests.get(
                f"https://hn.algolia.com/api/v1/search_by_date"
                f"?tags=story&numericFilters=created_at_i>{ts}"
                f"&hitsPerPage={limit * 2}&query={urllib.parse.quote(' OR '.join(quoted))}",
                timeout=10).json().get("hits", [])
            if not hits and kws:
                hits = requests.get(
                    f"https://hn.algolia.com/api/v1/search_by_date"
                    f"?tags=story&numericFilters=created_at_i>{ts}"
                    f"&hitsPerPage={limit * 2}&query={urllib.parse.quote(kws[0])}",
                    timeout=10).json().get("hits", [])
            for h in hits:
                items.append({"source": "Hacker News",
                    "title": h.get("title", ""),
                    "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                    "points": h.get("points", 0), "time": "Today"})
            if items: return items[:limit]
        except Exception as e:
            print(f"  [HN] {e}", file=sys.stderr)
    # fallback front-page
    try:
        soup = BeautifulSoup(requests.get("https://news.ycombinator.com/news", headers=HEADERS, timeout=10).text, "lxml")
        for row in soup.select(".athing"):
            tl = row.select_one(".titleline a")
            if not tl: continue
            href = tl.get("href", "")
            items.append({"source": "Hacker News", "title": tl.get_text(),
                "url": f"https://news.ycombinator.com/{href}" if href.startswith("item?id=") else href,
                "points": 0, "time": "Today"})
        if keyword: items = [it for it in items if any(k.lower() in it["title"].lower() for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [HN] {e}", file=sys.stderr)
    return items[:limit]

def fetch_36kr(limit=5, keyword=None):
    items = []
    try:
        soup = BeautifulSoup(requests.get("https://36kr.com/newsflashes", headers=HEADERS, timeout=10).text, "lxml")
        for el in soup.select(".newsflash-item"):
            te = el.select_one(".item-title")
            if not te: continue
            title = te.get_text(strip=True)
            href = te.get("href", "")
            if href and not href.startswith("http"): href = "https://36kr.com" + href
            tm = el.select_one(".time")
            ts = tm.get_text(strip=True) if tm else ""
            items.append({"source": "36氪", "title": title, "url": href, "time": ts})
        if keyword: items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [36Kr] {e}", file=sys.stderr)
    return items[:limit]

def fetch_wallstreetcn(limit=5, keyword=None):
    items = []
    try:
        data = requests.get(
            "https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&accept=article&limit=30",
            timeout=10).json()
        for item in data.get("data", {}).get("items", []):
            res = item.get("resource")
            if res and (res.get("title") or res.get("content_short")):
                ts = res.get("display_time", 0)
                items.append({"source": "华尔街见闻",
                    "title": res.get("title") or res.get("content_short"),
                    "url": res.get("uri", ""),
                    "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""})
        if keyword: items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [WSCN] {e}", file=sys.stderr)
    return items[:limit]

def fetch_tencent(limit=5, keyword=None):
    items = []
    try:
        data = requests.get(
            "https://i.news.qq.com/web_backend/v2/getTagInfo?tagId=aEWqxLtdgmQ%3D",
            headers={"Referer": "https://news.qq.com/"}, timeout=10).json()
        for n in data.get("data", {}).get("tabs", [{}])[0].get("articleList", []):
            items.append({"source": "腾讯新闻", "title": n.get("title", ""),
                "url": n.get("url") or n.get("link_info", {}).get("url", ""),
                "time": n.get("pub_time", "") or n.get("publish_time", "")})
        if keyword: items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [QQ] {e}", file=sys.stderr)
    return items[:limit]

def fetch_weibo(limit=5, keyword=None):
    items = []
    try:
        raw = requests.get("https://weibo.com/ajax/side/hotSearch", headers={
            "User-Agent": HEADERS["User-Agent"], "Referer": "https://weibo.com/"}, timeout=10).json()
        for item in raw.get("data", {}).get("realtime", []):
            title = item.get("note", "") or item.get("word", "")
            if not title: continue
            items.append({"source": "微博热搜", "title": title, "heat": str(item.get("num", 0)), "time": "Real-time"})
        if keyword: items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [Weibo] {e}", file=sys.stderr)
    return items[:limit]

# ── AI 简讯源 ────────────────────────────────────────────────────
AI_FEEDS = [
    ("Interconnects", "https://www.interconnects.ai/feed"),
    ("One Useful Thing", "https://www.oneusefulthing.org/feed"),
    ("ChinAI", "https://chinai.substack.com/feed"),
    ("Memia", "https://memia.substack.com/feed"),
    ("AI to ROI", "https://ai2roi.substack.com/feed"),
    ("KDnuggets", "https://www.kdnuggets.com/feed"),
]

def fetch_ai_newsletters(limit=5, keyword=None):
    all_items = []
    per = max(1, limit // 2)
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        fs = {ex.submit(fetch_rss, u, n, per): n for n, u in AI_FEEDS}
        for f in concurrent.futures.as_completed(fs):
            all_items.extend(f.result())
    if keyword: all_items = [it for it in all_items if any(k.lower() in it["title"].lower() for k in keyword.split(",") if k.strip())]
    return all_items[:limit]

def fetch_tldr(limit=3, keyword=None):
    items = fetch_rss("https://tldr.tech/api/rss/ai", "TLDR AI", limit * 2)
    items = [it for it in items if _within_hours(it.get("time", ""), 48)]
    return items[:limit]

def fetch_import_ai(limit=2, keyword=None):
    items = fetch_rss("https://importai.substack.com/feed", "Import AI", limit * 2)
    items = [it for it in items if _within_hours(it.get("time", ""), 168)]
    return items[:limit]

def fetch_aihot(limit=5, keyword=None):
    items = fetch_rss("https://aihot.virxact.com/rss", "AIHOT", limit * 2)
    items = [it for it in items if _within_hours(it.get("time", ""), 24)]
    return items[:limit]

def _within_hours(time_str, hours):
    if not time_str: return True
    try:
        pub = parsedate_to_datetime(str(time_str))
        if pub.tzinfo is None: pub = pub.replace(tzinfo=timezone.utc)
        return pub >= (datetime.now(timezone.utc) - timedelta(hours=hours))
    except: return True

# ── Profile ────────────────────────────────────────────────────────
PROFILES = {
    "general": {"emoji": "🌅", "name": "综合早报",
        "sources": [
            (fetch_36kr, 8, None), (fetch_wallstreetcn, 5, None),
            (fetch_hackernews, 7, "AI,LLM,GPT,Claude,Model,Robot,Tech,Apple,Google,Meta,Tesla,SpaceX"),
            (fetch_weibo, 3, None), (fetch_ai_newsletters, 4, None), (fetch_aihot, 3, None),
        ]},
    "finance": {"emoji": "💰", "name": "财经早报",
        "sources": [
            (fetch_wallstreetcn, 8, None),
            (fetch_36kr, 6, "财报,营收,上市,IPO,投资,基金,股市,经济"),
            (fetch_tencent, 4, "财经,股票,基金,市场,经济,金融"),
            (fetch_hackernews, 4, "Economy,Inflation,Fed,Stock,Finance,Bank,Market,Invest"),
        ]},
    "tech": {"emoji": "🤖", "name": "科技早报",
        "sources": [
            (fetch_hackernews, 6, "AI,LLM,GPT,Claude,Model,Robot,Tech,Apple,Google,Meta,Microsoft,Chip,Startup"),
            (fetch_36kr, 4, "融资,首发,独角兽,创投,科技,AI,人工智能"),
            (fetch_ai_newsletters, 5, None), (fetch_aihot, 4, None), (fetch_tldr, 3, None), (fetch_import_ai, 2, None),
        ]},
}

# ── 核心处理 ──────────────────────────────────────────────────────

def dedup(items):
    seen_url, seen_title, result = set(), set(), []
    for it in items:
        u, t = it.get("url", "") or "", it.get("title", "") or ""
        if u and u in seen_url: continue
        if t and t in seen_title: continue
        if u: seen_url.add(u)
        if t: seen_title.add(t)
        result.append(it)
    return result

def _first_good_paragraph(text):
    """提取正文中第一段有意义的段落（30字以上）。"""
    if not text: return ""
    text = re.sub(r'\s+', ' ', text).strip()
    # 找段落分隔
    for sep in ["\n\n", "\n\r\n", "\r\n\r\n"]:
        if sep in text:
            for p in text.split(sep):
                p = p.strip()
                if len(p) > 25:
                    return p
    # 按句号分
    for sep in ["。", "！", "？", "；"]:
        idx = text.find(sep)
        if 10 < idx < 400:
            return text[:idx+1]
    return text[:200] if len(text) > 20 else ""

def _is_bad(text):
    if not text or len(text) < 10: return True
    if text.startswith("%PDF"): return True
    nav_count = sum(1 for m in ["Skip to", "Sign in", "Subscribe", "Cookie", "All rights", "Terms of"] if m.lower() in text.lower())
    return nav_count >= 2

def tr(text):
    """简写翻译，先检查是否需要翻。"""
    return translate_to_cn(text) if text and not has_chinese(text) else text

def process_item(it):
    """单条新闻处理：标题翻译 + 正文提取 + 摘要生成。

    返回一句 30-50 字的中文新闻句。
    """
    title = clean_title(it.get("title", ""), it.get("source", ""))
    src = it.get("source", "")
    summary_raw = it.get("summary", "")
    url = it.get("url", "")

    # ── 中文源：标题就是新闻 ──
    if src in ("36氪", "华尔街见闻", "腾讯新闻", "微博热搜"):
        return tr(title)

    # ── AIHOT：已有中文摘要 ──
    if src == "AIHOT" and has_chinese(summary_raw):
        s = _first_good_paragraph(summary_raw)
        if s: return s

    # ── Hacker News：翻译标题。尝试提取正文，不行就用标题 ──
    if src == "Hacker News":
        title_cn = tr(title)
        if not title_cn or len(title_cn) < 8:
            return ""
        # 尝试提取正文（失败了就用标题，不勉强）
        body = _try_extract(url)
        if body:
            body_cn = tr(body[:400])
            if body_cn and len(body_cn) > 20:
                # 标题 + 正文第一句
                merged = f"{title_cn}：{body_cn}"
                return merged[:120]
        return title_cn

    # ── AI 简讯（Interconnects / One Useful Thing / TLDR / Import AI 等） ──
    if summary_raw and not _is_bad(summary_raw):
        # RSS 描述可能存在
        if has_chinese(summary_raw):
            s = _first_good_paragraph(summary_raw)
            if s: return s
        cn = tr(summary_raw[:600])
        if cn and cn != summary_raw[:600]:
            s = _first_good_paragraph(cn)
            if s: return s

    # 兜底：翻译标题
    title_cn = tr(title)
    return title_cn if len(title_cn) >= 8 else ""

def run_profile(key, max_items=15):
    cfg = PROFILES[key]
    all_items = []
    print(f"  [{cfg['name']}] 抓取 {len(cfg['sources'])} 个数据源...", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(10) as ex:
        fm = {ex.submit(fn, lm, kw if isinstance(kw, (str, type(None))) else None):
              fn.__name__ for fn, lm, kw in cfg["sources"]}
        for f in concurrent.futures.as_completed(fm):
            try:
                its = f.result()
                all_items.extend(its)
                print(f"    {fm[f]}: {len(its)} 条", file=sys.stderr)
            except Exception as e:
                print(f"    {fm[f]}: 错误 {e}", file=sys.stderr)

    all_items = dedup(all_items)
    print(f"    → 去重后: {len(all_items)} 条", file=sys.stderr)

    results = []
    for it in all_items:
        line = process_item(it)
        if line and len(line) >= 10:
            results.append((it, line))

    print(f"    → 合格: {len(results)} 条", file=sys.stderr)
    return cfg, results[:max_items]

# ── 格式化输出 ───────────────────────────────────────────────────
def build_briefing():
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    weekday = WEEKDAYS[now.weekday()]

    lines = [f"{date_str} {weekday}", ""]
    total = 0

    for pk in ["general", "finance", "tech"]:
        cfg, items = run_profile(pk, 15)
        if not items:
            continue
        lines.append(f"{cfg['emoji']} **{cfg['name']}** · 共 {len(items)} 条")
        lines.append("")
        for i, (it, nl) in enumerate(items, 1):
            emo = get_emoji(it.get("title", ""), it.get("source", ""))
            lines.append(f"{i}. {emo} {nl}")
            lines.append("")
        total += len(items)

    lines.append("─" * 30)
    lines.append(f"📡 数据源: Hacker News / AI Newsletters / 36氪 / 华尔街见闻 / 腾讯新闻 / 微博热搜")
    lines.append(f"🤖 共 {total} 条 · {now.strftime('%H:%M')} 自动生成")
    lines.append("")
    return "\n".join(lines), total

# ── 推送 ─────────────────────────────────────────────────────────
def push_combined():
    key = os.environ.get("SERVER_CHAN_KEY", "")
    if not key:
        print("❌ SERVER_CHAN_KEY 未设置", file=sys.stderr)
        return False
    now = datetime.now()
    title = now.strftime("📬 每日新闻简报 | %Y年%m月%d日")
    print("📡 抓取中...", file=sys.stderr)
    briefing, n = build_briefing()
    print(f"📊 共 {n} 条", file=sys.stderr)
    try:
        r = requests.post(SERVER_CHAN_URL.format(key=key),
            data={"title": title, "desp": briefing}, timeout=30)
        res = r.json()
        if r.status_code == 200 and res.get("code") == 0:
            print(f"✅ 推送成功: {res.get('message', 'OK')}", file=sys.stderr)
            return True
        print(f"❌ 推送失败: {res}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"❌ 推送错误: {e}", file=sys.stderr)
        return False

# ── CLI ──────────────────────────────────────────────────────────
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    args = ap.parse_args()
    if args.push:
        sys.exit(0 if push_combined() else 1)
    else:
        b, n = build_briefing()
        try:
            print(b)
        except UnicodeEncodeError:
            print(b.encode("utf-8", errors="replace").decode("utf-8"))
        print(f"\n📊 共 {n} 条", file=sys.stderr)

if __name__ == "__main__":
    main()
