#!/usr/bin/env python3
"""
Daily News Briefing — GitHub Actions + Server酱.
简洁、诚实：中文源直接用标题，英文源翻译标题。

Usage:
  python news_briefing.py
  SERVER_CHAN_KEY=xxx python news_briefing.py --push
"""

import io, os, re, sys, time, concurrent.futures, urllib.parse, urllib3
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

# ── 36氪标题清理 ──────────────────────────────────────────────
_36K_PREFIX = re.compile(
    r'^(36氪(?:Auto|出海)?|数字时氪|未来消费|智能涌现|未来城市|'
    r'启动Power\s*on|新经济IPO|Meta|风向|To\s?B|硬氪|新能源|36氪)\s*[\|｜]?\s*'
)
def clean_title(t, src=""):
    t = (t or "").strip()
    if "36" in src:
        t = _36K_PREFIX.sub('', t)
    t = re.sub(r'^[\|｜\s•●·]+|[\|｜\s•●·]+$', '', t).strip()
    t = re.sub(r'\s+', ' ', t)
    return t

# ── Emoji ────────────────────────────────────────────────────
EMOJI_PAIRS = [
    (r"人工智能|大模型|claude|gpt|chatgpt|openai|anthropic|fable|mythos|deepseek|agent|llm|模型已|具身", "🤖"),
    (r"spacex|马斯克|starship|火箭|卫星|nasa|发射|太空|飞船", "🚀"),
    (r"苹果|apple|iphone|ipad|mac|库克|airpods|vision|ios", "🍎"),
    (r"谷歌|google|deepmind|gemini|android|pixel|alphabet", "🔍"),
    (r"meta|facebook|instagram|扎克伯格|llama|threads|whatsapp", "👓"),
    (r"英伟达|nvidia|gpu|显卡|黄仁勋|cuda|芯片|半导体|tsmc|intel|amd|光刻|晶圆|处理器", "🖥️"),
    (r"微软|microsoft|windows|azure|纳德拉|copilot|office", "🪟"),
    (r"github|开源|open.source|代码|commit|开发者|repository", "🐙"),
    (r"融资|创投|独角兽|ipo|上市|startup|venture|收购|并购|估值|天使|a轮|b轮", "💎"),
    (r"股票|股市|基金|港股|美股|a股|上证|深证|纳斯达克|道指|标普|牛市|熊市|ipo|涨幅|市值|证券|投资者", "📈"),
    (r"比特币|以太坊|bitcoin|ethereum|区块链|web3|nft|加密|数字货币|defi|币价", "₿"),
    (r"数据|隐私|安全|泄露|黑客|网络攻击|漏洞|勒索|防火墙", "🔒"),
    (r"5g|6g|通信|华为|中兴|基站|星链|starlink|iot|带宽|光纤", "📡"),
    (r"石油|原油|能源|天然气|新能源|光伏|风电|储能|电池|碳中和|氢能|核能|电网|电力", "⛽"),
    (r"汽车|电车|特斯拉|比亚迪|蔚来|小鹏|理想|自动驾驶|智驾|新能源车|燃油车", "🚗"),
    (r"机器人|人形|humanoid|机器狗|机械臂|宇树|robotics", "🦾"),
    (r"量子|quantum|qubit", "⚛️"),
    (r"基因|医疗|药物|疫苗|健康|制药|生物|临床|手术|细胞|dna|医院|诊断", "🧬"),
    (r"气候|环保|碳排放|全球变暖|极端天气|污染|排放|绿色|可持续|巴黎协定", "🌍"),
    (r"游戏|gaming|playstation|xbox|steam|任天堂|switch|epic|暴雪|nintendo", "🎮"),
    (r"youtube|tiktok|抖音|b站|bilibili|短视频|直播|流媒体|netflix|视频", "🎬"),
    (r"播客|podcast|lex\s*fridman", "🎙️"),
    (r"中国|北京|上海|中央|国务院|习近平|两会|央行|发改委|商务部|外交部|政协", "🇨🇳"),
    (r"美国|华盛顿|白宫|拜登|特朗普|trump|美联储|fed|硅谷|华尔街|国会|参议院|众议院", "🇺🇸"),
    (r"俄罗斯|普京|莫斯科|俄乌|俄军|克里姆林|putin", "🇷🇺"),
    (r"乌克兰|基辅|泽连斯基|乌军", "🇺🇦"),
    (r"欧盟|欧洲|德国|法国|英国|伦敦|巴黎|柏林|欧元|欧洲央行|默克尔|冯德莱恩", "🇪🇺"),
    (r"日本|东京|索尼|丰田|日经|日元|软银|任天堂|岸田|石破", "🇯🇵"),
    (r"韩国|三星|现代|首尔|韩元|lg|samsung|尹锡悦|msci", "🇰🇷"),
    (r"台湾|台积电|联发科|富士康|鸿海|tsmc|台积", "🇹🇼"),
    (r"香港|恒生|港交所|hong\s*kong", "🇭🇰"),
    (r"伊朗|以色列|巴勒斯坦|哈马斯|真主党|霍尔木兹|中东|沙特|胡塞|也门|黎巴嫩|叙利亚|美伊|以黎|谈判|协议|停火|制裁|战争|军事|导弹|北约|国防|军队|武器|航母|核弹", "⚔️"),
    (r"地震|洪水|台风|暴雨|飓风|海啸|山火|灾害|救援|灾难", "🌊"),
    (r"选举|大选|投票|民调|竞选|连任|总统|制宪|campaign", "🗳️"),
    (r"教育|学校|高考|中考|学生|大学|培训|学位|考研|留学|教材|升学|取消", "📚"),
    (r"法律|法规|合规|反垄断|罚款|诉讼|判决|法院|仲裁|宪法|禁令|监管|立案", "⚖️"),
    (r"物价|通胀|cpi|ppi|工资|房价|租金|消费|零售|电商|购物|涨价|降价|税费|养路费", "🏷️"),
    (r"手机|小米|oppo|vivo|荣耀|一加|pixel|samsung|galaxy|折叠|xiaomi", "📱"),
    (r"足球|篮球|nba|fifa|世界杯|比赛|联赛|冠军|总决赛|体育|球员|傅明|巴西", "⚽"),
    (r"死亡|去世|自杀|谋杀|事故|刑事|犯罪|起诉|诉|庭审|法院|判决", "⚰️"),
    (r"海平面|冰川|融冰|冰盖|北极|南极|温室|甲烷", "🌊"),
    (r"宇航员|空间站|月球|火星|星际|猎鹰|重型|回收|再入|轨道", "🚀"),
]

