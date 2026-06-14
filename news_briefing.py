#!/usr/bin/env python3
"""
Daily News Briefing — standalone script for GitHub Actions + Server酱 (ServerChan).

Usage:
  python news_briefing.py              # 本地测试
  SERVER_CHAN_KEY=xxx python news_briefing.py --push  # 推送微信

Requirements: pip install requests beautifulsoup4 lxml
"""

import io, json, os, re, sys, time
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

# ── Constants ──────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}
SERVER_CHAN_URL = os.environ.get("SERVER_CHAN_URL", "https://sctapi.ftqq.com/{key}.send")
WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# 36氪标题前缀垃圾词黑名单 — 开头的统统砍掉
_36KR_PREFIXES = [
    "36氪Auto", "数字时氪", "未来消费", "智能涌现", "未来城市",
    "启动Power on", "36氪出海", "36氪", "新经济IPO", "Meta",
    "风向", "To B产业真探", "硬氪", "新能源",
]


def clean_title(title, source=""):
    """清洗标题：砍频道前缀、去导航关键词、去多余空格。"""
    if not title:
        return ""
    t = title.strip()
    # 砍 36kr 频道前缀
    if "36氪" in source or "36kr" in source:
        for p in _36KR_PREFIXES:
            if t.startswith(p):
                t = t[len(p):].strip()
                break
        t = re.sub(r'^\||\|\s*$', '', t).strip()

    # 去掉开头结尾的垃圾词
    t = re.sub(r'^(首页|\||专题|•|●|·)\s*', '', t).strip()
    t = re.sub(r'\s*\|\s*$', '', t).strip()
    # 多个空格归一
    t = re.sub(r'\s+', ' ', t)
    return t


# ── Emoji ──────────────────────────────────────────────────────────────────

