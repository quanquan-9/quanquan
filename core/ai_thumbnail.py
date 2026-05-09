"""
AI 封面图生成器 (AI Thumbnail Designer)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
基于 Gemini LLM 的智能封面图设计引擎。

功能：
- 分析视频脚本/场景，自动确定最佳封面概念
- 生成文字叠加设计建议（标语/副标题/关键词高亮）
- 从视频风格中提取配色方案
- 多种布局选项：centered / split / bottom-bar / cinematic
- 调用现有 ThumbnailGenerator 完成最终渲染

使用示例：
    designer = AIThumbnailDesigner()
    variants = await designer.generate_variants(
        script={"title": "赛博朋克2077深度评测", "scenes": [...]},
        style="cyberpunk"
    )
    # variants → [{"layout": "centered_title", "path": "/data/...png", "score": 0.92}, ...]
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("quanquan.ai_thumbnail")


# ═══════════ 数据模型 ═══════════

@dataclass
class ThumbnailConcept:
    """AI 生成的封面概念"""
    title: str                          # 主标题文本
    subtitle: str = ""                  # 副标题/标语
    keyword_highlights: List[str] = field(default_factory=list)  # 高亮关键词
    layout: str = "centered_title"      # 布局模板
    color_scheme_name: str = "auto"     # 配色方案名
    font_size_hint: str = "large"       # 字号建议: small / medium / large / xlarge
    text_position: str = "center"       # 文字位置
    overlay_opacity: float = 0.4        # 叠加层透明度
    rationale: str = ""                 # AI 设计理由
    score: float = 0.0                  # 综合评分 0~1


@dataclass
class StylePalette:
    """风格配色板"""
    style_name: str
    primary: str            # 主色 hex
    secondary: str          # 辅色 hex
    accent: str             # 强调色 hex
    text_light: str         # 亮色文字 hex
    text_dark: str          # 暗色文字 hex
    gradient_start: str     # 渐变起始 hex
    gradient_end: str       # 渐变终止 hex
    mood_tags: List[str] = field(default_factory=list)


# ═══════════ 预定义风格调色板 ═══════════

STYLE_PALETTES: Dict[str, StylePalette] = {
    "cyberpunk": StylePalette(
        style_name="赛博朋克",
        primary="#00ffcc", secondary="#ff00ff", accent="#ffff00",
        text_light="#00ffcc", text_dark="#0a0020",
        gradient_start="#0a0020", gradient_end="#1a0040",
        mood_tags=["科幻", "霓虹", "未来", "黑暗"],
    ),
    "tech": StylePalette(
        style_name="科技感",
        primary="#00d4ff", secondary="#0088ff", accent="#00ff88",
        text_light="#ffffff", text_dark="#001a2e",
        gradient_start="#001a2e", gradient_end="#003355",
        mood_tags=["科技", "数码", "创新", "极简"],
    ),
    "nature": StylePalette(
        style_name="自然风",
        primary="#4caf50", secondary="#81c784", accent="#ff9800",
        text_light="#ffffff", text_dark="#1b3a1b",
        gradient_start="#1b3a1b", gradient_end="#2d5a2d",
        mood_tags=["自然", "清新", "户外", "绿色"],
    ),
    "warm": StylePalette(
        style_name="暖色调",
        primary="#ff9800", secondary="#ffb74d", accent="#ff5722",
        text_light="#fff3e0", text_dark="#3d1c00",
        gradient_start="#3d1c00", gradient_end="#5c2e0a",
        mood_tags=["温暖", "舒适", "生活", "美食"],
    ),
    "dark": StylePalette(
        style_name="暗黑系",
        primary="#e0e0e0", secondary="#9e9e9e", accent="#ff1744",
        text_light="#cccccc", text_dark="#0a0a0a",
        gradient_start="#0a0a0a", gradient_end="#1a1a1a",
        mood_tags=["暗黑", "严肃", "深沉", "悬疑"],
    ),
    "vibrant": StylePalette(
        style_name="活力撞色",
        primary="#ff6d00", secondary="#ff00e5", accent="#00e5ff",
        text_light="#ffffff", text_dark="#1a0033",
        gradient_start="#1a0033", gradient_end="#330066",
        mood_tags=["活力", "年轻", "潮流", "冲击"],
    ),
    "minimal": StylePalette(
        style_name="极简白",
        primary="#212121", secondary="#757575", accent="#2962ff",
        text_light="#212121", text_dark="#ffffff",
        gradient_start="#fafafa", gradient_end="#e0e0e0",
        mood_tags=["简约", "干净", "商务", "高端"],
    ),
    "cinematic": StylePalette(
        style_name="电影感",
        primary="#ffd700", secondary="#b8860b", accent="#8b0000",
        text_light="#ffd700", text_dark="#0d0d0d",
        gradient_start="#0d0d0d", gradient_end="#1a1a2e",
        mood_tags=["电影", "大片", "史诗", "震撼"],
    ),
    "gaming": StylePalette(
        style_name="游戏电竞",
        primary="#ff4655", secondary="#0ff", accent="#ffd700",
        text_light="#ffffff", text_dark="#0f1923",
        gradient_start="#0f1923", gradient_end="#1a2735",
        mood_tags=["游戏", "电竞", "竞技", "热血"],
    ),
    "auto": StylePalette(
        style_name="自动",
        primary="#6c63ff", secondary="#3f51b5", accent="#ff4081",
        text_light="#ffffff", text_dark="#1a1a2e",
        gradient_start="#1a1a2e", gradient_end="#2d2d44",
        mood_tags=["通用"],
    ),
}

# 布局模板说明（给 LLM 的上下文）
LAYOUT_DESCRIPTIONS = {
    "centered_title": "标题垂直水平居中，带微妙阴影，适合简洁大气的封面",
    "split_left_right": "左半部分文字，右侧装饰色块/图标区，适合信息量较大的封面",
    "bottom_bar": "底部半透明标题栏 + 全屏背景，适合突出视觉主体的封面",
    "cinematic_letterbox": "上下黑边 + 居中标题，电影感十足，适合影视类内容",
}


# ═══════════ AIThumbnailDesigner ═══════════

class AIThumbnailDesigner:
    """AI 封面图设计器 — 使用 LLM 分析脚本并生成最佳封面方案

    工作流程：
    1. analyze_script() → 提取关键信息、情绪、风格
    2. suggest_thumbnail() → LLM 生成封面概念和设计建议
    3. generate_variants() → 调用 ThumbnailGenerator 渲染多个变体
    """

    # LLM 系统提示词
    SYSTEM_PROMPT = """你是一位专业的视频封面设计师，精通 YouTube/抖音/B站 的封面设计。