def emoji(title, src=""):
    t = f"{title} {src}".lower()
    for pat, em in EMOJI_PAIRS:
        if re.search(pat, t): return em
    return ""

# ── 翻译 ────────────────────────────────────────────────────
_HAS_CN = re.compile(r'[一-鿿]')
def has_chinese(s):
    return bool(s and _HAS_CN.search(s))

KEEP_WORDS = [
    "Claude Code", "ChatGPT", "Gemini", "Perplexity", "Midjourney",
    "Stable Diffusion", "Sora", "Mythos", "Fable", "Hacker News",
    "SpaceX", "Tesla", "OpenAI", "Anthropic", "DeepMind", "AlphaFold",
    "Transformer", "RAG", "LoRA", "Agentic", "MCP", "AGI", "ASI",
    "Llama", "Mixtral", "Qwen", "Bloomberg", "Reuters", "BBC", "CNN",
    "NYT", "WSJ", "PlayStation", "Xbox", "Nintendo", "Spotify", "Netflix",
    "Uber", "Airbnb", "Python", "JavaScript", "TypeScript", "Rust",
    "Kubernetes", "Docker", "Linux", "GitHub", "GitLab", "npm", "PyPI",
    "iPhone", "iPad", "MacBook", "AirPods", "Apple Watch", "Vision Pro",
    "DALL-E", "SOTA", "AWS", "GCP", "Azure", "Salesforce", "Oracle",
    "NVIDIA", "AMD", "Intel", "TSMC", "Samsung", "SHA3-512",
]

def translate(text):
    if not text or not text.strip() or has_chinese(text):
        return text
    t = text.strip()
    if ' ' not in t and t.isascii() and len(t) > 1:
        return t
    kmap = {}
    for i, w in enumerate(sorted(KEEP_WORDS, key=len, reverse=True)):
        if w.lower() in t.lower():
            ph = f"[K{i}]"
            kmap[ph] = w
            t = re.sub(re.escape(w), ph, t, flags=re.IGNORECASE)
    for attempt in range(3):
        try:
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "zh-cn", "dt": "t", "q": t[:3000]},
                timeout=15)
            r.raise_for_status()
            res = "".join(p[0] for p in r.json()[0] if p[0])
            if res:
                for ph, orig in kmap.items():
                    res = res.replace(ph, orig)
                return res
            break
        except:
            if attempt < 2: time.sleep(1)
    return text

