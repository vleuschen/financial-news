#!/usr/bin/env python3
"""
Daily News Briefing — GitHub Actions + Server酱.
核心流程：抓取 → 提取全文 → 提炼摘要 → 翻译 → 推送.

Usage:
  python news_briefing.py
  SERVER_CHAN_KEY=xxx python news_briefing.py --push
"""

import io, os, re, sys, time, math, concurrent.futures, urllib.parse, urllib3
from collections import Counter
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

try:
    import trafilatura
    print(f"  ✅ trafilatura {trafilatura.__version__}", file=sys.stderr)
except ImportError:
    trafilatura = None

# ── 36氪前缀清理 ────────────────────────────────────────────────
_36KR_PREFIXES = [
    "36氪Auto", "数字时氪", "未来消费", "智能涌现", "未来城市",
    "启动Power on", "36氪出海", "新经济IPO", "Meta", "风向",
    "To B产业真探", "硬氪", "新能源", "36氪",
]
def clean_title(title, src=""):
    t = (title or "").strip()
    if "36氪" in src:
        for p in _36KR_PREFIXES:
            if t.startswith(p): t = t[len(p):].strip(); break
        t = re.sub(r'^\||\|\s*$', '', t).strip()
    t = re.sub(r'^(首页|\||专题|•|●|·)\s*', '', t).strip()
    return re.sub(r'\s+', ' ', t).strip()

