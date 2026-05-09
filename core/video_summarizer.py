"""
AI 视频内容摘要生成器 (Video Summarizer)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
基于 Gemini LLM 的智能视频内容摘要引擎，支持多平台优化。

功能：
- 关键时间点提取 (extract_key_moments)：自动识别视频脚本中的精彩节点
- 平台优化描述生成 (generate_description)：B站长文 vs 抖音短文 vs YouTube SEO
- 分章节时间轴 (generate_chapters)：自动生成带时间戳的分节
- 标题变体建议 (suggest_title_variants)：生成多个备选标题供选择
- 支持视频脚本（含时间戳的场景列表）和纯文本输入

使用示例：
    summarizer = VideoSummarizer()
    moments = await summarizer.extract_key_moments(script)
    # → [{"timestamp": "00:30", "label": "精彩反转", "score": 0.95}, ...]
    
    desc = await summarizer.generate_description(script, platform="bilibili")
    # → 适合B站的长文描述，带分段和Emoji
    
    chapters = await summarizer.generate_chapters(script)
    # → [{"start": "00:00", "title": "开篇引入", "summary": "..."}, ...]
    
    titles = await summarizer.suggest_title_variants(script, count=5)
    # → ["震惊！Python竟然可以这样用", ...]

平台差异：
- B站 (bilibili)：长文描述，支持富文本，带分区标签，二创文化
- 抖音 (douyin)：极简描述，3行以内，口语化，带话题标签
- YouTube：SEO 优化，关键词密集，章节时间轴，英语为主
"""

import asyncio
import json
import logging
import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger("quanquan.video_summarizer")


# ═══════════ 数据模型 ═══════════

@dataclass
class KeyMoment:
    """视频关键时间点"""
    timestamp: str                       # 时间戳，如 "01:23" 或 "83"
    label: str                           # 标签，如 "精彩反转"
    description: str = ""                # 详细描述
    category: str = "highlight"          # highlight / cliffhanger / intro / climax / educational
    score: float = 0.0                   # 精彩度评分 0~1
    thumbnail_hint: str = ""            # 封面/缩略图文字建议


@dataclass
class Chapter:
    """视频章节"""
    title: str = ""                       # 章节标题
    start: str = ""                       # 起始时间戳
    end: str = ""                        # 结束时间戳
    summary: str = ""                    # 章节摘要
    keywords: List[str] = field(default_factory=list)  # 章节关键词
    is_sponsored: bool = False           # 是否含赞助/广告段


@dataclass
class PlatformDescription:
    """平台优化描述"""
    platform: str                        # bilibili / douyin / youtube
    description: str                     # 主描述文本
    short_description: str = ""          # 短版描述
    hashtags: List[str] = field(default_factory=list)  # 建议标签
    seo_keywords: List[str] = field(default_factory=list)  # SEO关键词
    character_count: int = 0             # 字符数
    estimated_read_time: int = 0         # 预估阅读秒数


@dataclass
class TitleVariant:
    """标题变体"""
    title: str                           # 标题文本
    style: str = "default"               # clickbait / professional / emotional / question / howto
    score: float = 0.0                   # 综合评分 0~1
    clickbait_level: float = 0.5         # 标题党程度 0~1
    rationale: str = ""                  # 推荐理由


# ═══════════ 平台描述策略 ═══════════