TOPIC_EMOJIS = [
    (r"ai|llm|gpt|claude|openai|anthropic|模型|人工智能|大模型|fable|mythos|chatgpt|deepseek|agent", "🤖"),
    (r"spacex|space|太空|马斯克|musk|starship|龙飞船|卫星|火箭|nasa|space", "🚀"),
    (r"apple|iphone|mac|ipad|vision|库克|airpods|watch|ios", "🍎"),
    (r"google|alphabet|pixel|谷歌|deepmind|gemini|gmail|chrome|android", "🔍"),
    (r"meta|facebook|instagram|whatsapp|threads|扎克伯格|llama", "👓"),
    (r"nvidia|英伟达|gpu|显卡|黄仁勋|cuda|hopper|blackwell|rtx", "🖥️"),
    (r"microsoft|windows|azure|surface|纳德拉|msft|office|teams|copilot", "🪟"),
    (r"github|git|代码|开源|open.source|repository|仓库|commit|pr|developer", "🐙"),
    (r"创业|融资|创投|独角兽|ipo|天使轮|a轮|b轮|startup|venture|投资机构|vc|pe", "💎"),
    (r"股票|股市|基金|投资|a股|港股|纳斯达克|道指|标普|沪深|上证|深证|证券|牛市|熊市|散户", "📈"),
    (r"bitcoin|btc|eth|ethereum|区块链|web3|nft|defi|加密|数字货币|币价|比特币|以太坊", "₿"),
    (r"芯片|半导体|台积电|tsmc|intel|amd|光刻|晶圆|制程|chip|processor|骁龙|麒麟", "🔬"),
    (r"数据|隐私|安全|泄露|hack|cyber|黑客|勒索|网络攻击|密码|防火墙|加密", "🔒"),
    (r"5g|6g|通信|华为|中兴|基站|网络|带宽|光纤|物联网|iot|starlink", "📡"),
    (r"石油|原油|能源|天然气|gas|新能源|光伏|风电|储能|电池|碳中和|green|氢能", "⛽"),
    (r"汽车|ev|电车|特斯拉|tesla|比亚迪|byd|蔚来|小鹏|理想|自动驾驶|智驾|新能源车|燃油车", "🚗"),
    (r"机器人|人形|humanoid|机器狗|机械臂|仿生|robotics|automation|宇树", "🦾"),
    (r"quantum|量子|比特|qubit", "⚛️"),
    (r"基因|医疗|药物|疫苗|health|健康|制药|bio|生物|临床试验|手术|诊断", "🧬"),
    (r"气候|环保|碳排放|全球变暖|厄尔尼诺|极端天气|污染|绿色|可持续|巴黎协定", "🌍"),
    (r"游戏|gaming|nintendo|sony|playstation|xbox|steam|任天堂|switch|epic|暴雪", "🎮"),
    (r"视频|youtube|tiktok|抖音|b站|bilibili|短视频|直播|流媒体|netflix|disney", "🎬"),
    (r"播客|podcast|lex|fridman|latent.space|这集听了", "🎙️"),
    (r"中国|北京|上海|中央|国务院|习近平|两会|央行|政策|监管|法规|发改委|商务部", "🇨🇳"),
    (r"美国|华盛顿|白宫|拜登|trump|特朗普|美联储|fed|硅谷|华尔街|参议院|众议院", "🇺🇸"),
    (r"俄罗斯|putin|普京|莫斯科|俄乌|俄罗斯|俄军", "🇷🇺"),
    (r"乌克兰|基辅|泽连斯基|乌军|乌方", "🇺🇦"),
    (r"欧洲|eu|欧盟|德国|法国|英国|uk|伦敦|巴黎|柏林|脱欧|欧元|欧洲央行", "🇪🇺"),
    (r"日本|tokyo|东京|索尼|丰田|日经|日元|日本央行|软银|三菱", "🇯🇵"),
    (r"韩国|samsung|三星|现代|首尔|韩元|lg|sk", "🇰🇷"),
    (r"台湾|tsmc|台积电|联发科|富士康|鸿海|台积", "🇹🇼"),
    (r"香港|hong.kong|恒生|港股|港交所|香港", "🇭🇰"),
    (r"伊朗|以色列|巴勒斯坦|哈马斯|真主党|霍尔木兹|中东|沙特|石油输出国|opec|胡塞", "🌍"),
    (r"战争|军事|导弹|制裁|防御|冲突|北约|国防|军队|武器|航母|战机", "⚔️"),
    (r"地震|洪水|台风|灾害|暴雨|飓风|海啸|山火", "🌊"),
    (r"选举|大选|投票|民调|campaign|竞选|连任", "🗳️"),
    (r"教育|学校|高考|gaokao|学生|大学|培训|学位|考研|留学|教材", "📚"),
    (r"法律|法规|监管|合规|反垄断|罚款|诉讼|立法|政策|判决|法院|仲裁|立案", "⚖️"),
    (r"物价|通胀|cpi|ppi|工资|房价|租金|消费|零售|电商|购物|双11|618", "🏷️"),
    (r"产品|发布|launch|新品|beta|测试版|producthunt|product.hunt|上新", "🆕"),
    (r"新闻|资讯|报道|日报|周刊|newsletter|tldr|import.ai|aihot|简报", "📨"),
    (r"手机|xiaomi|小米|oppo|vivo|荣耀|honor|oneplus|一加|pixel|samsung", "📱"),
]


def get_emoji(title, source=""):
    t = f"{title} {source}".lower()
    for pat, emo in TOPIC_EMOJIS:
        if re.search(pat, t):
            return emo
    return "📰"


# ── Translation ────────────────────────────────────────────────────────────

_HAS_CN = re.compile(r'[一-鿿㐀-䶿\U00020000-\U0002a6df]')
# 不要翻译的专有名词（大小写不敏感，自动忽略空格）
_KEEP_EN = re.compile(
    r'\b(?:Claude Code|Claude|Codex|Cursor|GitHub Copilot|ChatGPT|Gemini|Perplexity|'
    r'Midjourney|Stable Diffusion|Sora|Mythos|Fable|Hacker News|Product Hunt|'
    r'Reddit|SpaceX|Tesla|OpenAI|Anthropic|DeepMind|AlphaFold|'
    r'Transformer|RAG|LoRA|Agentic|MCP|A2A|AGI|ASI|'
    r'Llama|Mixtral|Qwen|Bloomberg|Reuters|BBC|CNN|NYT|WSJ|WaPo|'
    r'PlayStation|Xbox|Nintendo|Spotify|Netflix|Uber|Airbnb|'
    r'Python|JavaScript|TypeScript|Rust|Kubernetes|Docker|Linux|'
    r'GitHub|GitLab|BitBucket|npm|PyPI|'
    r'iPhone|iPad|MacBook|AirPods|Apple Watch|Vision Pro|'
    r'ChatGPT|Claude|Gemini|Copilot|DALL-E|Sora)\b',
    re.IGNORECASE
)