# ── Emoji ──────────────────────────────────────────────────────
TOPIC_EMOJIS = [
    (r"ai|llm|gpt|claude|openai|anthropic|模型|人工智能|大模型|fable|mythos|chatgpt|deepseek|agent|推理", "🤖"),
    (r"spacex|马斯克|musk|starship|卫星|火箭|nasa|发射|太空", "🚀"),
    (r"apple|iphone|ipad|mac|库克|vision|ios|苹果|airpods", "🍎"),
    (r"google|谷歌|deepmind|gemini|android|pixel|alphabet", "🔍"),
    (r"meta|facebook|instagram|whatsapp|扎克伯格|llama", "👓"),
    (r"nvidia|英伟达|gpu|显卡|黄仁勋|cuda|hopper|blackwell", "🖥️"),
    (r"microsoft|windows|azure|纳德拉|copilot|office|微软", "🪟"),
    (r"github|开源|open.source|repository|代码|commit|开发者", "🐙"),
    (r"创业|融资|创投|独角兽|ipo|startup|venture|vc|估值|收购|并购|投资|天使轮", "💎"),
    (r"股市|股票|基金|港股|纳斯达克|道指|标普|a股|上证|深证|证券|牛市|熊市|ipo|ipo|市值", "📈"),
    (r"bitcoin|btc|eth|ethereum|区块链|web3|nft|加密|数字货币|币价|比特币|以太|defi", "₿"),
    (r"芯片|半导体|台积电|tsmc|intel|amd|光刻|晶圆|制程|处理器|骁龙|麒麟|nand", "🔬"),
    (r"数据|隐私|安全|泄露|hack|cyber|黑客|勒索|网络攻击|密码|漏洞", "🔒"),
    (r"5g|6g|通信|华为|中兴|基站|星链|starlink|iot", "📡"),
    (r"石油|原油|能源|天然气|新能源|光伏|风电|储能|电池|碳中和|氢能|核能", "⛽"),
    (r"汽车|ev|电车|特斯拉|tesla|比亚迪|byd|蔚来|小鹏|理想|自动驾驶|智驾", "🚗"),
    (r"机器人|人形|humanoid|机器狗|机械臂|仿生|robotics|宇树", "🦾"),
    (r"quantum|量子|qubit", "⚛️"),
    (r"基因|医疗|药物|疫苗|health|制药|bio|生物|临床|手术|细胞|dna|医院|医生", "🧬"),
    (r"气候|环保|碳排放|全球变暖|厄尔尼诺|极端天气|污染|绿色|排放", "🌍"),
    (r"游戏|gaming|nintendo|sony|playstation|xbox|steam|任天堂|switch|epic|暴雪", "🎮"),
    (r"视频|youtube|tiktok|抖音|b站|bilibili|短视频|直播|流媒体|netflix", "🎬"),
    (r"播客|podcast|lex\s*fridman", "🎙️"),
    (r"中国|北京|上海|中央|国务院|习近平|两会|央行|政策|监管|发改委|商务部|政协|外交|外交部", "🇨🇳"),
    (r"美国|华盛顿|白宫|拜登|trump|特朗普|美联储|fed|硅谷|华尔街|国会|参议院|众议院", "🇺🇸"),
    (r"俄罗斯|putin|普京|莫斯科|俄乌|俄军|克里姆林", "🇷🇺"),
    (r"乌克兰|基辅|泽连斯基|乌军", "🇺🇦"),
    (r"欧洲|eu|欧盟|德国|法国|英国|uk|伦敦|巴黎|柏林|欧元|欧洲央行", "🇪🇺"),
    (r"日本|tokyo|东京|索尼|丰田|日经|日元|软银|三菱|任天堂|岸田|石破", "🇯🇵"),
    (r"韩国|samsung|三星|现代|首尔|韩元|lg|sk|尹锡悦|李在明|msci", "🇰🇷"),
    (r"台湾|tsmc|台积电|联发科|富士康|鸿海|台积", "🇹🇼"),
    (r"香港|hong\s*kong|恒生|港交所", "🇭🇰"),
    (r"伊朗|以色列|巴勒斯坦|哈马斯|真主党|霍尔木兹|中东|沙特|opec|胡塞|也门|黎巴嫩|叙利亚|美伊|以黎", "🌍"),
    (r"战争|军事|导弹|制裁|防御|冲突|北约|国防|军队|武器|航母|战机|核弹|停火|和平|谈判|协议", "⚔️"),
    (r"地震|洪水|台风|灾害|暴雨|飓风|海啸|山火|救援|灾难", "🌊"),
    (r"选举|大选|投票|民调|campaign|竞选|连任|总统|制宪", "🗳️"),
    (r"教育|学校|高考|gaokao|学生|大学|培训|学位|考研|留学|教材|中考|升学|取消", "📚"),
    (r"法律|法规|合规|反垄断|罚款|诉讼|判决|法院|仲裁|法改|宪法|禁令|监管", "⚖️"),
    (r"物价|通胀|cpi|ppi|工资|房价|租金|消费|零售|电商|购物|涨价|降价|养路费|税费", "🏷️"),
    (r"手机|xiaomi|小米|oppo|vivo|荣耀|honor|oneplus|一加|pixel|samsung|galaxy|折叠", "📱"),
    (r"世界杯|足球|篮球|nba|fifa|体育|比赛|联赛|冠军|总决赛|巴伦西亚|傅明|巴西", "⚽"),
    (r"死亡|去世|去世|自杀|谋杀|事故|刑事|犯罪|起诉|诉|庭审", "⚰️"),
]
def get_emoji(title, src=""):
    t = f"{title} {src}".lower()
    for pat, emo in TOPIC_EMOJIS:
        if re.search(pat, t): return emo
    return "📰"

# ── 翻译 ──────────────────────────────────────────────────────
_HAS_CN = re.compile(r'[一-鿿]')
def has_chinese(s):
    return bool(s and _HAS_CN.search(s))

