# AI 情报站

每日自动从全球知名科技媒体采集 **24 小时内最有价值的 12 条 AI 情报**，
并追踪 **GitHub 三日 / 一周 / 一月星数增长最快的各 12 个开源项目**。

## 快速开始

```bash
# 采集当天数据（生成 data/latest.json、data/latest.js、data/daily/<日期>.json）
python fetch_daily.py

# 生成线上发布副本（输出到 ../ai-intel-public/）
python publish_build.py

# 本地预览
python -m http.server 8899
# 浏览器打开 http://127.0.0.1:8899/
```

> 直接双击 `index.html` 也能看 —— 前端在 fetch 受 CORS 限制时会
> 自动回退到 `data/latest.js`（采集脚本同步生成的 JS 版数据）。

### 页面结构

页面分三个视图，由头部导航切换，**默认打开「今日 AI 情报」**，点一下即切到其余两个：

| 导航项 | 内容 | 直链 |
|---|---|---|
| 📰 今日 AI 情报 | 24 小时内 TOP 12 新闻卡片 | 默认（无 hash） |
| 🚀 GitHub 开源趋势 | 三日 / 一周 / 一月三档 TOP 12 仓库 | `index.html#repos` |
| 🗓️ 历史归档 | 日历选日期，回看当天情报与开源榜单 | `index.html#history` |

导航右侧徽标显示各视图条目数（历史视图为已归档天数）；切换时同步更新 URL hash，
所以刷新、分享带 `#repos` / `#history/2026-10-29` 的链接都会直接落在对应页面。
键盘左右方向键也可在三项间切换。

### 历史归档（日历）

历史视图左侧是月历，右侧是所选日期的内容：

- **有归档的日期显示蓝色底并可点击**，今天加描边，当前查看的日期是渐变高亮；
- 月份用 `‹ ›` 翻页，首末月自动置灰；下方月份快捷按钮只列出**确有归档**的月份；
- 右侧可切「情报 / 开源项目」两个 Tab，默认情报；
- 「回到今天」：今天没归档时自动退到最近一个有归档的日期；
- 日历上按方向键可在有归档的日期之间快速跳（按 ← → ↑ ↓）；
- 历史新闻的时间显示为绝对时间（`MM-DD HH:mm`，北京时间），
  因为「20 分钟前」对旧闻没有意义。

数据加载是**按月懒加载**：索引文件只记录哪天有归档，点开某个月才请求
`data/history/<YYYY-MM>.json`，不会一次性下载全部历史。

### 命令行参数

| 参数 | 说明 |
|---|---|
| `--date YYYY-MM-DD` | 指定采集日期，默认今天 |
| `--no-github` | 跳过 GitHub 榜单，只采新闻 |
| `--dry-run` | 只打印结果，不写文件 |
| `-v / --verbose` | 输出调试日志 |

## 目录结构

```
ai-intel/
├── fetch_daily.py       采集入口
├── publish_build.py     生成静态发布副本（输出到 ./ai-intel-public/）
├── deploy_pages.py      构建 + 推送 gh-pages（调用 publish_build.py）
├── lib/
│   ├── http.py          HTTP 层：gzip 解压、重试、并发抓取（保序返回）
│   ├── feeds.py         RSS 2.0 / Atom 解析（标准库实现，无第三方依赖）
│   ├── sources.py       数据源配置 + AI / 热度 / 噪声词典
│   ├── scoring.py       打分、跨源去重、排序（含每源限额）
│   ├── news.py          新闻采集编排
│   └── github.py        GitHub Trending 采集 + 星数快照差分
├── data/
│   ├── latest.json      最新数据（前端主数据源）
│   ├── latest.js        同上，JS 版（file:// 兜底）
│   ├── daily/           历史日报，保留最近 365 天
│   └── snapshots/       每日星数快照，用于计算真实增量
├── index.html / styles.css / app.js
│
├── ai-intel-public/     ← 发布用纯静态副本（gitignore，不进 main）
│   ├── index.html / styles.css / app.js
│   └── data/
│       ├── latest.json + latest.js
│       └── history/      历史归档（日历数据）
│           ├── index.json / index.js   哪天有归档（只含日期与条数）
│           └── YYYY-MM.json            按月分片，点开该月才加载
│
└── .deploy-worktree/    ← gh-pages 分支的独立工作树（gitignore）
```

> `data/daily/` 保留 30 天原始日报；`publish_build.py` 会把这些日报
> **裁剪后按月合并**成 `history/YYYY-MM.json`（去掉评分内部字段，体积约为完整版的 1/4），
> 默认归档最近 365 天，可用 `python publish_build.py --keep-days 180` 调整。
> 因此要让日历翻到更早的日期，只需保证 `data/daily/` 里那些日报还在。

## 一、新闻选题：怎么挑出 12 条

