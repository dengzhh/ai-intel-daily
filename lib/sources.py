"""数据源配置与 AI 领域词典。

每个源的配置字段：
    name     展示名
    url      源地址
    kind     rss | hn | arxiv
    lang     zh | en
    weight   来源权重（0~1，越大越权威）
    ai_only  该源是否本身就是 AI 垂直频道（是则默认认为与 AI 相关）
"""

from __future__ import annotations

# ---------------------------------------------------------------- RSS 源 -----
RSS_SOURCES: list[dict] = [
    # ---------------- 海外一线科技媒体（AI 垂直频道 / 综合科技） ----------------
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "lang": "en",
        "weight": 0.98,
        "ai_only": True,
    },
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "lang": "en",
        "weight": 0.95,
        "ai_only": True,
    },
    {
        "name": "MIT Tech Review AI",
        "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
        "lang": "en",
        "weight": 0.93,
        "ai_only": True,
    },
    {
        "name": "Wired AI",
        "url": "https://www.wired.com/feed/tag/ai/latest/rss",
        "lang": "en",
        "weight": 0.88,
        "ai_only": True,
    },
    {
        "name": "ZDNet AI",
        "url": "https://www.zdnet.com/topic/artificial-intelligence/rss.xml",
        "lang": "en",
        "weight": 0.82,
        "ai_only": True,
    },
    # ---------------- 一手官方博客（权重最高：信息源自发布方本身） ----------------
    {
        "name": "OpenAI",
        "url": "https://openai.com/news/rss.xml",
        "lang": "en",
        "weight": 1.0,
        "ai_only": True,
    },
    {
        "name": "Google DeepMind",
        "url": "https://deepmind.google/blog/rss.xml",
        "lang": "en",
        "weight": 0.99,
        "ai_only": True,
    },
    {
        "name": "Google AI Blog",
        "url": "https://blog.google/technology/ai/rss/",
        "lang": "en",
        "weight": 0.94,
        "ai_only": True,
    },
    {
        "name": "Hugging Face",
        "url": "https://huggingface.co/blog/feed.xml",
        "lang": "en",
        "weight": 0.87,
        "ai_only": True,
    },
    {
        "name": "InfoQ 英文",
        "url": "https://feed.infoq.com/ai-ml-data-eng/",
        "lang": "en",
        "weight": 0.86,
        "ai_only": True,
    },
    # ---------------- 国内科技 / 技术媒体 ----------------
    {
        "name": "量子位",
        "url": "https://www.qbitai.com/feed",
        "lang": "zh",
        "weight": 0.94,
        "ai_only": True,
    },
    {
        "name": "雷锋网",
        "url": "https://www.leiphone.com/feed",
        "lang": "zh",
        "weight": 0.83,
        "ai_only": False,
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
        "lang": "en",
        "weight": 0.90,
        "ai_only": True,
    },
    {
        "name": "Ars Technica AI",
        "url": "https://arstechnica.com/ai/feed/",
        "lang": "en",
        "weight": 0.90,
        "ai_only": True,
    },
    # ---------------- 国内科技 / 技术媒体 ----------------
    {
        "name": "InfoQ 中国",
        "url": "https://www.infoq.cn/feed",
        "lang": "zh",
        "weight": 0.84,
        "ai_only": False,
    },
    {
        "name": "少数派",
        "url": "https://sspai.com/feed",
        "lang": "zh",
        "weight": 0.70,
        "ai_only": False,
    },
]

# ------------------------------------------------------- Hacker News (API) ----
HN_QUERIES = ["AI", "LLM", "OpenAI", "GPT", "Claude", "agent", "machine learning"]
HN_MIN_POINTS = 30

# ------------------------------------------------------------- arXiv 论文 -----
ARXIV_CATEGORIES = ["cs.AI", "cs.CL", "cs.LG", "cs.CV"]
ARXIV_MAX_RESULTS = 40

# ------------------------------------------------------------------ 词典 -----
# 强信号：命中即基本可判定为 AI 领域
AI_STRONG_KEYWORDS = [
    "artificial intelligence", "machine learning", "deep learning", "large language model",
    "llm", "llms", "genai", "generative ai", "foundation model", "neural network",
    "transformer", "diffusion model", "fine-tuning", "finetuning", "rag", "agentic",
    "ai agent", "ai model", "chatbot", "copilot", "openai", "chatgpt", "gpt-4", "gpt-5",
    "anthropic", "claude", "gemini", "llama", "mistral", "deepmind", "hugging face",
    "sora", "midjourney", "stable diffusion", "nvidia", "gpu", "tpu", "openai's",
    "人工智能", "大模型", "大语言模型", "机器学习", "深度学习", "神经网络", "生成式",
    "智能体", "多模态", "算力", "训练模型", "推理模型", "自然语言", "预训练", "对齐",
    "英伟达", "强化学习", "ai 芯片", "ai芯片", "通义", "文心", "混元", "kimi", "deepseek",
    "智谱", "qwen", "glm", "豆包",
]

# 弱信号：AI 相关但需与其他信号叠加
AI_WEAK_KEYWORDS = [
    "ai", "a.i.", "ml", "nlp", "computer vision", "speech recognition", "dataset",
    "inference", "benchmark", "robot", "automation", "algorithm", "embedding",
    "vector database", "prompt", "token", "model", "算法", "模型", "机器人", "自动化",
    "自动驾驶", "芯片", "数据标注", "算力",
]

# 热度词：标题中出现通常意味着事件具备传播价值
HYPE_KEYWORDS = [
    "launch", "launching", "unveil", "release", "released", "introduce", "announce",
    "breakthrough", "raises", "funding", "acquisition", "acquire", "ipo", "open source",
    "open-source", "openai", "billion", "million", "beats", "outperform", "record",
    "发布", "推出", "开源", "融资", "收购", "上市", "突破", "超越", "上线", "首发",
    "免费", "升级", "联手", "合作", "亿", "亿美元", "挑战", "取代", "禁令", "监管",
]

# 低价值信号：出现时扣分，避免广告/榜单水文占据版面
NOISE_KEYWORDS = [
    "best ai tools", "top 10", "top 20", "prompts you", "how to use chatgpt",
    "gift guide", "deal", "discount", "coupon", "black friday", "sponsored",
    "测评排行", "好用推荐", "优惠券", "广告", "带货", "注册送", "免费领",
]


def build_arxiv_url(categories: list[str], max_results: int) -> str:
    """拼接 arXiv API 查询地址（按提交时间倒序取最新论文）。

    查询串中的空格与 `+` 必须百分号编码，否则 urllib 会拒绝该 URL。
    """
    from urllib.parse import urlencode

    query = " OR ".join(f"cat:{c}" for c in categories)
    params = urlencode(
        {
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": max_results,
        }
    )
    return f"https://export.arxiv.org/api/query?{params}"


def build_hn_url(query: str, since_ts: int, min_points: int) -> str:
    """拼接 Hacker News Algolia 检索地址（按时间倒序）。"""
    from urllib.parse import quote

    return (
        "https://hn.algolia.com/api/v1/search_by_date?"
        f"query={quote(query)}&tags=story"
        f"&numericFilters=created_at_i>{since_ts},points>{min_points}"
        "&hitsPerPage=40"
    )