# ── 文章提取 ────────────────────────────────────────────────
try:
    import trafilatura
    print(f"  trafilatura {trafilatura.__version__}", file=sys.stderr)
except ImportError:
    trafilatura = None

def fetch_body(url):
    if not url or "item?id=" in url or "news.ycombinator.com" in url:
        return ""
    if trafilatura:
        try:
            dl = trafilatura.fetch_url(url, timeout=12)
            if dl:
                text = trafilatura.extract(dl, include_links=False, include_tables=False) or ""
                if len(text.strip()) >= 100:
                    return text.strip()
        except: pass
    return ""

# ── 过滤 ────────────────────────────────────────────────────
def is_good(it):
    t = (it.get("title") or "").strip()
    u = (it.get("url") or "").strip()
    if not t or len(t) < 5: return False
    if u.endswith(".pdf") or "[pdf]" in t.lower(): return False
    if re.match(r'^(Ask|Show|Tell|Rate)\s+HN', t, re.IGNORECASE): return False
    # 纯疑问句
    if t.endswith("?") and re.match(r'^(What|Why|How|When|Where|Who|Is|Are|Can|Do|Does|Did|Will|Would|Should)\b', t, re.IGNORECASE):
        return False
    return True

# ── RSS ────────────────────────────────────────────────────
def parse_rss(content, src, limit=10):
    items = []
    try:
        soup = BeautifulSoup(content, "lxml")
        for entry in soup.find_all(["item", "entry"])[:limit]:
            tt = entry.find("title")
            if not tt: continue
            title = re.sub(r'^\s*<!\[CDATA\[|\]\]>\s*$', '', tt.get_text(strip=True)).strip()
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
                raw = re.sub(r'^\s*<!\[CDATA\[|\]\]>\s*$', '', desc.get_text()).strip()
                summary = BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)[:800]
            items.append({"source": src, "title": title, "url": link, "time": ts, "summary": summary})
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
        except Exception:
            if a < 2: time.sleep(1 + a)
    return []