def has_chinese(text):
    return bool(_HAS_CN.search(text))


def _restore_keep_words(text, keep_map):
    """Translate后把被翻译了的专有名词恢复回来。"""
    for orig, placeholder in keep_map.items():
        text = text.replace(placeholder, orig)
    return text


def translate_to_cn(text):
    """英译中，保持专有名词不翻译。"""
    if not text or not text.strip() or has_chinese(text):
        return text
    t = text.strip()
    # 纯单个英文词（无空格无中文）→ 大概率是专有名词，不翻译
    if ' ' not in t and t.isascii() and len(t) > 1:
        return t

    # 保护专有名词：用 __K0__ __K1__ 等安全占位符，URL编码和翻译都不会破坏
    keep_map = {}  # placeholder -> original
    reverse_map = {}  # original -> placeholder
    for m in _KEEP_EN.finditer(t):
        orig = m.group(0)
        if orig in reverse_map:
            continue  # 已经替换过
        placeholder = f"__K{len(keep_map)}__"
        keep_map[placeholder] = orig
        reverse_map[orig] = placeholder

    # 替换原文中的专有名词
    for orig, placeholder in sorted(reverse_map.items(), key=lambda x: -len(x[0])):
        t = t.replace(orig, placeholder)

    # 调用 Google Translate
    for attempt in range(3):
        try:
            url = "https://translate.googleapis.com/translate_a/single"
            params = {"client": "gtx", "sl": "auto", "tl": "zh-cn", "dt": "t",
                      "q": t[:3000]}
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            result = r.json()
            translated = "".join(p[0] for p in result[0] if p[0])
            if translated:
                # 恢复专有名词
                for placeholder, orig in keep_map.items():
                    translated = translated.replace(placeholder, orig)
                return translated
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
                continue
            print(f"  ⚠️ 翻译失败: {e}", file=sys.stderr)
    return text  # fallback


def batch_translate(texts):
    """批量翻译，按 <||> 分隔合并发一次请求。"""
    idxs = [i for i, t in enumerate(texts) if t and not has_chinese(t)]
    if not idxs:
        return texts
    english = [texts[i] for i in idxs]
    combined = "\n<||>\n".join(english)
    result = list(texts)
    translated = translate_to_cn(combined)
    if translated and translated != combined:
        parts = translated.split("\n<||>\n")
        for i, p in zip(idxs, parts):
            p = p.strip()
            if p and i < len(result):
                result[i] = p
    return result


# ── Content Fetching & Summarization ───────────────────────────────────────


def fetch_url(url, max_chars=2000):
    """抓取网页正文，提取干净文本。"""
    if not url or not url.startswith("http"):
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                         ".sidebar", ".nav", ".menu", ".footer", ".header"]):
            tag.decompose()
        # 找 article / main 区域
        main = soup.find("article") or soup.find("main") or soup.find(".post-content") or soup
        text = main.get_text(separator=" ", strip=True) if hasattr(main, 'get_text') else soup.get_text(separator=" ", strip=True)
        text = re.sub(r'\s+', ' ', text).strip()
        # 过滤纯导航文本
        nav_words = ["登录", "注册", "搜索", "账号设置", "我的关注", "我的收藏", "退出",
                     "首页", "关于我们", "联系我们", "广告合作", "免责声明", "用户协议",
                     "隐私政策", "Copyright", "All rights reserved"]
        for w in nav_words:
            text = text.replace(w, "")
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_chars]
    except Exception:
        return ""


# ── Filters ────────────────────────────────────────────────────────────────

_BAD_TITLE_RE = re.compile(
    r"^(登录|注册|账号|设置|我的关注|我的收藏|退出|首页|"
    r"搜索|关于我们|联系我们|广告|免责|协议|隐私|"
    r"Copyright|All rights reserved|This page|404|302|Redirect|"
    r"Subscribe|Sign in|Sign up|Skip to|Comment|Loader|Save Story)",
    re.IGNORECASE
)