你的任务：
1. 分析视频脚本，提取最吸引人的卖点作为封面标题
2. 根据视频风格推荐配色方案和布局
3. 生成简洁有力的标语/副标题
4. 输出结构化 JSON

设计原则：
- 标题不超过15个字，要有冲击力
- 配色需与内容情绪匹配（赛博朋克→霓虹色 / 自然→绿色 / 科技→蓝色）
- 布局选择：信息密集型→split，视觉冲击型→cinematic，通用型→centered

输出格式（纯 JSON，无代码块）：
{
  "title": "精简封面标题",
  "subtitle": "副标题或标语",
  "keywords": ["关键词1", "关键词2"],
  "layout": "centered_title|split_left_right|bottom_bar|cinematic_letterbox",
  "color_style": "cyberpunk|tech|nature|warm|dark|vibrant|minimal|cinematic|gaming",
  "font_size_hint": "small|medium|large|xlarge",
  "text_position": "center|left|bottom",
  "overlay_opacity": 0.4,
  "rationale": "设计理由（简短）",
  "score": 0.85
}"""

    def __init__(self, llm_client=None, output_dir: str = "/data/quanquan/data/thumbnails"):
        """初始化 AI 封面设计器

        Args:
            llm_client: LLM 客户端实例，不传则从 core.llm_client 懒加载
            output_dir: 封面输出目录
        """
        self._llm = llm_client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[AIThumbnailDesigner] 初始化完成，输出目录={self.output_dir}")

    @property
    def llm(self):
        """懒加载 LLM 客户端"""
        if self._llm is None:
            from core.llm_client import llm as _llm
            self._llm = _llm
        return self._llm

    # ── 公共 API ──────────────────────────────────────────────

    async def analyze_script(self, script: dict) -> Dict:
        """分析视频脚本，提取封面设计所需的关键信息

        Args:
            script: 脚本数据，至少包含 'title' 字段，
                    可选 'scenes' / 'segments' / 'style' / 'emotion'

        Returns:
            {
                "main_topic": "核心主题",
                "emotion": "激昂/温馨/紧张/...",
                "target_audience": "目标受众",
                "keywords": ["关键词列表"],
                "suggested_style": "推荐的配色风格",
                "suggested_layout": "推荐的布局",
                "scene_count": 场景数,
                "total_duration_hint": "时长提示",
            }
        """
        title = script.get("title", "")
        scenes = script.get("scenes") or script.get("segments") or []
        style = script.get("style", "auto")
        emotion = script.get("emotion", "")

        # 提取场景文本
        scene_texts = []
        for s in scenes[:10]:  # 只取前10个场景用于分析
            text = s.get("narration", "") or s.get("text", "") or s.get("description", "")
            if text:
                scene_texts.append(text[:200])

        # 构建分析请求
        analysis_prompt = f"""分析以下视频脚本，提取封面设计所需的关键信息：

