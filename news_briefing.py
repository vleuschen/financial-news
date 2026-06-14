#!/usr/bin/env python3
"""
每日新闻简报 — 方案 B：只用中文编辑源，标题即新闻。

    36氪 / 华尔街见闻 / 腾讯新闻 / 微博热搜 / AIHOT

用法：
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

# ── 36氪标题前缀清理 ──────────────────────────────────────────
_36K_RE = re.compile(
    r'^(36氪(?:Auto|出海)?|数字时氪|未来消费|智能涌现|未来城市|'
    r'启动Power\s*on|新经济IPO|Meta|风向|To\s?B|硬氪|新能源|36氪)\s*[\|｜]?\s*')

def clean_title(t, src=""):
    t = (t or "").strip()
    if "36" in src:
        t = _36K_RE.sub('', t)
    return re.sub(r'\s+', ' ', re.sub(r'^[\|｜\s•●·]+|[\|｜\s•●·]+$', '', t)).strip()

# ── Emoji ─────────────────────────────────────────────────────
EMOJI = [
    (r"人工智能|大模型|claude|chatgpt|openai|anthropic|fable|mythos|deepseek|agent|llm|模型|GPT|AI已|具身", "🤖"),
    (r"spacex|马斯克|starship|火箭|卫星|nasa|发射|飞船|太空", "🚀"),
    (r"苹果|apple|iphone|ipad|mac|库克|airpods|vision|ios|苹果", "🍎"),
    (r"谷歌|google|deepmind|gemini|android|pixel|alphabet", "🔍"),
    (r"meta|facebook|instagram|扎克伯格|llama|threads|whatsapp", "👓"),
    (r"英伟达|nvidia|gpu|显卡|黄仁勋|cuda|芯片|半导体|tsmc|intel|amd|光刻|晶圆|处理器|制程", "🖥️"),
    (r"微软|microsoft|windows|azure|纳德拉|copilot|office", "🪟"),
    (r"github|开源|open.source|代码|commit|开发者|repository|编程", "🐙"),
    (r"融资|创投|独角兽|ipo|上市|startup|venture|收购|并购|估值|天使|a轮|b轮|风投", "💎"),
    (r"股票|股市|基金|港股|美股|a股|上证|深证|纳斯达克|道指|标普|牛市|熊市|ipo|涨幅|市值|证券|投资者|散户|季度|年报|股息|分红|市盈", "📈"),
    (r"比特币|以太坊|bitcoin|ethereum|区块链|web3|nft|加密|数字货币|defi|币价|虚拟货币", "₿"),
    (r"数据|隐私|安全|泄露|黑客|网络攻击|漏洞|勒索|防火墙|个人信息", "🔒"),
    (r"5g|6g|通信|华为|中兴|基站|星链|starlink|iot|带宽|光纤|移动|联通|电信", "📡"),
    (r"石油|原油|能源|天然气|新能源|光伏|风电|储能|电池|碳中和|氢能|核能|电网|电力|充电", "⛽"),
    (r"汽车|电车|特斯拉|比亚迪|蔚来|小鹏|理想|自动驾驶|智驾|新能源车|燃油车|吉利|奇瑞|长城", "🚗"),
    (r"机器人|人形|humanoid|机器狗|机械臂|宇树|robotics|自动化", "🦾"),
    (r"量子|quantum|qubit|超导", "⚛️"),
    (r"基因|医疗|药物|疫苗|健康|制药|生物|临床|手术|细胞|dna|医院|诊断|药企", "🧬"),
    (r"气候|环保|碳排放|全球变暖|极端天气|污染|排放|绿色|可持续|巴黎协定|环保", "🌍"),
    (r"游戏|gaming|playstation|xbox|steam|任天堂|switch|epic|暴雪|nintendo|电竞", "🎮"),
    (r"youtube|tiktok|抖音|b站|bilibili|短视频|直播|流媒体|netflix|视频|腾讯视频|爱奇艺|优酷", "🎬"),
    (r"播客|podcast|lex\s*fridman", "🎙️"),
    (r"中国|北京|上海|中央|国务院|习近平|两会|央行|发改委|商务部|外交部|政协|党中央", "🇨🇳"),
    (r"美国|华盛顿|白宫|拜登|特朗普|trump|美联储|fed|硅谷|华尔街|国会|参议院|众议院|五角大楼", "🇺🇸"),
    (r"俄罗斯|普京|莫斯科|俄乌|俄军|克里姆林|putin|俄方", "🇷🇺"),
    (r"乌克兰|基辅|泽连斯基|乌军|乌方", "🇺🇦"),
    (r"欧盟|欧洲|德国|法国|英国|伦敦|巴黎|柏林|欧元|欧洲央行|默克尔|冯德莱恩|英国", "🇪🇺"),
    (r"日本|东京|索尼|丰田|日经|日元|软银|任天堂|岸田|石破|日本央行", "🇯🇵"),
    (r"韩国|三星|现代|首尔|韩元|lg|samsung|尹锡悦|李在明|msci|韩国", "🇰🇷"),
    (r"台湾|台积电|联发科|富士康|鸿海|tsmc|台积|台企", "🇹🇼"),
    (r"香港|恒生|港交所|hong\s*kong|港元|港股", "🇭🇰"),
    (r"伊朗|以色列|巴勒斯坦|哈马斯|真主党|霍尔木兹|中东|沙特|胡塞|也门|黎巴嫩|叙利亚|美伊|以黎|谈判|协议|停火|制裁|战争|军事|导弹|北约|国防|军队|武器|航母|核|冲突|战役", "⚔️"),
    (r"地震|洪水|台风|暴雨|飓风|海啸|山火|灾害|救援|灾难|遇难", "🌊"),
    (r"选举|大选|投票|民调|竞选|连任|总统|制宪|campaign|候选人", "🗳️"),
    (r"教育|学校|高考|中考|学生|大学|培训|学位|考研|留学|教材|升学|取消|课改", "📚"),
    (r"法律|法规|合规|反垄断|罚款|诉讼|判决|法院|仲裁|宪法|禁令|监管|立案|侵权", "⚖️"),
    (r"物价|通胀|cpi|ppi|工资|房价|租金|消费|零售|电商|购物|涨价|降价|税费|养路费|限购", "🏷️"),
    (r"手机|小米|oppo|vivo|荣耀|一加|pixel|samsung|galaxy|折叠|xiaomi|honor", "📱"),
    (r"足球|篮球|nba|fifa|世界杯|比赛|联赛|冠军|总决赛|体育|球员|傅明|巴西|TCR|巴伦西亚", "⚽"),
    (r"死亡|去世|自杀|谋杀|事故|刑事|犯罪|起诉|诉|庭审|法院|判决|赔偿", "⚰️"),
    (r"C919|大飞机|国产大飞机|商飞|民航|飞机|航空|空客|波音|南航|国航|东航", "✈️"),
    (r"贸易|关税|进出口|出口管制|营收|财报|利润|亏损|汇兑|业绩|暴雷", "💹"),
    (r"银行|贷款|信贷|利率|降息|加息|降准|存款|房贷|按揭|lpr|再贷款|再贴现", "🏦"),
]

def emoji(title, src=""):
    t = f"{title} {src}".lower()
    for pat, em in EMOJI:
        if re.search(pat, t):
            return em
    return ""

# ── RSS 解析 ──────────────────────────────────────────────────
def parse_rss(content, src, limit=10):
    items = []
    try:
        soup = BeautifulSoup(content, "lxml")
        for entry in soup.find_all(["item", "entry"])[:limit]:
            tt = entry.find("title")
            if not tt: continue
            title = re.sub(r'^\s*<!\[CDATA\[|\]\]>\s*$', '', tt.get_text(strip=True)).strip()
            if not title: continue
            items.append({"source": src, "title": title, "time": "", "url": ""})
    except: pass
    return items

def fetch_rss(url, src, limit=10):
    for a in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20, verify=False)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return parse_rss(r.content, src, limit)
        except:
            if a < 2: time.sleep(1 + a)
    return []

# ── 数据源 ────────────────────────────────────────────────────

def fetch_36kr(limit=5, keyword=None):
    """36氪快讯 — 中文标题即新闻。"""
    items = []
    try:
        soup = BeautifulSoup(
            requests.get("https://36kr.com/newsflashes", headers=HEADERS, timeout=10).text,
            "lxml")
        for el in soup.select(".newsflash-item"):
            te = el.select_one(".item-title")
            if not te: continue
            title = te.get_text(strip=True)
            tm = el.select_one(".time")
            items.append({
                "source": "36氪",
                "title": title,
                "time": tm.get_text(strip=True) if tm else "",
            })
        if keyword:
            items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [36Kr] 错误: {e}", file=sys.stderr)
    return items[:limit]

def fetch_wallstreetcn(limit=5, keyword=None):
    """华尔街见闻 — API 标题即新闻。"""
    items = []
    try:
        data = requests.get(
            "https://api-one.wallstcn.com/apiv1/content/information-flow?"
            "channel=global-channel&accept=article&limit=30", timeout=10).json()
        for item in data.get("data", {}).get("items", []):
            res = item.get("resource")
            if not res: continue
            title = res.get("title") or res.get("content_short")
            if not title: continue
            ts = res.get("display_time", 0)
            items.append({
                "source": "华尔街见闻",
                "title": title,
                "time": datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "",
            })
        if keyword:
            items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [WSCN] 错误: {e}", file=sys.stderr)
    return items[:limit]

def fetch_tencent(limit=5, keyword=None):
    """腾讯新闻 — 标题即新闻。"""
    items = []
    try:
        data = requests.get(
            "https://i.news.qq.com/web_backend/v2/getTagInfo?tagId=aEWqxLtdgmQ%3D",
            headers={"Referer": "https://news.qq.com/"}, timeout=10).json()
        for n in data.get("data", {}).get("tabs", [{}])[0].get("articleList", []):
            items.append({
                "source": "腾讯新闻",
                "title": n.get("title", ""),
                "time": n.get("pub_time", "") or n.get("publish_time", ""),
            })
        if keyword:
            items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [QQ] 错误: {e}", file=sys.stderr)
    return items[:limit]

def fetch_weibo(limit=5, keyword=None):
    """微博热搜 — 标题即话题。"""
    items = []
    try:
        raw = requests.get("https://weibo.com/ajax/side/hotSearch", headers={
            "User-Agent": HEADERS["User-Agent"], "Referer": "https://weibo.com/"}, timeout=10).json()
        for item in raw.get("data", {}).get("realtime", []):
            title = item.get("note", "") or item.get("word", "")
            if not title: continue
            items.append({
                "source": "微博热搜",
                "title": title,
                "heat": str(item.get("num", 0)),
                "time": "",
            })
        if keyword:
            items = [it for it in items if any(k in it["title"] for k in keyword.split(",") if k.strip())]
        return items[:limit]
    except Exception as e:
        print(f"  [Weibo] 错误: {e}", file=sys.stderr)
    return items[:limit]

def fetch_aihot(limit=5, keyword=None):
    """AIHOT 中文 AI 精选。"""
    items = fetch_rss("https://aihot.virxact.com/rss", "AIHOT", limit * 2)
    items = [it for it in items if _recent(it.get("time", ""), 24)]
    return items[:limit]

def _recent(ts, hours):
    if not ts: return True
    try:
        pub = parsedate_to_datetime(str(ts))
        if pub.tzinfo is None: pub = pub.replace(tzinfo=timezone.utc)
        return pub >= (datetime.now(timezone.utc) - timedelta(hours=hours))
    except: return True

# ── 过滤 ──────────────────────────────────────────────────────
def is_good(it):
    t = (it.get("title") or "").strip()
    if not t or len(t) < 6: return False
    # 过滤纯导航/广告/元内容
    garbage = [
        r'^(登录|注册|账号|设置|退出|首页|搜索|关于|联系|广告|免责|用户协议|隐私|版权)',
        r'(登录|注册|退出)$',
        r'^\d{1,3}$',  # 纯数字
    ]
    for g in garbage:
        if re.search(g, t): return False
    return True

# ── Profiles ─────────────────────────────────────────────────
PROFILES = {
    "general": {
        "emoji": "🌅", "name": "综合",
        "sources": [
            (fetch_36kr, 8, None),
            (fetch_wallstreetcn, 6, None),
            (fetch_weibo, 3, None),
            (fetch_aihot, 3, None),
        ],
    },
    "finance": {
        "emoji": "💰", "name": "财经",
        "sources": [
            (fetch_wallstreetcn, 8, None),
            (fetch_36kr, 5, "财报,营收,上市,IPO,投资,基金,股市,经济,银行,贷款,利率"),
            (fetch_tencent, 4, "财经,股票,基金,市场,经济,金融"),
        ],
    },
    "tech": {
        "emoji": "🤖", "name": "科技",
        "sources": [
            (fetch_36kr, 5, "融资,首发,独角兽,创投,科技,AI,人工智能"),
            (fetch_wallstreetcn, 5, "AI,芯片,半导体,特斯拉,苹果,谷歌,微软,SpaceX"),
            (fetch_aihot, 5, None),
        ],
    },
}

# ── 核心 ─────────────────────────────────────────────────────
def dedup(items):
    seen, result = set(), []
    for it in items:
        t = (it.get("title") or "").strip()
        if t and t not in seen:
            seen.add(t)
            result.append(it)
    return result

def run_profile(key, max_items=15):
    cfg = PROFILES[key]
    all_items = []
    print(f"  [{cfg['name']}] 抓取中...", file=sys.stderr)
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        fm = {}
        for entry in cfg["sources"]:
            fn, lm = entry[0], entry[1]
            kw = entry[2] if len(entry) > 2 else None
            f = ex.submit(fn, lm, kw)
            fm[f] = fn.__name__
        for f in concurrent.futures.as_completed(fm):
            try:
                its = f.result()
                all_items.extend(its)
                print(f"    {fm[f]}: {len(its)}", file=sys.stderr)
            except Exception as e:
                print(f"    {fm[f]}: 错误 {e}", file=sys.stderr)

    # 清洗 + 过滤 + 去重
    for it in all_items:
        it["title"] = clean_title(it["title"], it.get("source", ""))
    all_items = [it for it in all_items if is_good(it)]
    all_items = dedup(all_items)
    print(f"    → {len(all_items)} 条", file=sys.stderr)
    return cfg, all_items[:max_items]

# ── 格式化 ───────────────────────────────────────────────────
def build_briefing():
    now = datetime.now()
    lines = [now.strftime("%Y年%m月%d日") + " " + WEEKDAYS[now.weekday()], ""]
    total = 0
    for pk in ["general", "finance", "tech"]:
        cfg, items = run_profile(pk, 15)
        if not items: continue
        lines.append(f"{cfg['emoji']} **{cfg['name']}** · 共 {len(items)} 条")
        lines.append("")
        for i, it in enumerate(items, 1):
            title = it["title"]
            em = emoji(title, it.get("source", ""))
            prefix = f"{i}. {em}" if em else f"{i}. "
            lines.append(f"{prefix}{title}")
            lines.append("")
        total += len(items)
    lines.append("─" * 30)
    lines.append(f"📡 36氪 / 华尔街见闻 / 腾讯新闻 / 微博热搜 / AIHOT")
    lines.append(f"🤖 共 {total} 条 · {now.strftime('%H:%M')}")
    lines.append("")
    return "\n".join(lines), total

def push():
    key = os.environ.get("SERVER_CHAN_KEY", "")
    if not key:
        print("❌ 未设置 SERVER_CHAN_KEY", file=sys.stderr)
        return False
    now = datetime.now()
    print("📡 开始抓取...", file=sys.stderr)
    b, n = build_briefing()
    print(f"📊 共 {n} 条 → 推送...", file=sys.stderr)
    try:
        r = requests.post(SERVER_CHAN_URL.format(key=key),
            data={"title": now.strftime("📬 每日新闻简报 | %Y年%m月%d日"),
                  "desp": b}, timeout=30)
        res = r.json()
        if r.status_code == 200 and res.get("code") == 0:
            print(f"✅ {res.get('message', 'OK')}", file=sys.stderr)
            return True
        print(f"❌ {res}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        return False

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