KEEP = [
    "Claude Code", "ChatGPT", "Gemini", "Perplexity", "Midjourney",
    "Stable Diffusion", "Sora", "Mythos", "Fable", "Hacker News",
    "SpaceX", "Tesla", "OpenAI", "Anthropic", "DeepMind", "AlphaFold",
    "Transformer", "RAG", "LoRA", "Agentic", "MCP", "AGI", "ASI",
    "Llama", "Mixtral", "Qwen", "PlayStation", "Xbox", "Nintendo",
    "Spotify", "Netflix", "Uber", "Airbnb", "Python", "JavaScript",
    "TypeScript", "Rust", "Kubernetes", "Docker", "Linux", "GitHub",
    "GitLab", "npm", "PyPI", "iPhone", "iPad", "MacBook",
    "AirPods", "Apple Watch", "Vision Pro", "DALL-E", "SOTA",
    "Bloomberg", "Reuters", "BBC", "CNN", "NYT", "WSJ",
    "AWS", "GCP", "Azure", "Salesforce", "Oracle", "Meta",
    "NVIDIA", "AMD", "Intel", "TSMC", "Samsung",
    "SHA3", "SQL", "EVM", "AOSP",
]

def translate(text):
    if not text or not text.strip() or has_chinese(text):
        return text
    t = text.strip()
    if ' ' not in t and t.isascii() and len(t) > 1:
        return t
    # 保护专有名词
    kmap = {}
    for w in sorted(KEEP, key=len, reverse=True):
        if w.lower() in t.lower():
            ph = f"[K{len(kmap)}]"
            kmap[ph] = w
            t = re.sub(re.escape(w), ph, t, flags=re.IGNORECASE)
    for attempt in range(3):
        try:
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "zh-cn",
                        "dt": "t", "q": t[:3000]},
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

# ── 文章提取 ───────────────────────────────────────────────────
def fetch_body(url):
    """提取文章正文。"""
    if not url or "item?id=" in url or "news.ycombinator.com" in url:
        return ""
    # 方法1: trafilatura
    if trafilatura:
        try:
            dl = trafilatura.fetch_url(url, timeout=12)
            if dl:
                text = trafilatura.extract(dl, include_links=False, include_tables=False) or ""
                if len(text.strip()) >= 100:
                    return text.strip()
        except: pass
    # 方法2: BeautifulSoup 兜底
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        for cls in ["article-body", "post-content", "entry-content", "article-content", "story-body"]:
            area = soup.select_one(f".{cls}") or soup.find(attrs={"class": cls})
            if area:
                ps = [p.get_text(strip=True) for p in area.find_all("p") if len(p.get_text(strip=True)) > 25]
                if ps: return " ".join(ps)
        art = soup.find("article") or soup.find("main")
        if art:
            ps = [p.get_text(strip=True) for p in art.find_all("p") if len(p.get_text(strip=True)) > 25]
            if ps: return " ".join(ps)
    except: pass
    return ""

# ── 摘要算法 ────────────────────────────────────────────────────
# Extractive summarization: 从文章中找最能概括标题的句子

def _split_sentences(text):
    """分割英文句子。"""
    # 按 . ! ? 后跟空格或换行分割
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if len(s.strip()) > 15]

def _split_cn_sentences(text):
    """分割中文句子。"""
    sentences = re.split(r'(?<=[。！？；])', text)
    return [s.strip() for s in sentences if len(s.strip()) > 8]

def _get_keywords(title, body=""):
    """从标题+正文提取关键词（去停用词后频率最高的词）。"""
    combined = (title + " " + body[:300]).lower()
    words = re.findall(r'[a-zA-Z]{3,}', combined)
    # 停用词
    stop = {'the','and','for','that','this','with','have','from','what',
            'when','your','will','they','there','their','about','which',
            'would','could','should','been','more','some','than','then',
            'also','just','like','into','over','after','very','only','most',
            'other','such','each','these','them','does','being','been'}
    words = [w for w in words if w not in stop]
    if not words:
        return set()
    counts = Counter(words)
    # 取频率 > 1 的词
    return {w for w, c in counts.items() if c > 1}

def _score_sentence_en(sentence, keywords):
    """英文句子评分：关键词命中数 / 句子长度。"""
    words = set(re.findall(r'[a-zA-Z]{3,}', sentence.lower()))
    hits = len(words & keywords)
    return hits / max(len(sentence.split()), 1)