# ── 数据源 ─────────────────────────────────────────────────
def fetch_hackernews(limit=5, keyword=None):
    items = []
    if keyword:
        try:
            ts = int(time.time() - 24 * 3600)
            kws = [k.strip() for k in keyword.split(",")]
            quoted = [f'"{k}"' if " " in k else k for k in kws]
            q = " OR ".join(quoted)
            hits = requests.get(
                f"https://hn.algolia.com/api/v1/search_by_date"
                f"?tags=story&numericFilters=created_at_i>{ts}"
                f"&hitsPerPage={limit * 2}&query={urllib.parse.quote(q)}",
                timeout=10).json().get("hits", [])
            if not hits and kws:
                hits = requests.get(
                    f"https://hn.algolia.com/api/v1/search_by_date"
                    f"?tags=story&numericFilters=created_at_i>{ts}"
                    f"&hitsPerPage={limit * 2}&query={urllib.parse.quote(kws[0])}",
                    timeout=10).json().get("hits", [])
            for h in hits:
                items.append({"source": "Hacker News", "title": h.get("title", ""),
                    "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                    "points": h.get("points", 0), "time": "Today"})
            if items: return items[:limit]
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
            href = te.get("href", "")
            if href and not href.startswith("http"): href = "https://36kr.com" + href
            tm = el.select_one(".time")
            items.append({"source": "36氪", "title": te.get_text(strip=True),
                "url": href, "time": tm.get_text(strip=True) if tm else ""})
        if keyword:
            items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [36Kr] {e}", file=sys.stderr)
    return items[:limit]

def fetch_wallstreetcn(limit=5, keyword=None):
    items = []
    try:
        data = requests.get(
            "https://api-one.wallstcn.com/apiv1/content/information-flow?"
            "channel=global-channel&accept=article&limit=30", timeout=10).json()
        for item in data.get("data", {}).get("items", []):
            res = item.get("resource")
            if res and (res.get("title") or res.get("content_short")):
                ts = res.get("display_time", 0)
                items.append({"source": "华尔街见闻",
                    "title": res.get("title") or res.get("content_short"),
                    "url": res.get("uri", ""),
                    "time": datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else ""})
        if keyword:
            items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
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
        if keyword:
            items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
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
            items.append({"source": "微博热搜", "title": title, "heat": str(item.get("num", 0)),
                "time": "Real-time"})
        if keyword:
            items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [Weibo] {e}", file=sys.stderr)
    return items[:limit]

# ── AI ─────────────────────────────────────────────────────
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
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        fs = {ex.submit(fetch_rss, u, n, max(1, limit // 2)): n for n, u in AI_FEEDS}
        for f in concurrent.futures.as_completed(fs):
            all_items.extend(f.result())
    if keyword:
        all_items = [it for it in all_items
                     if any(k.lower() in it["title"].lower() for k in keyword.split(",") if k.strip())]
    return all_items[:limit]

def fetch_tldr(limit=3, keyword=None):
    items = fetch_rss("https://tldr.tech/api/rss/ai", "TLDR AI", limit * 2)
    return [it for it in items if _recent(it.get("time", ""), 48)][:limit]

def fetch_import_ai(limit=2, keyword=None):
    items = fetch_rss("https://importai.substack.com/feed", "Import AI", limit * 2)
    return [it for it in items if _recent(it.get("time", ""), 168)][:limit]

def fetch_aihot(limit=5, keyword=None):
    items = fetch_rss("https://aihot.virxact.com/rss", "AIHOT", limit * 2)
    return [it for it in items if _recent(it.get("time", ""), 24)][:limit]

def _recent(ts, hours):
    if not ts: return True
    try:
        pub = parsedate_to_datetime(str(ts))
        if pub.tzinfo is None: pub = pub.replace(tzinfo=timezone.utc)
        return pub >= (datetime.now(timezone.utc) - timedelta(hours=hours))
    except: return True

# ── Profiles ──────────────────────────────────────────────
PROFILES = {
    "general": {"emoji": "🌅", "name": "综合早报",
        "sources": [
            (fetch_36kr, 8), (fetch_wallstreetcn, 5),
            (fetch_hackernews, 7, "AI,LLM,GPT,Claude,Model,Robot,Tech,Apple,Google,Meta,Tesla,SpaceX"),
            (fetch_weibo, 3),
            (fetch_ai_newsletters, 4),
        ]},
    "finance": {"emoji": "💰", "name": "财经早报",
        "sources": [
            (fetch_wallstreetcn, 8),
            (fetch_36kr, 6, "财报,营收,上市,IPO,投资,基金,股市,经济"),
            (fetch_tencent, 4, "财经,股票,基金,市场,经济,金融"),
            (fetch_hackernews, 4, "Economy,Inflation,Fed,Stock,Finance,Bank,Market,Invest"),
        ]},
    "tech": {"emoji": "🤖", "name": "科技早报",
        "sources": [
            (fetch_hackernews, 6, "AI,LLM,GPT,Claude,Model,Robot,Tech,Apple,Google,Meta,Microsoft,Chip,Startup"),
            (fetch_36kr, 4, "融资,首发,独角兽,创投,科技,AI,人工智能"),
            (fetch_ai_newsletters, 5),
            (fetch_aihot, 4),
            (fetch_tldr, 3),
            (fetch_import_ai, 2),
        ]},
}

# ── 核心 ──────────────────────────────────────────────────
def dedup(items):
    seen_u, seen_t, result = set(), set(), []
    for it in items:
        u = (it.get("url") or "").strip()
        t = (it.get("title") or "").strip()
        if (u and u in seen_u) or (t and t in seen_t): continue
        if u: seen_u.add(u)
        if t: seen_t.add(t)
        result.append(it)
    return result

def _clean_html(raw):
    if not raw: return ""
    return BeautifulSoup(raw, "lxml").get_text(separator=" ", strip=True)[:600]

def _first_cn_sentence(text):
    """取第一句有实质内容的中文句子。"""
    if not text: return ""
    text = re.sub(r'\s+', ' ', text).strip()
    # 按段落取，跳过导航段
    for sep in ["\n\n", "\n"]:
        if sep in text:
            paragraphs = [p.strip() for p in text.split(sep) if len(p.strip()) > 20]
            if paragraphs:
                text = paragraphs[0]
                break
    # 取第一句
    for sep in ["。", "！", "？", "；"]:
        idx = text.find(sep)
        if 8 < idx < 150:
            return text[:idx + 1]
    return text[:100] if len(text) > 20 else text

def process(it):
    """新闻条目处理。策略：中文标题即为新闻句，英文标题翻译。"""
    title = clean_title(it.get("title", ""), it.get("source", ""))
    src = it.get("source", "")
    summary = it.get("summary", "") or ""

    # 1. 中文快讯 → 标题就是完整新闻
    if src in ("36氪", "华尔街见闻", "腾讯新闻", "微博热搜"):
        return title

    # 2. AIHOT 有中文编辑稿
    if src == "AIHOT" and summary and has_chinese(summary):
        s = _first_cn_sentence(summary)
        if s: return s

    # 3. Hacker News
    if src == "Hacker News":
        cn = translate(title)
        # 只对高质量文章源尝试提取正文增强摘要
        # 判断标准：URL 是新闻站点（reuters/bbc/bloomberg/nature/science 等）
        url = it.get("url", "")
        if url and any(n in url for n in ["reuters.com", "bbc.com", "bloomberg.com",
            "nature.com", "science.org", "techcrunch.com", "theverge.com",
            "arstechnica.com", "wired.com", "wsj.com", "economist.com"]):
            body = fetch_body(url)
            if body and len(body) > 150:
                body_cn = translate(body[:600])
                if body_cn and len(body_cn) > 40:
                    s = _first_cn_sentence(body_cn)
                    if s and len(s) > 15:
                        return f"{cn}：{s}"
        return cn if len(cn) >= 8 else ""

    # 4. AI 简讯
    if summary:
        if has_chinese(summary):
            s = _first_cn_sentence(summary)
            if s: return s
        cn = translate(summary[:600])
        if cn and cn != summary[:600]:
            s = _first_cn_sentence(cn)
            if s: return s
    return translate(title) if len(title) >= 8 else ""

def run_profile(key, max_items=15):
    cfg = PROFILES[key]
    all_items = []
    print(f"  [{cfg['name']}] 抓取中...", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(10) as ex:
        fm = {}
        for entry in cfg["sources"]:
            fn = entry[0]; lm = entry[1]; kw = entry[2] if len(entry) > 2 else None
            f = ex.submit(fn, lm, kw)
            fm[f] = fn.__name__
        for f in concurrent.futures.as_completed(fm):
            try:
                its = f.result()
                all_items.extend(its)
                print(f"    {fm[f]}: {len(its)}", file=sys.stderr)
            except Exception as e:
                print(f"    {fm[f]}: ERR {e}", file=sys.stderr)

    all_items = [it for it in all_items if is_good(it)]
    all_items = dedup(all_items)
    print(f"    → {len(all_items)} 条", file=sys.stderr)

    results = []
    for it in all_items:
        line = process(it)
        if line and len(line) >= 10:
            results.append((it, line))

    print(f"    → 合格 {len(results)} 条", file=sys.stderr)
    return cfg, results[:max_items]

# ── 格式化 ────────────────────────────────────────────────
def build_briefing():
    now = datetime.now()
    lines = [now.strftime("%Y年%m月%d日") + " " + WEEKDAYS[now.weekday()], ""]
    total = 0
    for pk in ["general", "finance", "tech"]:
        cfg, items = run_profile(pk, 15)
        if not items: continue
        lines.append(f"{cfg['emoji']} **{cfg['name']}** · 共 {len(items)} 条")
        lines.append("")
        for i, (it, nl) in enumerate(items, 1):
            em = emoji(it.get("title", ""), it.get("source", ""))
            lines.append(f"{i}. {em}{nl}" if em else f"{i}. {nl}")
            lines.append("")
        total += len(items)
    lines.append("─" * 30)
    lines.append(f"📡 HN / 36氪 / 华尔街见闻 / 腾讯 / 微博 / AI Newsletters")
    lines.append(f"🤖 共 {total} 条 · {now.strftime('%H:%M')}")
    lines.append("")
    return "\n".join(lines), total

def push():
    key = os.environ.get("SERVER_CHAN_KEY", "")
    if not key: print("❌ SERVER_CHAN_KEY", file=sys.stderr); return False
    now = datetime.now()
    print("📡 抓取中...", file=sys.stderr)
    b, n = build_briefing()
    print(f"📊 {n} 条 → 推送...", file=sys.stderr)
    try:
        r = requests.post(SERVER_CHAN_URL.format(key=key), data={"title": now.strftime("📬 每日新闻简报 | %Y年%m月%d日"), "desp": b}, timeout=30)
        res = r.json()
        if r.status_code == 200 and res.get("code") == 0:
            print(f"✅ {res.get('message', 'OK')}", file=sys.stderr); return True
        print(f"❌ {res}", file=sys.stderr); return False
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr); return False

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    args = ap.parse_args()
    if args.push:
        sys.exit(0 if push() else 1)
    else:
        b, n = build_briefing()
        try: print(b)
        except: print(b.encode("utf-8", errors="replace").decode("utf-8"))
        print(f"\n📊 共 {n} 条", file=sys.stderr)

if __name__ == "__main__":
    main()