PLATFORM_DESC_PROFILES = {
    "bilibili": {
        "display_name": "B站",
        "max_chars": 2000,
        "style_guide": (
            "B站风格描述要求：\n"
            "1. 使用丰富的Emoji和分段标题（如「📌 本期看点」「⚡ 精彩时刻」）\n"
            "2. 开头用吸引人的一句话摘要（约50字）\n"
            "3. 详细的分段说明，每段100-200字\n"
            "4. 末尾加入互动引导（点赞/投币/收藏 三连）\n"
            "5. 自然地插入B站文化梗和二创术语\n"
            "6. 附上时间轴章节方便跳转\n"
            "7. 使用中文，语气亲切如朋友聊天"
        ),
    },
    "douyin": {
        "display_name": "抖音",
        "max_chars": 150,
        "style_guide": (
            "抖音风格描述要求：\n"
            "1. 极简风格，总共不超过3行\n"
            "2. 第一行用强吸引力文案（疑问/悬念/数字）\n"
            "3. 口语化、接地气的表达\n"
            "4. 结尾带2-3个热门话题标签\n"
            "5. 不需要分段，不需要Emoji\n"
            "6. 可适当使用网络流行语"
        ),
    },
    "youtube": {
        "display_name": "YouTube",
        "max_chars": 5000,
        "style_guide": (
            "YouTube风格描述要求：\n"
            "1. 英文为主，SEO友好\n"
            "2. 第一段是200字以内的Hook（吸引点击）\n"
            "3. 关键词自然散布在描述中，密度适中\n"
            "4. 包含清晰的章节时间轴（Chapter Timestamps）\n"
            "5. 末尾加入Subscribe CTA和相关视频链接\n"
            "6. 使用#标签分隔不同主题\n"
            "7. 可包含赞助声明（如有）和章节跳转"
        ),
    },
    "xiaohongshu": {
        "display_name": "小红书",
        "max_chars": 1000,
        "style_guide": (
            "小红书风格描述要求：\n"
            "1. 图文并茂的描述风格（即使视频也用图文思维）\n"
            "2. 使用Emoji分段，每段前加Emoji\n"
            "3. 强调使用体验和个人感受\n"
            "4. 结尾带小红书风格标签 #好物分享 #生活记录\n"
            "5. 女性友好语气，温柔亲切"
        ),
    },
}


# ═══════════ VideoSummarizer ═══════════