def _score_sentence_cn(sentence, title):
    """中文句子评分：跟标题的字符重叠度。"""
    title_chars = set(title)
    sentence_chars = set(sentence)
    overlap = len(title_chars & sentence_chars)
    return overlap / max(len(sentence), 1)

def summarize(text, title="", target_len=60):
    """
    从文章中提炼一句 30-50 字的中文摘要。
    策略:
    1. 翻译全文
    2. 找跟标题最相关的 1-2 句
    3. 合并输出
    """
    if not text or len(text) < 50:
        return ""

    title_cn = translate(title) if not has_chinese(title) else title

    if has_chinese(text):
        # 中文文章：直接找关键词句
        keywords = _get_keywords(title, text)
        sentences = _split_cn_sentences(text)
        if not sentences:
            return _first_sentence(text, target_len)

        # 取前 10 句评分
        scored = [(s, _score_sentence_en(s, keywords)) for s in sentences[:10]]
        scored.sort(key=lambda x: -x[1])

        if scored and scored[0][1] > 0:
            best = scored[0][0][:target_len * 2]
            return _first_sentence(best, target_len)
        return _first_sentence(text, target_len)

    # 英文文章
    keywords = _get_keywords(title, text)
    sentences = _split_sentences(text)
    if not sentences:
        return ""

    # 取前 15 句评分，找最好的 2 句
    candidates = sentences[:15]
    scored = [(s, _score_sentence_en(s, keywords)) for s in candidates]
    scored.sort(key=lambda x: -x[1])

    if not scored or scored[0][1] == 0:
        # 无强相关句 → 取第一段翻译
        return translate(candidates[0][:300])[:target_len] if candidates else ""

    # 取最好的 1-2 句
    top_sentences = [scored[0][0]]
    if len(scored) > 1 and scored[1][1] > scored[0][1] * 0.5:
        top_sentences.append(scored[1][0])

    combined = " ".join(top_sentences)
    cn = translate(combined[:400])
    return _first_sentence(cn, target_len) if cn else ""

def _first_sentence(text, max_len=60):
    if not text: return ""
    text = re.sub(r'\s+', ' ', text).strip()
    for sep in ["。", "！", "？", "；"]:
        idx = text.find(sep)
        if 8 < idx < max_len * 2:
            return text[:idx + 1]
    return text[:max_len] + ("…" if len(text) > max_len else "")

# ── 过滤 ──────────────────────────────────────────────────────
def is_good_item(it):
    title = (it.get("title") or "").strip()
    url = (it.get("url") or "").strip()
    if not title or len(title) < 5: return False
    if url.endswith(".pdf") or "[pdf]" in title.lower(): return False
    # 过滤 Ask/Show/Tell HN
    if re.match(r'^(Ask|Show|Tell|Rate)\s+HN', title, re.IGNORECASE): return False
    # 过滤纯问题（以问号结尾且开头是疑问词）
    if title.endswith("?"):
        q = title.lower()
        if re.match(r'^(what|why|how|when|where|who|is|are|can|do|does|did|will|would|should)\b', q):
            return False
    return True

# ── RSS ──────────────────────────────────────────────────────
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
        except Exception as e:
            if a < 2: time.sleep(1 + a)
    return []

# ── 数据源 ───────────────────────────────────────────────────
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
                    "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""})
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

# ── AI 简讯 ────────────────────────────────────────────────
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

# ── Profiles ────────────────────────────────────────────────
PROFILES = {
    "general": {"emoji": "🌅", "name": "综合早报",
        "sources": [
            (fetch_36kr, 8, None), (fetch_wallstreetcn, 5, None),
            (fetch_hackernews, 7, "AI,LLM,GPT,Claude,Model,Robot,Tech,Apple,Google,Meta,Tesla,SpaceX"),
            (fetch_weibo, 3, None), (fetch_ai_newsletters, 4, None),
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
            (fetch_ai_newsletters, 5, None), (fetch_aihot, 4, None),
            (fetch_tldr, 3, None), (fetch_import_ai, 2, None),
        ]},
}