# 不是新闻的内容模式
_NOT_NEWS_RE = re.compile(
    r"^(%PDF-|%PNG|GIF8|PK\x03\x04|MZ\x90)",  # 二进制文件头
    re.IGNORECASE
)

# GitHub 仓库描述不是新闻——纯开源项目列表
_GITHUB_DESC_RE = re.compile(
    r"^(A collection of|Collection of|An alternative to|"
    r"An open.source|Open.source|An opinionated|"
    r"List of|A list of|The best|Awesome )",
    re.IGNORECASE
)


def is_good_item(item):
    """过滤垃圾条目：导航文字、太短、无意义、二进制内容。"""
    title = item.get("title", "").strip()
    if not title or len(title) < 5:
        return False
    if _BAD_TITLE_RE.match(title):
        return False
    if re.match(r'^https?://', title):
        return False
    if _NOT_NEWS_RE.match(title):
        return False

    src = item.get("source", "")

    # GitHub Trending 的仓库描述不算新闻，必须有实质内容
    if "GitHub" in src:
        # 纯仓库描述：如 "iptv-org/iptv — Collection of ..."
        if " — " in title:
            parts = title.split(" — ", 1)
            repo_name = parts[0].strip()
            desc = parts[1].strip()
            # 如果描述是"Collection of...", "An alternative to..." 这类模板 → 过滤
            if _GITHUB_DESC_RE.match(desc):
                return False
            # 只有仓库名没有实际新闻内容
            if desc and " " in desc and len(desc) < 15:
                return False
        # 纯仓库名（无描述）→ 过滤
        elif "/" in title and len(title) < 30:
            return False

    # 产品名单独出现（无上下文）→ Product Hunt 的纯产品名
    if "Product Hunt" in src and " " not in title and len(title) < 20:
        return False

    # 中文标题太短而且没有标点说明
    if has_chinese(title) and len(title) < 8 and "，" not in title and "：" not in title:
        return False

    return True


# ── Helpers ────────────────────────────────────────────────────────────────

def filter_keyword(items, kw):
    if not kw:
        return items
    kws = [k.strip() for k in kw.split(",") if k.strip()]
    if not kws:
        return items
    pat = "|".join(re.escape(k) for k in kws)
    return [it for it in items if re.search(rf'(?i)({pat})', it.get("title", ""))]