class VideoSummarizer:
    """AI 视频内容摘要生成器

    使用 LLM 分析视频脚本，生成多平台优化的描述、章节和标题。

    工作流程：
    1. 解析脚本中的场景/段落信息
    2. LLM 分析内容结构，识别关键节点
    3. 按平台策略生成定制化输出
    """

    # 系统提示词 - 关键时间点提取
    KEY_MOMENTS_SYSTEM = """你是一位专业的视频内容分析师，擅长识别视频中的关键时间点和精彩片段。

你的任务：分析给定的视频脚本/时间轴，识别所有值得标记的关键时刻。

关键时间点类型：
- intro: 开场引入（前10%位置）
- highlight: 内容精华/高能时刻
- climax: 剧情/情绪高潮
- cliffhanger: 悬念/反转
- educational: 教程中的关键步骤
- transition: 重要转场

输出格式（纯JSON，无代码块）：
{
  "moments": [
    {
      "timestamp": "00:00",
      "label": "简短的时刻标签",
      "description": "这一刻发生了什么",
      "category": "highlight",
      "score": 0.0~1.0,
      "thumbnail_hint": "适合做封面的文字"
    }
  ],
  "total_duration": "估计总时长",
  "density": "high/medium/low - 精彩度密度"
}"""

    # 系统提示词 - 描述生成
    DESCRIPTION_SYSTEM = """你是一位专业的社媒运营专家，擅长为不同平台撰写视频描述文案。

根据提供的平台风格指南，为视频生成最优化的描述文案。
注意：输出必须是纯JSON格式，不要包含markdown代码块标记。
确保文案字数不超过平台限制。"""

    # 系统提示词 - 章节生成
    CHAPTERS_SYSTEM = """你是一位专业的视频编辑，擅长为视频划分清晰的章节结构。

你的任务：分析视频脚本内容，生成逻辑清晰的章节划分。

要求：
1. 每个章节3-8分钟为宜
2. 章节标题简洁有力（5-15字）
3. 每个章节有简短的摘要说明
4. 标记可能的赞助/广告段落
5. 章节之间逻辑连贯

输出格式（纯JSON，无代码块）：
{
  "chapters": [
    {
      "start": "00:00",
      "end": "03:15",
      "title": "章节标题",
      "summary": "章节内容概述",
      "keywords": ["关键词1", "关键词2"],
      "is_sponsored": false
    }
  ],
  "chapter_count": 6,
  "total_duration": "20:00"
}"""

    # 系统提示词 - 标题变体
    TITLES_SYSTEM = """你是一位顶级的视频标题创作专家，精通各种风格的标题写作。

标题风格类型：
- clickbait: 夸张吸引眼球（"你绝对想不到..."、"99%的人不知道..."）
- professional: 专业严谨（"深入解析..."、"完整指南..."）
- emotional: 情感共鸣（"看完我哭了..."、"这就是生活..."）
- question: 提问式（"为什么...？"、"你知道...吗？"）
- howto: 教程式（"如何...？"、"X步学会..."）
- numbered: 数字型（"5个方法..."、"TOP 10..."）
- contrast: 对比型（"从月薪3K到3W..."、"小白vs大神..."）
- trending: 蹭热点型（结合当下热点事件）

要求：
1. 每个标题15-30字（中文）或8-15词（英文）
2. 风格多样，覆盖不同受众
3. 评分依据：吸引力、SEO价值、平台适配性
4. 说明每个标题的推荐理由

输出格式（纯JSON，无代码块）：
{
  "titles": [
    {
      "title": "标题文本",
      "style": "clickbait",
      "score": 0.0~1.0,
      "clickbait_level": 0.0~1.0,
      "rationale": "推荐理由"
    }
  ]
}"""

    def __init__(self, llm_client=None):
        """初始化摘要生成器

        Args:
            llm_client: LLM 客户端实例，不传则懒加载
        """
        self._llm = llm_client
        logger.info("[VideoSummarizer] 初始化完成")

    @property
    def llm(self):
        """懒加载 LLM 客户端"""
        if self._llm is None:
            from core.llm_client import llm as _llm
            self._llm = _llm
        return self._llm

    # ── 公共 API ──────────────────────────────────────────────

    async def extract_key_moments(
        self,
        script: dict,
        max_moments: int = 10,
    ) -> List[KeyMoment]:
        """从视频脚本中提取关键时刻

        Args:
            script: 脚本数据，需包含 'scenes'（场景列表，每场景含 timestamp/text）
                    或 'segments'（段落列表），以及 'title'/'duration' 等可选字段
            max_moments: 最多返回的关键时刻数量

        Returns:
            KeyMoment 列表，按时间戳排序
        """
        title = script.get("title", "未命名视频")
        scenes = script.get("scenes") or script.get("segments") or []
        duration = script.get("duration", "未知")

        # 构建场景文本，保留时间戳信息
        scene_texts = []
        for i, scene in enumerate(scenes):
            if isinstance(scene, dict):
                ts = scene.get("timestamp", scene.get("time", f"{i:02d}:00"))
                text = scene.get("text", scene.get("description", scene.get("content", "")))
                scene_texts.append(f"[{ts}] {text[:200]}")
            elif isinstance(scene, str):
                scene_texts.append(scene[:200])

        if not scene_texts:
            logger.warning("[VideoSummarizer] 脚本无场景数据，返回空列表")
            return []

        full_text = "\n".join(scene_texts)
        prompt = (
            f"视频标题：{title}\n"
            f"总时长：{duration}\n"
            f"最多标记 {max_moments} 个关键时刻。\n\n"
            f"时间轴内容：\n{full_text[:4000]}"
        )

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.KEY_MOMENTS_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2048,
            )
            data = self._parse_json(response)
            moments_data = data.get("moments", [])
        except Exception as e:
            logger.warning(f"[VideoSummarizer] LLM提取关键时刻失败: {e}")
            moments_data = self._fallback_key_moments(scene_texts)

        # 转换为数据类
        moments = []
        for m in moments_data[:max_moments]:
            moments.append(KeyMoment(
                timestamp=m.get("timestamp", "00:00"),
                label=m.get("label", ""),
                description=m.get("description", ""),
                category=m.get("category", "highlight"),
                score=float(m.get("score", 0.5)),
                thumbnail_hint=m.get("thumbnail_hint", ""),
            ))

        # 按时间戳排序
        moments.sort(key=lambda x: self._timestamp_to_seconds(x.timestamp))
        logger.info(f"[VideoSummarizer] 提取到 {len(moments)} 个关键时刻")
        return moments

    async def generate_description(
        self,
        script: dict,
        platform: str = "bilibili",
    ) -> PlatformDescription:
        """生成平台优化的视频描述

        Args:
            script: 脚本数据，需包含 'title'，可选 'scenes'/'summary'/'keywords'
            platform: 目标平台 (bilibili / douyin / youtube / xiaohongshu)

        Returns:
            PlatformDescription: 包含各版本描述和建议
        """
        profile = PLATFORM_DESC_PROFILES.get(platform)
        if not profile:
            raise ValueError(f"不支持的平台: {platform}，可选: {list(PLATFORM_DESC_PROFILES.keys())}")

        title = script.get("title", "未命名视频")
        summary = script.get("summary", "")
        keywords = script.get("keywords", [])
        scenes = script.get("scenes") or script.get("segments") or []

        # 构建内容摘要
        content_parts = [f"视频标题：{title}"]
        if summary:
            content_parts.append(f"内容概要：{summary}")
        if keywords:
            content_parts.append(f"关键词：{', '.join(keywords[:10])}")
        if scenes:
            scene_summary = "、".join(
                s.get("text", s.get("description", ""))[:80]
                for s in scenes[:5]
                if isinstance(s, dict)
            )
            if scene_summary:
                content_parts.append(f"主要场景：{scene_summary}")

        prompt = (
            f"平台：{profile['display_name']}\n"
            f"描述字数上限：{profile['max_chars']} 字符\n"
            f"风格要求：\n{profile['style_guide']}\n\n"
            f"视频信息：\n" + "\n".join(content_parts)
        )

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.DESCRIPTION_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                max_tokens=2048,
            )
            data = self._parse_json(response)
        except Exception as e:
            logger.warning(f"[VideoSummarizer] LLM生成描述失败: {e}")
            data = {
                "description": f"【{title}】\n精彩内容，不容错过！",
                "short_description": title,
                "hashtags": [],
                "seo_keywords": keywords[:5] if keywords else [],
            }

        description = data.get("description", "")
        short_desc = data.get("short_description", description[:100] if description else title)
        hashtags = data.get("hashtags", [])
        seo_kw = data.get("seo_keywords", keywords[:5] if keywords else [])

        result = PlatformDescription(
            platform=platform,
            description=description,
            short_description=short_desc,
            hashtags=hashtags,
            seo_keywords=seo_kw,
            character_count=len(description),
            estimated_read_time=max(1, len(description) // 400),
        )

        logger.info(
            f"[VideoSummarizer] 生成 {profile['display_name']} 描述 "
            f"({result.character_count} 字符)"
        )
        return result

    async def generate_chapters(
        self,
        script: dict,
        target_count: int = 6,
    ) -> List[Chapter]:
        """生成视频分章节时间轴

        Args:
            script: 脚本数据，需包含 'scenes'（带时间戳），以及 'duration'
            target_count: 目标章节数量

        Returns:
            Chapter 列表，按时间排序
        """
        title = script.get("title", "未命名视频")
        duration = script.get("duration", "未知")
        scenes = script.get("scenes") or script.get("segments") or []

        # 构建带时间戳的内容文本
        scene_texts = []
        for i, scene in enumerate(scenes):
            if isinstance(scene, dict):
                ts = scene.get("timestamp", scene.get("time", ""))
                text = scene.get("text", scene.get("description", scene.get("content", "")))
                scene_texts.append(f"[{ts}] {text[:150]}")
            elif isinstance(scene, str):
                scene_texts.append(scene[:150])

        prompt = (
            f"视频标题：{title}\n"
            f"总时长：{duration}\n"
            f"目标章节数：{target_count}\n\n"
            f"时间轴内容：\n" + "\n".join(scene_texts[:50])
        )

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.CHAPTERS_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=2048,
            )
            data = self._parse_json(response)
            chapters_data = data.get("chapters", [])
        except Exception as e:
            logger.warning(f"[VideoSummarizer] LLM生成章节失败: {e}")
            chapters_data = self._fallback_chapters(scenes, target_count)

        chapters = []
        for ch in chapters_data:
            chapters.append(Chapter(
                start=ch.get("start", "00:00"),
                end=ch.get("end", ""),
                title=ch.get("title", "未命名章节"),
                summary=ch.get("summary", ""),
                keywords=ch.get("keywords", []),
                is_sponsored=ch.get("is_sponsored", False),
            ))

        chapters.sort(key=lambda x: self._timestamp_to_seconds(x.start))
        logger.info(f"[VideoSummarizer] 生成 {len(chapters)} 个章节")
        return chapters

    async def suggest_title_variants(
        self,
        script: dict,
        count: int = 5,
    ) -> List[TitleVariant]:
        """生成标题变体建议

        Args:
            script: 脚本数据，需包含 'title'，可选 'summary'/'keywords'
            count: 生成的标题变体数量

        Returns:
            TitleVariant 列表，按评分降序
        """
        title = script.get("title", "")
        summary = script.get("summary", "")
        keywords = script.get("keywords", [])
        style = script.get("style", "")

        prompt = (
            f"原始标题：{title or '(无)'}\n"
            f"内容概要：{summary or '(无)'}\n"
            f"关键词：{', '.join(keywords[:10]) if keywords else '(无)'}\n"
            f"视频风格：{style or '(未指定)'}\n\n"
            f"请生成 {count} 个不同风格的标题变体。"
        )

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.TITLES_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                max_tokens=2048,
            )
            data = self._parse_json(response)
            titles_data = data.get("titles", [])
        except Exception as e:
            logger.warning(f"[VideoSummarizer] LLM生成标题失败: {e}")
            titles_data = self._fallback_titles(title, count)

        variants = []
        for t in titles_data[:count]:
            variants.append(TitleVariant(
                title=t.get("title", f"精彩视频 #{len(variants)+1}"),
                style=t.get("style", "default"),
                score=float(t.get("score", 0.5)),
                clickbait_level=float(t.get("clickbait_level", 0.5)),
                rationale=t.get("rationale", ""),
            ))

        variants.sort(key=lambda x: x.score, reverse=True)
        logger.info(f"[VideoSummarizer] 生成 {len(variants)} 个标题变体")
        return variants

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _timestamp_to_seconds(ts: str) -> float:
        """将时间戳字符串转为秒数"""
        if not ts:
            return 0.0
        ts = ts.strip()
        # 尝试 "MM:SS" 或 "HH:MM:SS" 格式
        parts = ts.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            else:
                return float(ts)
        except (ValueError, IndexError):
            return 0.0

    @staticmethod
    def _parse_json(text: str) -> dict:
        """智能 JSON 解析"""
        # 1. 直接解析
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        # 2. 提取 ```json ... ``` 代码块
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                pass
        # 3. 提取第一个 { ... } 块
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        logger.warning(f"[VideoSummarizer] JSON解析失败: {text[:200]}")
        return {}

    @staticmethod
    def _fallback_key_moments(scene_texts: List[str]) -> List[dict]:
        """回退：从场景文本简单提取关键时刻"""
        moments = []
        total = len(scene_texts)
        if total == 0:
            return moments

        # 简单按比例标记：开头、25%、50%、75%、结尾
        markers = [0, max(1, total // 4), total // 2, max(total - 2, 3 * total // 4), total - 1]
        labels = ["开场", "展开", "核心", "高潮", "结尾"]
        for idx, label in zip(markers, labels):
            if 0 <= idx < total:
                text = scene_texts[idx]
                ts_match = re.match(r'\[([^\]]+)\]', text)
                ts = ts_match.group(1) if ts_match else f"{idx:02d}:00"
                moments.append({
                    "timestamp": ts,
                    "label": label,
                    "description": text[:100],
                    "category": "highlight",
                    "score": 0.5,
                    "thumbnail_hint": "",
                })
        return moments

    @staticmethod
    def _fallback_chapters(scenes: list, target_count: int) -> List[dict]:
        """回退：从场景均匀分割生成章节"""
        if not scenes:
            return [{"start": "00:00", "end": "", "title": "完整视频", "summary": ""}]

        total = len(scenes)
        chapter_size = max(1, total // max(1, target_count))
        chapters = []
        for i in range(0, total, chapter_size):
            chunk = scenes[i:i + chapter_size]
            first = chunk[0]
            last = chunk[-1]
            start_ts = ""
            end_ts = ""
            if isinstance(first, dict):
                start_ts = first.get("timestamp", first.get("time", f"{i:02d}:00"))
            if isinstance(last, dict):
                end_ts = last.get("timestamp", last.get("time", ""))

            # 用第一个场景文本的前15字做标题
            first_text = ""
            if isinstance(first, dict):
                first_text = first.get("text", first.get("description", ""))
            elif isinstance(first, str):
                first_text = first
            ch_title = first_text[:15] if first_text else f"第{i//chapter_size + 1}章"

            chapters.append({
                "start": start_ts,
                "end": end_ts,
                "title": ch_title,
                "summary": "\n".join(
                    s.get("text", s.get("description", ""))[:100]
                    if isinstance(s, dict) else str(s)[:100]
                    for s in chunk[:3]
                ),
                "keywords": [],
                "is_sponsored": False,
            })
        return chapters

    @staticmethod
    def _fallback_titles(original_title: str, count: int) -> List[dict]:
        """回退：基于原标题生成简单变体"""
        if not original_title:
            original_title = "精彩视频"
        suffixes = [
            "｜深度解析", "｜新手必看", "｜超详细教程",
            "｜你学会了吗？", "｜99%的人不知道", "｜保姆级教学",
            "｜终极指南", "｜从入门到精通", "｜5分钟学会",
            "｜防坑指南",
        ]
        prefixes = [
            "【干货】", "【教程】", "【必看】", "【揭秘】",
            "【实测】", "【避坑】", "",
        ]
        variants = []
        styles = ["professional", "howto", "clickbait", "emotional", "question"]
        for i in range(min(count, len(suffixes))):
            prefix = prefixes[i % len(prefixes)]
            suffix = suffixes[i]
            variants.append({
                "title": f"{prefix}{original_title}{suffix}",
                "style": styles[i % len(styles)],
                "score": 0.6 - i * 0.05,
                "clickbait_level": 0.3 + i * 0.1,
                "rationale": f"变体 #{i+1}：{'添加' + prefix if prefix else ''}{suffix}增强吸引力",
            })
        return variants


# ── 便捷函数 ──────────────────────────────────────────────────

async def quick_summarize(script: dict, platform: str = "bilibili") -> dict:
    """快捷摘要：一次性返回描述、章节、关键时刻和标题

    Args:
        script: 视频脚本数据
        platform: 目标平台

    Returns:
        {
            "description": PlatformDescription,
            "chapters": [Chapter, ...],
            "key_moments": [KeyMoment, ...],
            "title_variants": [TitleVariant, ...],
        }
    """
    summarizer = VideoSummarizer()
    desc, chapters, moments, titles = await asyncio.gather(
        summarizer.generate_description(script, platform),
        summarizer.generate_chapters(script),
        summarizer.extract_key_moments(script),
        summarizer.suggest_title_variants(script),
    )
    return {
        "description": desc,
        "chapters": chapters,
        "key_moments": moments,
        "title_variants": titles,
    }