# ── 核心处理 ────────────────────────────────────────────────
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

def process_item(it):
    """每条新闻 → 一句 30-50 字中文。"""
    title = clean_title(it.get("title", ""), it.get("source", ""))
    src = it.get("source", "")
    summary_raw = it.get("summary", "") or ""
    url = it.get("url", "")

    # 1. 中文快讯 → 标题即新闻
    if src in ("36氪", "华尔街见闻", "腾讯新闻", "微博热搜"):
        return title

    # 2. AIHOT → 中文摘要
    if src == "AIHOT" and has_chinese(summary_raw):
        s = _first_sentence(summary_raw, 60)
        if len(s) >= 15: return s

    # 3. AI 简讯 → RSS描述
    if src in ("Interconnects", "One Useful Thing", "ChinAI", "Memia",
               "AI to ROI", "KDnuggets", "TLDR AI", "Import AI"):
        if summary_raw:
            if has_chinese(summary_raw):
                return _first_sentence(summary_raw, 60)
            cn = translate(summary_raw[:600])
            if cn:
                return _first_sentence(cn, 60)
        return translate(title) if len(title) >= 8 else ""

    # 4. Hacker News → 提取全文 + 摘要算法
    if src == "Hacker News":
        if not has_chinese(title):
            article = fetch_body(url)
            if article and len(article) > 100:
                summary = summarize(article, title)
                if summary and len(summary) >= 15:
                    return summary
        return translate(title) if len(title) >= 8 else ""

    return translate(title) if len(title) >= 8 else ""

def run_profile(key, max_items=15):
    cfg = PROFILES[key]
    all_items = []
    print(f"  [{cfg['name']}] 抓取中...", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(10) as ex:
        fm = {}
        for fn, lm, kw in cfg["sources"]:
            f = ex.submit(fn, lm, kw)
            fm[f] = fn.__name__
        for f in concurrent.futures.as_completed(fm):
            try:
                its = f.result()
                all_items.extend(its)
                print(f"    {fm[f]}: {len(its)}", file=sys.stderr)
            except Exception as e:
                print(f"    {fm[f]}: ERR {e}", file=sys.stderr)

    all_items = [it for it in all_items if is_good_item(it)]
    all_items = dedup(all_items)
    print(f"    → 过滤后: {len(all_items)}", file=sys.stderr)

    results = []
    for it in all_items:
        line = process_item(it)
        if line and len(line) >= 10:
            results.append((it, line))

    print(f"    → 合格: {len(results)}", file=sys.stderr)
    # 打印前 3 条样例
    for i, (it, line) in enumerate(results[:3]):
        print(f"    [{it['source']}] {line[:80]}...", file=sys.stderr)
    return cfg, results[:max_items]

# ── 格式化 ──────────────────────────────────────────────────
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
            lines.append(f"{i}. {get_emoji(it.get('title',''), it.get('source',''))} {nl}")
            lines.append("")
        total += len(items)
    lines.append("─" * 30)
    lines.append(f"📡 HN / 36氪 / 华尔街见闻 / 腾讯 / 微博 / AI Newsletters")
    lines.append(f"🤖 共 {total} 条 · {now.strftime('%H:%M')}")
    lines.append("")
    return "\n".join(lines), total

def push():
    key = os.environ.get("SERVER_CHAN_KEY", "")
    if not key: print("❌ 未设 SERVER_CHAN_KEY", file=sys.stderr); return False
    now = datetime.now()
    title = now.strftime("📬 每日新闻简报 | %Y年%m月%d日")
    print("📡 开始抓取...", file=sys.stderr)
    b, n = build_briefing()
    print(f"📊 共 {n} 条 · 推送中...", file=sys.stderr)
    try:
        r = requests.post(SERVER_CHAN_URL.format(key=key), data={"title": title, "desp": b}, timeout=30)
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