标题：{title}
风格：{style}
情绪：{emotion or "未知"}
场景片段（前{len(scene_texts)}个）：
{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(scene_texts))}

请输出 JSON：
{{
  "main_topic": "核心主题（10字以内）",
  "emotion": "激昂/温馨/紧张/悲伤/欢快/严肃/中立",
  "target_audience": "目标受众（如：游戏玩家/科技爱好者/美食爱好者）",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "suggested_style": "cyberpunk/tech/nature/warm/dark/vibrant/minimal/cinematic/gaming",
  "suggested_layout": "centered_title/split_left_right/bottom_bar/cinematic_letterbox",
  "scene_count": {len(scenes)},
  "total_duration_hint": "推测的视频时长范围"
}}"""

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": "你是视频内容分析专家。只返回 JSON，不要代码块。"},
                    {"role": "user", "content": analysis_prompt},
                ],
                temperature=0.3,
                max_tokens=1024,
            )
            result = self._parse_json_response(response)
            logger.info(f"[AIThumbnailDesigner] 脚本分析完成: {result.get('main_topic', '')}")
            return result
        except Exception as e:
            logger.warning(f"[AIThumbnailDesigner] 脚本分析失败: {e}")
            # 回退：基于元数据推断
            return self._fallback_analysis(script)

    async def suggest_thumbnail(self, script: dict, analysis: Optional[Dict] = None) -> ThumbnailConcept:
        """根据脚本和分析结果，生成封面设计建议

        Args:
            script: 脚本数据
            analysis: analyze_script() 的输出，为空则自动分析

        Returns:
            ThumbnailConcept 封面概念对象
        """
        if analysis is None:
            analysis = await self.analyze_script(script)

        title = script.get("title", "")
        style = script.get("style", analysis.get("suggested_style", "auto"))

        # 构建完整的封面设计请求
        design_prompt = f"""为以下视频设计封面缩略图：

【视频信息】
- 原标题：{title}
- 核心主题：{analysis.get('main_topic', title)}
- 情绪：{analysis.get('emotion', '中立')}
- 目标受众：{analysis.get('target_audience', '通用')}
- 关键词：{', '.join(analysis.get('keywords', []))}
- 视频风格：{style}

【可用布局】
- centered_title: {LAYOUT_DESCRIPTIONS.get('centered_title', '')}
- split_left_right: {LAYOUT_DESCRIPTIONS.get('split_left_right', '')}
- bottom_bar: {LAYOUT_DESCRIPTIONS.get('bottom_bar', '')}
- cinematic_letterbox: {LAYOUT_DESCRIPTIONS.get('cinematic_letterbox', '')}

