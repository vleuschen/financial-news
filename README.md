# 📬 Daily News Briefing

每日新闻简报自动推送机器人 —— 通过 GitHub Actions + Server酱，定时抓取硅谷科技、中国创投、开源社区、金融市场、国际新闻、AI 播客等资讯，推送到微信。

## 🚀 功能

| 简报 | 内容来源 | 条数 |
|------|---------|------|
| 🌅 **综合早报** | Hacker News + 36氪 + GitHub Trending + 华尔街见闻 + Product Hunt | ≤10 |
| 💰 **财经早报** | 华尔街见闻 + 36氪 + 腾讯新闻 + Hacker News(财经) | ≤10 |
| 🤖 **科技早报** | Hacker News(AI) + GitHub Trending + Product Hunt + 36氪(创投) | ≤10 |
| 🧠 **AI 深度日报** | Interconnects / One Useful Thing / AIHOT / Import AI | ≤10 |

## ⏰ 推送时间

| 时段 | 北京时间 |
|------|---------|
| 🌅 **早间推送** | 每天 **08:03** |
| 🌙 **晚间推送** | 每天 **20:03** |
| 🖐️ **手动触发** | GitHub Actions → Run workflow |

## 📁 项目结构

```
.
├── news_briefing.py           # 主脚本（抓取 + 格式化 + 推送）
├── requirements.txt           # Python 依赖
├── .github/workflows/
│   └── news_briefing.yml      # GitHub Actions 定时任务配置
└── README.md
```

## 🔧 配置步骤

### 1. 注册 Server酱

打开 https://sct.ftqq.com → 微信扫码登录 → 获取 **SendKey**

### 2. 添加 GitHub Secret

```
仓库 Settings → Secrets and variables → Actions → New repository secret
```

| Name | Value |
|------|-------|
| `SERVER_CHAN_KEY` | 你的 SendKey |

### 3. 手动触发测试

```
Actions → Daily News Briefing → Run workflow
```

检查微信是否收到推送。

## 🖥️ 本地测试

```bash
pip install -r requirements.txt

# 查看内容（不推送）
python news_briefing.py --profile general,finance,tech,ai_daily

# 推送到微信
SERVER_CHAN_KEY=your_key python news_briefing.py --push
```

## 📝 自定义

编辑 `news_briefing.py` 中的 `PROFILES` 字典即可调整数据源和条数上限。

## 📜 License

MIT
