"""
自动标签/话题生成器 (Auto Hashtag Generator)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
基于 LLM 的智能标签生成引擎，适配多平台话题文化。

功能：
- 从视频脚本中提取关键词
- 平台特定热门话题推荐（抖音 / B站 / YouTube）
- LLM 驱动的语义标签生成
- 热门度评分与排序
- 各平台最优标签数量建议

使用示例：
    hg = HashtagGenerator()
    tags = await hg.generate_tags(
        script={"title": "10分钟学会Python爬虫", "scenes": [...]},
        platform="douyin"
    )
    # tags → ["#Python", "#爬虫教程", "#编程入门", "#程序员日常", ...]

平台差异：
- 抖音：短标签为主（2-6字），偏好口语化/情绪化标签
- B站：二创文化，标签较长（4-10字），偏好圈层梗
- YouTube：英文为主，SEO 导向，长尾关键词
"""

import asyncio
import json
import logging
import re
import time
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("quanquan.auto_hashtag")


# ═══════════ 平台定义 ═══════════

class Platform(Enum):
    DOUYIN = "douyin"       # 抖音
    BILIBILI = "bilibili"   # B站
    YOUTUBE = "youtube"     # YouTube
    XIAOHONGSHU = "xiaohongshu"  # 小红书
    KUAISHOU = "kuaishou"   # 快手


PLATFORM_NAMES = {
    Platform.DOUYIN: "抖音",
    Platform.BILIBILI: "B站",
    Platform.YOUTUBE: "YouTube",
    Platform.XIAOHONGSHU: "小红书",
    Platform.KUAISHOU: "快手",
}

PLATFORM_DISPLAY = {
    "douyin": "抖音",
    "bilibili": "B站",
    "youtube": "YouTube",
    "xiaohongshu": "小红书",
    "kuaishou": "快手",
}


# ═══════════ 平台特定配置 ═══════════

@dataclass
class PlatformConfig:
    """平台标签策略配置"""
    platform_id: str
    display_name: str

    # 标签规范
    min_tags: int = 3           # 最少标签数
    max_tags: int = 8           # 最多标签数
    optimal_tags: int = 5       # 最优标签数
    max_tag_length: int = 20    # 单标签最大长度（字符）

    # 标签文化特征
    prefer_short: bool = True      # 偏好短标签
    prefer_emotional: bool = False # 偏好情绪化标签
    prefer_trending: bool = True   # 偏好热门标签
    prefer_long_tail: bool = False # 偏好长尾标签（SEO）
    use_english: bool = False      # 是否混用英文标签
    allow_numbers: bool = True     # 是否允许数字标签
    separator: str = " "           # 标签分隔符（抖音用空格，B站用空格）

    # LLM 提示词
    culture_description: str = ""  # 平台文化描述


PLATFORM_CONFIGS: Dict[str, PlatformConfig] = {
    "douyin": PlatformConfig(
        platform_id="douyin",
        display_name="抖音",
        min_tags=3, max_tags=8, optimal_tags=5,
        max_tag_length=10,
        prefer_short=True,
        prefer_emotional=True,
        prefer_trending=True,
        prefer_long_tail=False,
        use_english=False,
        allow_numbers=True,
        culture_description=(
            "抖音标签文化：短小精悍（2-6字），口语化、情绪化，"
            "喜欢用「」包裹的短语标签，大量使用网络热词和梗。"
            "典型标签如：#日常 #vlog #治愈 #美食 #搞笑 #涨知识"
        ),
    ),
    "bilibili": PlatformConfig(
        platform_id="bilibili",
        display_name="B站",
        min_tags=3, max_tags=10, optimal_tags=6,
        max_tag_length=15,
        prefer_short=False,
        prefer_emotional=False,
        prefer_trending=True,
        prefer_long_tail=False,
        use_english=False,
        allow_numbers=True,
        culture_description=(
            "B站标签文化：圈层化严重，标签较长（4-10字），大量使用二次元/鬼畜/游戏圈梗。"
            "喜欢用【】标注分区，标签带有强烈的社区归属感。"
            "典型标签如：#搞笑 #鬼畜 #科普 #混剪 #新人UP主 #每日一遍"
        ),
    ),
    "youtube": PlatformConfig(
        platform_id="youtube",
        display_name="YouTube",
        min_tags=5, max_tags=15, optimal_tags=8,
        max_tag_length=50,
        prefer_short=False,
        prefer_emotional=False,
        prefer_trending=False,
        prefer_long_tail=True,
        use_english=True,
        allow_numbers=True,
        culture_description=(
            "YouTube 标签文化：SEO 导向，以英文为主，重视长尾关键词，"
            "精确描述视频内容以便搜索引擎匹配。标签用于搜索排名而非社交互动。"
            "典型标签如：#PythonTutorial #MachineLearning #CodingForBeginners"
        ),
    ),
    "xiaohongshu": PlatformConfig(
        platform_id="xiaohongshu",
        display_name="小红书",
        min_tags=3, max_tags=10, optimal_tags=6,
        max_tag_length=10,
        prefer_short=True,
        prefer_emotional=True,
        prefer_trending=True,
        prefer_long_tail=False,
        use_english=False,
        allow_numbers=True,
        culture_description=(
            "小红书标签文化：种草导向，标签短且精准，注重场景化描述，"
            "女性用户为主，偏好生活方式/美妆/穿搭/美食类标签。"
            "典型标签如：#ootd #好物分享 #护肤 #打卡 #探店"
        ),
    ),
    "kuaishou": PlatformConfig(
        platform_id="kuaishou",
        display_name="快手",
        min_tags=3, max_tags=8, optimal_tags=5,
        max_tag_length=12,
        prefer_short=True,
        prefer_emotional=True,
        prefer_trending=True,
        prefer_long_tail=False,
        use_english=False,
        allow_numbers=True,
        culture_description=(
            "快手标签文化：接地气、老铁文化，标签贴近生活，农村/搞笑/才艺类居多。"
            "标签偏口语化，喜欢用感叹号和表情符号。"
            "典型标签如：#老铁 #农村生活 #搞笑日常 #才艺表演"
        ),
    ),
}