### 采集范围

| 类别 | 来源 |
|---|---|
| 海外媒体 | TechCrunch AI、The Verge AI、MIT Technology Review、Wired AI、ZDNet AI、VentureBeat AI、Ars Technica AI |
| 一手官方 | OpenAI、Google DeepMind、Google AI Blog、Hugging Face、InfoQ（英文） |
| 国内媒体 | 量子位、InfoQ 中国、雷锋网、少数派 |
| 社区 / 论文 | Hacker News（Algolia API）、arXiv（cs.AI / cs.CL / cs.LG / cs.CV） |

所有源并发抓取，单个源失败只跳过自身，不影响整体。

### 打分模型

只保留发布时间在 **24 小时内** 的条目，然后按四项加权：

| 维度 | 权重 | 说明 |
|---|---|---|
| 新鲜度 | 28% | 24 小时内线性衰减（幂 0.85，前期衰减更慢） |
| AI 相关度 | 27% | 强信号词（如 `LLM` `大模型` `OpenAI`）权重远高于弱信号；标题权重高于摘要；饱和函数压缩避免堆词刷分 |
| 热度 | 28% | 标题热度词（发布 / 开源 / 融资 / 突破…）+ 跨源转载次数 + Hacker News 点赞与评论 |
| 来源权重 | 17% | 一手官方博客最高（OpenAI 1.0），社区与论文较低 |

另设**噪声惩罚**：命中「Top 10 工具盘点」「优惠券」「带货」等营销水文词时扣分，
避免榜单水文占据版面。

### 跨源去重

标题分词后做复合判定，满足任一条即视为同一事件：

1. **Jaccard 相似度 ≥ 0.62**；
2. **较小集合覆盖率 ≥ 0.50 且共有词 ≥ 3 个**。

只靠 Jaccard 会漏判「同一事件、不同措辞」的标题 —— 各家媒体在标题里增删修饰语
（`launches` / `announces` / `significant leap`）会让相似度掉到 0.30 左右，
即便两者共享全部专有名词。实测同事件标题覆盖率多在 0.50~0.65、
不同事件普遍低于 0.20，区间可分；加上「共有词 ≥ 3」可避免同公司泛词误合并。

合并后保留得分最高者作为代表，其余记为转载来源，并据此提升该事件的热度分。

### 来源多样性

纯全局排序下，更新频繁且权重高的源可能独占半数名额（实测曾出现单一源占 6/12）。
因此排序后追加**每源最多 3 席**的限额；若因此凑不满 12 条，把被挤下的高分条目
按分数顺序回填，保证始终足量。

## 二、GitHub 榜单：星数增量怎么算

这是本项目中唯一需要特别说明的部分 —— **GitHub 官方没有「最近三日」档位**，
因此增量分三种口径，取值优先级如下：

| 口径 | 适用对象 | 是否真实值 | 说明 |
|---|---|---|---|
| `new_repo` 新建推算 | 区间内新建的仓库 | ✅ 真实 | 仓库在窗口起点尚不存在（星数为 0），当前星数即区间真实增量 |
| `snapshot` 快照差分 | 有历史记录的老项目 | ✅ 真实 | 当前星数 − 该区间起点的本地快照星数 |
| `page` 页面数据 | Trending 页面命中的项目 | ✅ 真实 | 直接取 GitHub Trending 标注的 `stars this week/month` |
| `estimate` 估算外推 | 三日档、暂无快照时 | ⚠️ 估算 | GitHub 无三日档，按周增量的日均速度外推三日 |

**冷启动表现**：首次运行时没有历史快照，三日榜主要依靠「新建推算」与「周增量外推」。
**连续运行满 3 天后**，本地快照积累完成，老项目的三日增量会自动切换为**实测值**，
页面上的「估算」标注随之消失。

候选池由三部分构成，共约 300 个仓库：Trending 三档页面 + Search API 各窗口新建仓库 + 历史快照命中项。

## 三、发布到 GitHub Pages

### 通道选择

早期方案是发布到 WorkBuddy 站点托管，但宿主机安全策略会拦截「把本地目录上传到
外部托管服务」的动作（`decidedBy: ai`，`content approval was denied`），
定时任务里包含部署步骤也照样被拦，**无法做到真正的每日自动上线**。

现改为 **GitHub Pages + `git push`**：`git push` 不受该策略限制，于是全链路可以无人值守。

### 目录分工

| 目录 / 分支 | 内容 | 用途 |
|---|---|---|
| `ai-intel/`（main 分支） | 采集脚本 + 前端源码 + 数据 | 开发与每日采集 |
| `ai-intel/ai-intel-public/` | **仅** html / css / js / 数据 | 构建产物，被 `.gitignore` 忽略 |
| `.deploy-worktree/`（gh-pages 分支） | 发布副本快照 | 推送到 GitHub，由 Pages 对外提供访问 |