【可用配色】
{', '.join(STYLE_PALETTES.keys())}

请输出 JSON（纯 JSON，无代码块）：
{{
  "title": "精简封面标题（≤15字）",
  "subtitle": "副标题或标语（≤20字）",
  "keywords": ["关键词1", "关键词2"],
  "layout": "布局名称",
  "color_style": "配色方案名称",
  "font_size_hint": "small/medium/large/xlarge",
  "text_position": "center/left/bottom",
  "overlay_opacity": 0.4,
  "rationale": "设计理由（简短）",
  "score": 0.85
}}"""

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": design_prompt},
                ],
                temperature=0.5,
                max_tokens=1024,
            )
            data = self._parse_json_response(response)

            concept = ThumbnailConcept(
                title=data.get("title", title[:15]),
                subtitle=data.get("subtitle", ""),
                keyword_highlights=data.get("keywords", []),
                layout=data.get("layout", "centered_title"),
                color_scheme_name=data.get("color_style", style),
                font_size_hint=data.get("font_size_hint", "large"),
                text_position=data.get("text_position", "center"),
                overlay_opacity=float(data.get("overlay_opacity", 0.4)),
                rationale=data.get("rationale", ""),
                score=float(data.get("score", 0.7)),
            )

            logger.info(
                f"[AIThumbnailDesigner] 封面建议: title='{concept.title}', "
                f"layout={concept.layout}, style={concept.color_scheme_name}, "
                f"score={concept.score:.2f}"
            )
            return concept

        except Exception as e:
            logger.warning(f"[AIThumbnailDesigner] LLM 封面建议失败: {e}")
            return self._fallback_concept(script, analysis)

    async def generate_variants(
        self,
        script: dict,
        style: str = "auto",
        layouts: Optional[List[str]] = None,
        max_variants: int = 3,
    ) -> List[Dict]:
        """生成多个封面变体，涵盖不同布局方案

        工作流程：
        1. 分析脚本
        2. LLM 建议封面概念
        3. 调用 ThumbnailGenerator 渲染每个变体
        4. 返回变体列表（含评分排序）

        Args:
            script: 脚本数据
            style: 视频风格
            layouts: 要生成的布局列表，为空则自动选择 top 3
            max_variants: 最大变体数

        Returns:
            [
                {
                    "path": "/data/.../thumb_xxx.png",
                    "layout": "centered_title",
                    "title": "封面标题",
                    "style": "cyberpunk",
                    "score": 0.92,
                    "rationale": "...",
                },
                ...
            ]
        """
        # 步骤1: 分析脚本
        analysis = await self.analyze_script(script)
        effective_style = analysis.get("suggested_style", style)

        # 步骤2: LLM 建议
        concept = await self.suggest_thumbnail(script, analysis)

        # 步骤3: 确定要生成的布局列表
        if layouts is None:
            # 自动选择：优先 AI 建议的布局，再补充其他
            all_layouts = ["centered_title", "split_left_right", "bottom_bar", "cinematic_letterbox"]
            preferred = concept.layout if concept.layout in all_layouts else "centered_title"
            layouts = [preferred] + [l for l in all_layouts if l != preferred]
            layouts = layouts[:max_variants]

        # 步骤4: 调用 ThumbnailGenerator 渲染
        from core.thumbnail_generator import ThumbnailGenerator
        tg = ThumbnailGenerator()

        rendered_script = dict(script)
        variants = []

        for i, layout in enumerate(layouts):
            try:
                # 为每个变体微调标题
                variant_title = concept.title
                if i == 0:
                    variant_title = concept.title  # 首选保持原样
                elif layout == "split_left_right":
                    variant_title = f"{concept.title}｜{concept.subtitle}" if concept.subtitle else concept.title
                elif layout == "bottom_bar":
                    variant_title = concept.title

                rendered_script["title"] = variant_title

                path = tg.generate(
                    script=rendered_script,
                    style=concept.color_scheme_name,
                    layout=layout,
                    width=1280,
                    height=720,
                )

                # 调整评分：首选布局得分最高
                score = concept.score * (1.0 - i * 0.08)

                variants.append({
                    "path": path,
                    "layout": layout,
                    "title": variant_title,
                    "style": concept.color_scheme_name,
                    "score": round(score, 3),
                    "rationale": concept.rationale if i == 0 else f"布局变体: {layout}",
                    "subtitle": concept.subtitle,
                })

                logger.info(
                    f"[AIThumbnailDesigner] 变体{i+1}/{len(layouts)}: "
                    f"layout={layout}, path={path}"
                )

            except Exception as e:
                logger.warning(f"[AIThumbnailDesigner] 变体{i+1}渲染失败 ({layout}): {e}")
                continue

        # 按评分排序
        variants.sort(key=lambda v: v["score"], reverse=True)

        logger.info(f"[AIThumbnailDesigner] 生成 {len(variants)} 个封面变体")
        return variants

    async def extract_color_palette(self, style: str = "auto", emotion: str = "") -> StylePalette:
        """从风格/情绪中提取配色方案

        Args:
            style: 风格名称（cyberpunk / nature / warm / ...）
            emotion: 情绪标签（激昂 / 温馨 / ...）

        Returns:
            StylePalette 配色板对象
        """
        # 先尝试直接匹配
        if style in STYLE_PALETTES and style != "auto":
            return STYLE_PALETTES[style]

        # 通过情绪推断风格
        if emotion:
            emotion_style_map = {
                "激昂": "vibrant", "兴奋": "tech", "紧张": "dark",
                "温馨": "warm", "悲伤": "dark", "中立": "minimal",
                "欢快": "vibrant", "严肃": "minimal", "震撼": "cinematic",
            }
            mapped = emotion_style_map.get(emotion, "auto")
            if mapped in STYLE_PALETTES:
                return STYLE_PALETTES[mapped]

        # 默认
        return STYLE_PALETTES["auto"]

    # ── 辅助方法 ──────────────────────────────────────────────

    def _parse_json_response(self, text: str) -> Dict:
        """智能 JSON 解析：处理各种 LLM 响应格式"""
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

        logger.warning(f"[AIThumbnailDesigner] JSON 解析失败: {text[:200]}")
        return {}

    def _fallback_analysis(self, script: dict) -> Dict:
        """LLM 不可用时的回退分析"""
        title = script.get("title", "")
        scenes = script.get("scenes") or script.get("segments") or []
        style = script.get("style", "auto")
        emotion = script.get("emotion", "中立")

        # 简单的关键词提取
        import re
        keywords = re.findall(r'[\u4e00-\u9fff]{2,6}', title)[:5]

        return {
            "main_topic": title[:10] if title else "未命名",
            "emotion": emotion,
            "target_audience": "通用观众",
            "keywords": keywords if keywords else ["视频", "内容"],
            "suggested_style": style if style != "auto" else "tech",
            "suggested_layout": "centered_title",
            "scene_count": len(scenes),
            "total_duration_hint": "未知",
        }

    def _fallback_concept(self, script: dict, analysis: Dict) -> ThumbnailConcept:
        """LLM 不可用时的回退概念"""
        title = script.get("title", "视频封面")
        return ThumbnailConcept(
            title=title[:15],
            subtitle="",
            keyword_highlights=analysis.get("keywords", []),
            layout=analysis.get("suggested_layout", "centered_title"),
            color_scheme_name=analysis.get("suggested_style", "auto"),
            font_size_hint="large",
            text_position="center",
            overlay_opacity=0.4,
            rationale="回退方案：基于脚本元数据的默认设计",
            score=0.5,
        )

    def list_styles(self) -> List[Dict]:
        """列出所有可用的配色风格"""
        return [
            {
                "name": name,
                "label": p.style_name,
                "primary": p.primary,
                "mood_tags": p.mood_tags,
            }
            for name, p in STYLE_PALETTES.items()
            if name != "auto"
        ]

    def list_layouts(self) -> Dict[str, str]:
        """列出所有可用布局模板及说明"""
        return dict(LAYOUT_DESCRIPTIONS)


# 模块级单例
ai_thumbnail_designer = AIThumbnailDesigner()