# ═══════════ 数据模型 ═══════════

@dataclass
class HashtagSuggestion:
    """标签建议"""
    tag: str                        # 标签文本（不含#号）
    platform: str                   # 目标平台
    category: str = "keyword"       # general / trending / keyword / semantic / longtail
    popularity_score: float = 0.0   # 热门度 0~1
    relevance_score: float = 0.0    # 相关度 0~1
    source: str = "ai"              # ai / trending_db / keyword_extract


@dataclass
class TrendingTopic:
    """热门话题"""
    topic: str
    platform: str
    trend_score: float = 0.0   # 热度评分 0~1
    category: str = "general"
    last_updated: float = 0.0


# ═══════════ HashtagGenerator ═══════════

class HashtagGenerator:
    """自动标签生成器 — 多平台适配

    工作流程：
    1. 从脚本中提取关键词
    2. LLM 生成语义标签
    3. 按平台优化标签列表
    4. 热门度评分排序
    """

    SYSTEM_PROMPT = """你是一位社交媒体运营专家，精通各大视频平台的标签/话题策略。

你的任务：为给定的视频内容生成平台优化的标签（hashtags）。

要求：
1. 标签要精准反映视频核心内容
2. 标签要有搜索价值（用户会主动搜索的词）
3. 标签要符合平台文化（不同平台标签风格差异很大）
4. 标签要有层级：核心标签（精确描述）+ 扩展标签（相关领域）+ 热门标签（蹭流量）

输出格式（纯 JSON，无代码块）：
{
  "tags": ["标签1", "标签2", "标签3", ...],
  "category_tags": {
    "core": ["核心标签"],
    "extended": ["扩展标签"],
    "trending": ["热门标签"]
  },
  "rationale": "标签策略说明（简短）"
}"""

    def __init__(self, llm_client=None):
        """初始化标签生成器

        Args:
            llm_client: LLM 客户端实例，不传则懒加载
        """
        self._llm = llm_client
        # 模拟的热门标签库（生产环境应接真实 API）
        self._trending_cache: Dict[str, List[TrendingTopic]] = {}
        self._cache_ttl: float = 3600  # 缓存1小时
        logger.info("[HashtagGenerator] 初始化完成")

    @property
    def llm(self):
        """懒加载 LLM 客户端"""
        if self._llm is None:
            from core.llm_client import llm as _llm
            self._llm = _llm
        return self._llm

    # ── 公共 API ──────────────────────────────────────────────

    async def generate_tags(
        self,
        script: dict,
        platform: str = "douyin",
        count: Optional[int] = None,
    ) -> List[str]:
        """为视频脚本生成标签

        Args:
            script: 脚本数据，至少包含 'title'，可选 'scenes' / 'style' / 'keywords'
            platform: 目标平台 (douyin / bilibili / youtube / xiaohongshu / kuaishou)
            count: 期望的标签数量，为空则使用平台最优值

        Returns:
            标签文本列表，如 ["Python", "爬虫教程", "编程入门"]
        """
        cfg = self._get_platform_config(platform)
        if count is None:
            count = cfg.optimal_tags

        title = script.get("title", "")
        scenes = script.get("scenes") or script.get("segments") or []
        style = script.get("style", "")
        existing_keywords = script.get("keywords", [])

        # 1. 提取关键词
        keywords = await self._extract_keywords(title, scenes)

        # 2. LLM 生成平台优化标签
        ai_tags = await self._generate_ai_tags(
            title=title,
            keywords=keywords,
            style=style,
            platform=platform,
            cfg=cfg,
        )

        # 3. 获取热门标签
        trending = await self.get_trending(platform, limit=5)

        # 4. 合并去重 + 评分排序
        all_tags = await self._merge_and_score(
            ai_tags=ai_tags,
            keywords=keywords,
            trending=trending,
            platform=platform,
            cfg=cfg,
        )

        # 5. 按平台限制截取
        result = self._finalize_tags(all_tags, count, cfg)

        logger.info(
            f"[HashtagGenerator] 为 '{title[:20]}...' 生成 {len(result)} 个 "
            f"{PLATFORM_DISPLAY.get(platform, platform)} 标签"
        )
        return result

    async def get_trending(self, platform: str = "douyin", limit: int = 10) -> List[TrendingTopic]:
        """获取平台热门话题

        Args:
            platform: 平台 ID
            limit: 返回数量

        Returns:
            热门话题列表
        """
        # 检查缓存
        now = time.time()
        cached = self._trending_cache.get(platform, [])
        if cached and (now - cached[0].last_updated) < self._cache_ttl:
            return cached[:limit]

        # 模拟热门话题（生产环境应接 API）
        trending = self._mock_trending(platform)

        # 更新缓存
        for t in trending:
            t.last_updated = now
        self._trending_cache[platform] = trending

        logger.debug(f"[HashtagGenerator] 获取 {platform} 热门话题 {len(trending)} 条")
        return trending[:limit]

    async def platform_optimize(
        self,
        tags: List[str],
        platform: str = "douyin",
    ) -> List[HashtagSuggestion]:
        """对已有标签进行平台适配优化

        根据平台文化特征调整标签：
        - 抖音：截短长标签、增加情绪词
        - B站：加圈层前缀
        - YouTube：翻译/补充英文标签

        Args:
            tags: 原始标签列表
            platform: 目标平台

        Returns:
            优化后的 HashtagSuggestion 列表
        """
        cfg = self._get_platform_config(platform)

        suggestions = []
        for tag in tags:
            optimized = self._optimize_single_tag(tag, cfg)
            suggestions.append(HashtagSuggestion(
                tag=optimized,
                platform=platform,
                category="keyword",
                popularity_score=0.5,
                relevance_score=0.8,
                source="optimized",
            ))

        # 对 YouTube 补充英文标签
        if platform == "youtube":
            en_tags = await self._translate_tags_english(tags)
            for en_tag in en_tags:
                if en_tag not in {s.tag for s in suggestions}:
                    suggestions.append(HashtagSuggestion(
                        tag=en_tag,
                        platform=platform,
                        category="semantic",
                        popularity_score=0.4,
                        relevance_score=0.7,
                        source="translated",
                    ))

        # 按热门度排序
        suggestions.sort(key=lambda s: s.popularity_score, reverse=True)

        logger.info(
            f"[HashtagGenerator] 平台优化: {len(tags)} → {len(suggestions)} 个标签 "
            f"({PLATFORM_DISPLAY.get(platform, platform)})"
        )
        return suggestions

    # ── 内部方法 ──────────────────────────────────────────────

    async def _extract_keywords(self, title: str, scenes: List[dict]) -> List[str]:
        """从标题和场景中提取关键词"""
        # 合并所有文本
        texts = [title]
        for s in scenes[:5]:
            text = s.get("narration", "") or s.get("text", "") or s.get("description", "")
            if text:
                texts.append(text[:100])

        full_text = " ".join(texts)
        if not full_text.strip():
            return []

        # 用 LLM 提取关键词
        try:
            response = await self.llm.chat(
                messages=[{
                    "role": "user",
                    "content": (
                        f"从以下视频文本中提取5-10个核心关键词，每行一个。"
                        f"只返回关键词，不要编号和解释：\n\n{full_text[:500]}"
                    ),
                }],
                temperature=0.2,
                max_tokens=256,
            )
            keywords = [
                kw.strip().lstrip("-•·1234567890.、)） ")
                for kw in response.strip().split("\n")
                if kw.strip()
            ]
            keywords = [kw for kw in keywords if len(kw) >= 2]
            return keywords[:10]
        except Exception as e:
            logger.warning(f"[HashtagGenerator] 关键词提取失败: {e}")
            # 简单回退：用正则提取中文词组
            chinese_words = re.findall(r'[\u4e00-\u9fff]{2,6}', title)
            return list(dict.fromkeys(chinese_words))[:10]

    async def _generate_ai_tags(
        self,
        title: str,
        keywords: List[str],
        style: str,
        platform: str,
        cfg: PlatformConfig,
    ) -> List[str]:
        """使用 LLM 生成平台优化的标签"""
        prompt = f"""为以下视频生成 {cfg.display_name} 平台的标签：

视频标题：{title}
关键词：{', '.join(keywords[:8])}
风格：{style or '未指定'}

平台文化：{cfg.culture_description}

标签要求：
- 最少{cfg.min_tags}个，最多{cfg.max_tags}个
- {'偏好短标签（2-6字）' if cfg.prefer_short else '标签长度适中'}
- {'可混用英文标签' if cfg.use_english else '使用中文标签'}
- 标签要分层：核心标签 + 扩展标签 + 热门标签

输出 JSON（纯 JSON，无代码块）：
{{
  "tags": ["标签1", "标签2", ...],
  "rationale": "简短说明"
}}"""

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
                max_tokens=512,
            )
            data = self._parse_json(response)
            tags = data.get("tags", [])
            # 清洗：去掉可能带有的#号
            tags = [t.lstrip("#＃").strip() for t in tags if t.strip()]
            return tags
        except Exception as e:
            logger.warning(f"[HashtagGenerator] LLM 标签生成失败: {e}")
            return keywords[:cfg.optimal_tags]

    async def _merge_and_score(
        self,
        ai_tags: List[str],
        keywords: List[str],
        trending: List[TrendingTopic],
        platform: str,
        cfg: PlatformConfig,
    ) -> List[HashtagSuggestion]:
        """合并 AI 标签、关键词、热门话题，并评分"""
        seen: Set[str] = set()
        suggestions: List[HashtagSuggestion] = []

        # 1. AI 标签 — 最高相关度
        for tag in ai_tags:
            normalized = tag.lower().strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                suggestions.append(HashtagSuggestion(
                    tag=tag,
                    platform=platform,
                    category="semantic",
                    popularity_score=0.6,
                    relevance_score=0.9,
                    source="ai",
                ))

        # 2. 关键词 — 高相关度
        for kw in keywords:
            normalized = kw.lower().strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                suggestions.append(HashtagSuggestion(
                    tag=kw,
                    platform=platform,
                    category="keyword",
                    popularity_score=0.3,
                    relevance_score=0.85,
                    source="keyword_extract",
                ))

        # 3. 热门话题 — 高热门度
        for trend in trending:
            normalized = trend.topic.lower().strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                suggestions.append(HashtagSuggestion(
                    tag=trend.topic,
                    platform=platform,
                    category="trending",
                    popularity_score=trend.trend_score,
                    relevance_score=0.4,  # 热门但未必相关
                    source="trending_db",
                ))

        # 综合评分 = 0.5*热门度 + 0.5*相关度
        for s in suggestions:
            s.popularity_score = round(0.5 * s.popularity_score + 0.5 * s.relevance_score, 3)

        # 排序
        suggestions.sort(key=lambda s: s.popularity_score, reverse=True)

        return suggestions

    def _finalize_tags(
        self,
        suggestions: List[HashtagSuggestion],
        count: int,
        cfg: PlatformConfig,
    ) -> List[str]:
        """最终标签列表：截取、清洗、格式化"""
        result = []
        for s in suggestions[:count]:
            tag = s.tag.strip()
            # 截断过长标签
            if len(tag) > cfg.max_tag_length:
                tag = tag[:cfg.max_tag_length]
            # 清理
            tag = tag.strip("#＃ \t\n")
            if tag and len(tag) >= 2:
                result.append(tag)

        return result[:count]

    def _optimize_single_tag(self, tag: str, cfg: PlatformConfig) -> str:
        """优化单个标签以适应平台"""
        tag = tag.strip("#＃ \t\n")

        # 截断
        if len(tag) > cfg.max_tag_length:
            tag = tag[:cfg.max_tag_length]

        # 抖音/快手：去掉过长的学术化表达
        if cfg.prefer_short and len(tag) > 6:
            # 尝试提取核心词
            core = re.sub(r'[的了么呢吗啊吧]', '', tag)
            if len(core) >= 2:
                tag = core[:6]

        return tag

    async def _translate_tags_english(self, tags: List[str]) -> List[str]:
        """将中文标签翻译为英文（YouTube 平台用）"""
        if not tags:
            return []

        try:
            response = await self.llm.chat(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Translate these Chinese video tags to concise English tags, "
                        f"one per line, keep them SEO-friendly:\n\n" +
                        "\n".join(tags[:10])
                    ),
                }],
                temperature=0.3,
                max_tokens=256,
            )
            en_tags = [
                t.strip() for t in response.strip().split("\n")
                if t.strip() and len(t.strip()) >= 2
            ]
            return en_tags[:len(tags)]
        except Exception as e:
            logger.warning(f"[HashtagGenerator] 英文翻译失败: {e}")
            return []

    def _get_platform_config(self, platform: str) -> PlatformConfig:
        """获取平台配置"""
        if platform in PLATFORM_CONFIGS:
            return PLATFORM_CONFIGS[platform]
        # 尝试部分匹配
        for key, cfg in PLATFORM_CONFIGS.items():
            if key in platform or platform in key:
                return cfg
        # 默认抖音
        logger.warning(f"[HashtagGenerator] 未知平台 '{platform}'，回退到抖音配置")
        return PLATFORM_CONFIGS["douyin"]

    def _parse_json(self, text: str) -> Dict:
        """智能 JSON 解析"""
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        return {}

    def _mock_trending(self, platform: str) -> List[TrendingTopic]:
        """模拟热门话题数据（生产环境替换为真实 API）"""
        mock_data = {
            "douyin": [
                ("日常vlog", 0.95, "lifestyle"),
                ("搞笑", 0.92, "entertainment"),
                ("美食教程", 0.88, "food"),
                ("舞蹈", 0.85, "dance"),
                ("旅行", 0.82, "travel"),
                ("变装", 0.80, "fashion"),
                ("猫咪", 0.78, "pet"),
                ("翻唱", 0.76, "music"),
                ("化妆教程", 0.74, "beauty"),
                ("健身", 0.72, "fitness"),
            ],
            "bilibili": [
                ("鬼畜", 0.93, "entertainment"),
                ("搞笑", 0.90, "entertainment"),
                ("科普", 0.87, "education"),
                ("混剪", 0.85, "editing"),
                ("游戏实况", 0.83, "gaming"),
                ("新人UP主", 0.80, "community"),
                ("动漫", 0.78, "anime"),
                ("数码评测", 0.75, "tech"),
                ("音乐", 0.73, "music"),
                ("舞蹈", 0.70, "dance"),
            ],
            "youtube": [
                ("Tutorial", 0.94, "education"),
                ("Vlog", 0.91, "lifestyle"),
                ("Review", 0.88, "tech"),
                ("Gaming", 0.86, "gaming"),
                ("Music", 0.84, "music"),
                ("HowTo", 0.82, "education"),
                ("Unboxing", 0.80, "tech"),
                ("Travel", 0.78, "travel"),
                ("Cooking", 0.76, "food"),
                ("Fitness", 0.74, "fitness"),
            ],
            "xiaohongshu": [
                ("护肤", 0.92, "beauty"),
                ("穿搭", 0.90, "fashion"),
                ("美食", 0.87, "food"),
                ("探店", 0.85, "lifestyle"),
                ("好物分享", 0.83, "shopping"),
                ("ootd", 0.80, "fashion"),
                ("美妆", 0.78, "beauty"),
                ("家居", 0.75, "home"),
                ("旅行攻略", 0.73, "travel"),
                ("健身打卡", 0.70, "fitness"),
            ],
            "kuaishou": [
                ("搞笑日常", 0.93, "entertainment"),
                ("农村生活", 0.90, "lifestyle"),
                ("才艺表演", 0.87, "talent"),
                ("美食", 0.85, "food"),
                ("老铁", 0.82, "community"),
                ("户外", 0.80, "outdoor"),
                ("正能量", 0.78, "social"),
                ("手工", 0.75, "diy"),
                ("汽车", 0.73, "auto"),
                ("游戏", 0.70, "gaming"),
            ],
        }

        topics = mock_data.get(platform, mock_data["douyin"])
        return [
            TrendingTopic(topic=t[0], platform=platform, trend_score=t[1], category=t[2])
            for t in topics
        ]

    def get_platform_configs(self) -> Dict[str, dict]:
        """获取所有平台配置摘要"""
        return {
            pid: {
                "display_name": cfg.display_name,
                "optimal_tags": cfg.optimal_tags,
                "min_tags": cfg.min_tags,
                "max_tags": cfg.max_tags,
                "culture": cfg.culture_description[:60] + "...",
            }
            for pid, cfg in PLATFORM_CONFIGS.items()
        }


# 模块级单例
hashtag_generator = HashtagGenerator()