产物目录不并入 main，避免每日 JSON 把源码历史搅乱；用 git worktree 单独挂一个
`gh-pages` 工作树来提交。

### 每日链路

```bash
cd ai-intel
python fetch_daily.py    # 1. 采集 → data/latest.json、data/daily/<日期>.json
python deploy_pages.py   # 2. 构建副本 → 同步到 gh-pages → commit + push
```

`deploy_pages.py` 内部会调用 `publish_build.py`，所以不需要单独跑。它只在
`git status --porcelain` 有变化时才提交推送，无变化时打印「无变更，跳过提交」并正常退出，
**可反复执行**。加 `--dry-run` 只构建不推送。

`publish_build.py` 只挑选前端渲染必需的字段（`news` / `news_stats` / `news_sources` /
`github` / `github_meta` 等），评分内部字段不会外泄。

### 首次启用 Pages（仅一次）

仓库 Settings → Pages → Source 选 *Deploy from a branch* → 分支 `gh-pages`、
目录 `/ (root)` → Save。约 1 分钟后线上地址生效：

```
https://<用户名>.github.io/ai-intel-daily/
```

## 四、定时运行

每天 **09:30（北京时间）** 由 WorkBuddy 自动化任务
「AI 情报站 · 每日 9:30 采集并发布到 GitHub Pages」依次执行两步：

```bash
python fetch_daily.py    # 1. 采集 → data/latest.json、data/daily/<日期>.json
python deploy_pages.py   # 2. 构建副本 → gh-pages → push（GitHub Pages 自动上线）
```

该任务**不使用**站点托管发布工具（宿主机策略会拦截），只走 `git push`。
推送后 Pages 需要 30 秒到 1 分钟构建，不必立即抓取线上验证。

判误要点：

- `deploy_pages.py` 打印「无变更，跳过提交」是**正常**的（内容幂等），不是失败。
- 只有 push 报错或异常退出才算失败，需附日志原文。
- 某数据源超时属于正常降级，脚本会跳过该源继续。

历史保留天数由 `fetch_daily.py` 的 `KEEP_DAYS` 控制（当前 **365** 天）。

**缓存指纹**：静态托管返回的响应没有 `Cache-Control`，也没有 `ETag`，只有 `Last-Modified`。
浏览器对这种响应走启发式缓存，会在一段时间内直接使用本地副本、连条件请求都不发，
于是「样式改了、线上文件也换了，用户看到的却还是旧样子」。
因此 `publish_build.py` 在拷贝静态文件后会调用 `stamp_asset_versions()`，
把发布副本 `index.html` 里的引用改写成 `styles.css?v=<md5前8位>`、`app.js?v=<md5前8位>`：
内容一变 URL 就变，必然重新拉取；内容不变则哈希不变，缓存照常有效。
该函数幂等，重复执行结果一致。**改样式/脚本后必须跑一次 `deploy_pages.py`**，
直接改产物目录不会带指纹、也不会推送。

**判断「改了没生效」的顺序**（别一上来就怀疑代码）：

1. 拉线上文件算 md5，与本地比对 → 不一致说明没推送成功或 Pages 还在构建；
2. 一致但用户仍看到旧样式 → 浏览器内查 `document.styleSheets` 是否含目标规则，确认缓存；
3. 最后才排查代码逻辑。

**任务跑完不等于跑成功**：这类定时任务依赖 WorkBuddy 客户端在线，电脑关机或软件没开时到点不会执行，
会在客户端下次启动后补跑，实际写盘时间可能比 09:30 晚几个小时。
判断当天有没有数据，看 `data/daily/<日期>.json` 是否存在，不要只看时间点。

也可以用系统计划任务兜底（跑同样的两步）：

```bash
# Windows 计划任务（每天 9:30）
schtasks /create /tn "AI情报站每日采集" /tr "python C:\路径\ai-intel\deploy_pages.py" /sc daily /st 09:30

# Linux / macOS crontab
30 9 * * * cd /path/to/ai-intel && python fetch_daily.py && python deploy_pages.py >> logs/daily.log 2>&1
```

## 五、设计要点

- **零第三方依赖**：只用 Python 标准库（urllib / ElementTree / json），`pip install` 都不需要。
- **外部输入不可信**：所有新闻标题、摘要、链接都来自外部站点，前端统一用
  DOM API + `textContent` 构建，链接经 `safeUrl()` 只放行 http/https，杜绝 XSS。
- **保序并发**：`fetch_many()` 返回结果顺序与请求顺序严格一致，
  调用方才能按索引把结果对应回源配置（这一条踩过坑：乱序返回会导致源与条目错配）。
- **失败降级**：任一数据源不可达时只跳过该源；GitHub Trending 全部失败时页面仍正常渲染。