def filter_hours(items, hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    kept = []
    for it in items:
        t = it.get("time", "")
        try:
            pub = parsedate_to_datetime(str(t))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub >= cutoff:
                kept.append(it)
        except:
            kept.append(it)
    return kept


def dedup(items):
    seen_url, seen_title, result = set(), set(), []
    for it in items:
        u, t = it.get("url", "") or "", it.get("title", "") or ""
        if u and u in seen_url:
            continue
        if t and t in seen_title:
            continue
        if u:
            seen_url.add(u)
        if t:
            seen_title.add(t)
        result.append(it)
    return result


# ── RSS Parser ─────────────────────────────────────────────────────────────

def parse_rss(content, src, limit=10):
    items = []
    try:
        soup = BeautifulSoup(content, "html.parser")
        for entry in soup.find_all(["item", "entry"]):
            tag = entry.find("title")
            if not tag:
                continue
            title = tag.get_text(strip=True)
            if not title:
                continue
            title = re.sub(r'^\s*<!\[CDATA\[|\]\]>\s*$', '', title).strip()
            if not title:
                continue
            link = ""
            lt = entry.find("link")
            if lt:
                if lt.has_attr("href"):
                    link = lt["href"]
                elif lt.get_text(strip=True):
                    link = lt.get_text(strip=True)
            if not link:
                g = entry.find("guid")
                if g and g.get_text(strip=True).startswith("http"):
                    link = g.get_text(strip=True)
            pub = entry.find(["pubdate", "published", "updated", "dc:date"])
            ts = pub.get_text(strip=True) if pub else ""
            desc = entry.find("description") or entry.find("summary")
            summary = ""
            if desc:
                raw = desc.get_text()
                raw = re.sub(r'^\s*<!\[CDATA\[|\]\]>\s*$', '', raw).strip()
                summary = BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)[:800]
            items.append({"source": src, "title": title, "url": link,
                          "time": ts, "summary": summary})
            if len(items) >= limit:
                break
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
            if a < 2:
                time.sleep(1 + a)
            else:
                print(f"  [RSS] {url}: {e}", file=sys.stderr)
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
                items.append({"source": "Hacker News",
                              "title": h.get("title", ""),
                              "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                              "heat": f"{h.get('points', 0)}", "time": "Today"})
            if items:
                return items[:limit]
        except Exception as e:
            print(f"  [HN] {e}", file=sys.stderr)
    try:
        soup = BeautifulSoup(requests.get("https://news.ycombinator.com/news", headers=HEADERS, timeout=10).text, "html.parser")
        for row in soup.select(".athing"):
            tl = row.select_one(".titleline a")
            if not tl:
                continue
            title = tl.get_text()
            link = tl.get("href")
            if link and link.startswith("item?id="):
                link = f"https://news.ycombinator.com/{link}"
            items.append({"source": "Hacker News", "title": title, "url": link, "heat": "", "time": "Today"})
        if keyword:
            items = filter_keyword(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [HN] {e}", file=sys.stderr)
    return items[:limit]


def fetch_github(limit=5, keyword=None):
    items = []
    try:
        soup = BeautifulSoup(requests.get("https://github.com/trending", headers=HEADERS, timeout=10).text, "html.parser")
        for art in soup.select("article.Box-row"):
            h2 = art.select_one("h2 a")
            if not h2:
                continue
            title = h2.get_text(strip=True).replace("\n", "").replace(" ", "")
            href = "https://github.com" + h2["href"]
            desc = art.select_one("p")
            desc_text = desc.get_text(strip=True) if desc else ""
            stars = art.select_one('a[href$="/stargazers"]')
            star_str = stars.get_text(strip=True) if stars else ""
            items.append({"source": "GitHub Trending",
                          "title": f"{title} — {desc_text}" if desc_text else title,
                          "url": href, "heat": f"{star_str} stars", "time": "Today"})
        if keyword:
            items = filter_keyword(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [GitHub] {e}", file=sys.stderr)
    return items[:limit]


def fetch_36kr(limit=5, keyword=None):
    items = []
    try:
        soup = BeautifulSoup(requests.get("https://36kr.com/newsflashes", headers=HEADERS, timeout=10).text, "html.parser")
        for el in soup.select(".newsflash-item"):
            te = el.select_one(".item-title")
            if not te:
                continue
            title = te.get_text(strip=True)
            href = te.get("href", "")
            if href and not href.startswith("http"):
                href = "https://36kr.com" + href
            tm = el.select_one(".time")
            ts = tm.get_text(strip=True) if tm else ""
            items.append({"source": "36氪", "title": title, "url": href, "time": ts, "heat": ""})
        if keyword:
            items = filter_keyword(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [36Kr] {e}", file=sys.stderr)
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
                          "time": n.get("pub_time", "") or n.get("publish_time", ""), "heat": ""})
        if keyword:
            items = filter_keyword(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [QQ] {e}", file=sys.stderr)
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
                time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else ""
                items.append({"source": "华尔街见闻",
                              "title": res.get("title") or res.get("content_short"),
                              "url": res.get("uri", ""), "time": time_str, "heat": ""})
        if keyword:
            items = filter_keyword(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [WSCN] {e}", file=sys.stderr)
    return items[:limit]


def fetch_producthunt(limit=5, keyword=None):
    items = fetch_rss("https://www.producthunt.com/feed", "Product Hunt", limit * 2)
    for it in items:
        it["heat"] = "Trending"
    if keyword:
        items = filter_keyword(items, keyword)
    return items[:limit]


def fetch_weibo(limit=5, keyword=None):
    items = []
    try:
        raw = requests.get("https://weibo.com/ajax/side/hotSearch", headers={
            "User-Agent": HEADERS["User-Agent"], "Referer": "https://weibo.com/"}, timeout=10).json()
        for item in raw.get("data", {}).get("realtime", []):
            title = item.get("note", "") or item.get("word", "")
            if not title:
                continue
            items.append({"source": "微博热搜", "title": title,
                          "url": f"https://s.weibo.com/weibo?q={urllib.parse.quote(title)}&Refer=top",
                          "heat": str(item.get("num", 0)), "time": "Real-time"})
        if keyword:
            items = filter_keyword(items, keyword)
        return items[:limit]
    except Exception as e:
        print(f"  [Weibo] {e}", file=sys.stderr)
    return items[:limit]


# ── AI / Newsletter Sources ────────────────────────────────────────────────

AI_FEEDS = [
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
    per = max(1, limit // 2)
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        fs = {ex.submit(fetch_rss, u, n, per): n for n, u in AI_FEEDS}
        for f in concurrent.futures.as_completed(fs):
            all_items.extend(f.result())
    if keyword:
        all_items = filter_keyword(all_items, keyword)
    return all_items[:limit]


def fetch_tldr(limit=3, keyword=None):
    items = fetch_rss("https://tldr.tech/api/rss/ai", "TLDR AI", limit * 2)
    items = filter_hours(items, 48)
    if keyword:
        items = filter_keyword(items, keyword)
    return items[:limit]


def fetch_import_ai(limit=2, keyword=None):
    items = fetch_rss("https://importai.substack.com/feed", "Import AI", limit * 2)
    items = filter_hours(items, 168)
    if keyword:
        items = filter_keyword(items, keyword)
    return items[:limit]


def fetch_aihot(limit=5, keyword=None):
    items = fetch_rss("https://aihot.virxact.com/rss", "AIHOT", limit * 2)
    items = filter_hours(items, 24)
    if keyword:
        items = filter_keyword(items, keyword)
    return items[:limit]


# ── Profiles ───────────────────────────────────────────────────────────────

PROFILES = {
    "general": {
        "emoji": "🌅", "name": "综合早报",
        "sources": [
            (fetch_hackernews, 6, None), (fetch_36kr, 5, None),
            (fetch_github, 3, None), (fetch_wallstreetcn, 3, None),
            (fetch_producthunt, 2, None), (fetch_weibo, 2, None),
        ],
    },
    "finance": {
        "emoji": "💰", "name": "财经早报",
        "sources": [
            (fetch_wallstreetcn, 8, None),
            (fetch_36kr, 5, "财报,营收,上市,IPO,投资,基金,股市"),
            (fetch_tencent, 3, "财经,股票,基金,市场,经济"),
            (fetch_hackernews, 3, "Economy,Inflation,Fed,Stock,Finance,Bank,Market"),
        ],
    },
    "tech": {
        "emoji": "🤖", "name": "科技早报",
        "sources": [
            (fetch_hackernews, 5, "AI,LLM,GPT,Claude,Model,Robot,Startup,Tech,Apple,Google,Meta,Microsoft"),
            (fetch_github, 4, None), (fetch_producthunt, 3, "Developer Tools,Coding,API,AI,Tech"),
            (fetch_36kr, 2, "融资,首发,独角兽,创投,科技"),
            (fetch_ai_newsletters, 4, None), (fetch_aihot, 3, None),
            (fetch_tldr, 3, None), (fetch_import_ai, 1, None),
        ],
    },
}


# ── Pipeline ───────────────────────────────────────────────────────────────


def _fetch_content(items):
    """Fetch URL content for HN items without summaries."""
    to_fetch = [
        it for it in items
        if it.get("source") == "Hacker News"
        and not it.get("summary")
        and it.get("url") and "item?id=" not in it["url"]
    ]
    if not to_fetch:
        return

    def _f(it):
        c = fetch_url(it["url"], 1000)
        if c and not c.startswith("%PDF"):
            it["fetched_content"] = c
    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        ex.map(_f, to_fetch)


def _first_sentence(text):
    """取第一句有意义的句子。"""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    for sep in ["。", "！", "？", "；"]:
        idx = text.find(sep)
        if 10 < idx < 250:
            return text[:idx + 1]
    for sep in [". ", "! ", "? "]:
        idx = text.find(sep)
        if 10 < idx < 250:
            return text[:idx + 1]
    return text[:120] + ("…" if len(text) > 120 else "")


def _is_garbage(text):
    """检测是否为PDF/二进制/导航等垃圾内容。"""
    if not text:
        return True
    if text.startswith("%PDF") or text.startswith("%PNG"):
        return True
    nav = ["Search", "Sign in", "Sign up", "Subscribe",
           "Skip to main content", "Cookie policy",
           "All rights reserved", "Terms of Service"]
    count = sum(1 for m in nav if m.lower() in text.lower())
    return count >= 3


def run_profile(key, max_items=15):
    cfg = PROFILES[key]
    all_items = []
    print(f"  [{cfg['name']}] Fetching {len(cfg['sources'])} sources...", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(10) as ex:
        fm = {ex.submit(fn, lm, kw): fn.__name__ for fn, lm, kw in cfg["sources"]}
        for f in concurrent.futures.as_completed(fm):
            try:
                its = f.result()
                all_items.extend(its)
                print(f"    {fm[f]}: {len(its)}", file=sys.stderr)
            except Exception as e:
                print(f"    {fm[f]}: ERROR {e}", file=sys.stderr)
    all_items = [it for it in all_items if is_good_item(it)]
    all_items = dedup(all_items)
    print(f"    → After filter+dedup: {len(all_items)}", file=sys.stderr)

    for it in all_items:
        it["title"] = clean_title(it["title"], it.get("source", ""))

    _fetch_content(all_items)

    for it in all_items:
        title = it["title"]
        src = it.get("source", "")
        raw = it.get("summary") or it.get("fetched_content", "")

        if has_chinese(title):
            it["title_cn"] = title
        else:
            it["title_cn"] = translate_to_cn(title)

        # 中文快讯源：标题就是完整新闻
        if src in ("36氪", "华尔街见闻", "腾讯新闻", "微博热搜"):
            it["summary_cn"] = title
            continue

        if _is_garbage(raw):
            it["summary_cn"] = ""
            continue

        if has_chinese(raw):
            it["summary_cn"] = _first_sentence(raw[:400])
        elif raw:
            cn = translate_to_cn(raw[:600])
            it["summary_cn"] = _first_sentence(cn) if cn and cn != raw[:600] else ""
        else:
            it["summary_cn"] = ""

    # 过滤无摘要的
    final = [it for it in all_items
             if it.get("summary_cn") and len(it["summary_cn"]) >= 5
             and not _is_garbage(it["summary_cn"])]
    print(f"    → After summary quality filter: {len(final)}", file=sys.stderr)
    return cfg, final[:max_items]


# ── Format ─────────────────────────────────────────────────────────────────


def build_briefing():
    now = datetime.now()
    date_str = now.strftime("%Y年%m月%d日")
    weekday = WEEKDAYS[now.weekday()]

    lines = [
        f"📬 **每日新闻简报**",
        f"{date_str} {weekday}",
        "",
    ]
    total = 0

    for pk in ["general", "finance", "tech"]:
        cfg, items = run_profile(pk, 15)
        if not items:
            continue

        lines.append(f"{cfg['emoji']} **{cfg['name']}** · 共 {len(items)} 条")
        lines.append("")
        for i, it in enumerate(items, 1):
            emo = get_emoji(it.get("title_cn") or it.get("title", ""), it.get("source", ""))
            tc = it.get("title_cn") or it.get("title", "")
            sc = it.get("summary_cn", "")
            lines.append(f"{i}. {emo} {tc}")
            if sc and sc != tc:
                lines.append(f"")
                lines.append(f"   {sc}")
            lines.append("")
        total += len(items)

    lines.append("─" * 30)
    lines.append(f"📡 数据源: Hacker News / GitHub / 36氪 / 华尔街见闻 / Product Hunt / 腾讯新闻 / 微博热搜 / AI Newsletters")
    lines.append(f"🤖 共 {total} 条 · {now.strftime('%H:%M')} 自动生成")
    lines.append("")
    return "\n".join(lines), total


# ── Push ───────────────────────────────────────────────────────────────────


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
    url = SERVER_CHAN_URL.format(key=key)
    try:
        r = requests.post(url, data={"title": title, "desp": briefing}, timeout=30)
        res = r.json()
        if r.status_code == 200 and res.get("code") == 0:
            print(f"✅ 推送成功: {res.get('message', 'OK')}", file=sys.stderr)
            return True
        print(f"❌ 推送失败: {res}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"❌ 推送错误: {e}", file=sys.stderr)
        return False


# ── CLI ────────────────────────────────────────────────────────────────────


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
