"""
字幕 Agent (Subtitle Agent) — 独立模块

功能：
- SRT 字幕生成（从脚本）
- 字幕样式美化（多预设模板）
- 双语字幕生成
- 字幕时间轴微调（对齐配音）
- 字幕导出（SRT / ASS / VTT / JSON）
"""

import asyncio
import json
import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SubtitleEntry:
    """单条字幕"""
    index: int
    start_sec: float
    end_sec: float
    text: str
    translation: str = ""
    style: Optional[dict] = None


@dataclass
class SubtitleStyle:
    """字幕样式模板"""
    name: str
    font: str = "PingFang SC"
    font_size: int = 32
    color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: int = 2
    bold: bool = False
    alignment: str = "center"   # center / left / right
    position: str = "bottom"     # bottom / top / middle
    margin_v: int = 50


# 预设字幕样式
SUBTITLE_STYLES: Dict[str, SubtitleStyle] = {
    "default": SubtitleStyle("默认白字黑边"),
    "douyin": SubtitleStyle(
        "抖音流行", font_size=40, color="#FFEAA7",
        outline_color="#2d3436", outline_width=3,
    ),
    "minimal": SubtitleStyle(
        "极简白字", outline_width=0, position="bottom",
    ),
    "movie": SubtitleStyle(
        "电影字幕", font="Microsoft YaHei", font_size=28,
        color="#E8D5B7", outline_color="#000000",
        outline_width=1, position="bottom",
    ),
    "vibrant": SubtitleStyle(
        "活力黄字", font_size=36, color="#FFD700",
        outline_color="#8B0000", outline_width=2,
    ),
    "bilingual": SubtitleStyle(
        "双语字幕", font_size=24, color="#FFFFFF",
        outline_width=1, position="bottom",
    ),
}


class SubtitleAgent:
    """字幕 Agent 3.0 — CoT推理 + 多格式导出 + 样式模板 + 自我批判"""

    # ── Agent Capabilities (3.0) ──
    AGENT_CAPABILITIES = {
        "name": "SubtitleAgent",
        "version": "3.0",
        "description": "AI字幕师 — 智能字幕生成与多格式导出",
        "capabilities": [
            "srt_generation",           # SRT字幕生成
            "ass_export",               # ASS带样式导出
            "vtt_export",               # VTT Web字幕
            "bilingual_subtitle",       # 双语字幕
            "style_presets",            # 6种预设样式模板
            "timeline_adjustment",      # 时间轴微调
            "cot_reasoning",            # Chain-of-Thought推理
            "self_critique",            # 自我批判改进
            "context_memory",           # 项目历史感知
        ],
        "input_formats": ["script_json", "voiceover_json", "style_name"],
        "output_formats": ["srt", "ass", "vtt", "json", "subtitle_entries"],
        "style_presets": ["default", "douyin", "minimal", "movie", "vibrant", "bilingual"],
    }

    def __init__(self, context_bus, artifact_store, config: dict):
        self.bus = context_bus
        self.artifacts = artifact_store
        self.config = config
        self.state = "IDLE"

    async def run(self):
        while True:
            event = await self.bus.wait_for('TASK_DISPATCH',
                                            filter=lambda e: e.payload.get('agent') == 'Subtitle')
            await self._handle_task(event)

    async def _handle_task(self, event):
        task = event.payload
        self.state = "RECEIVING"

        # 拉取脚本
        script = await self.artifacts.get(task['project_id'],
                                          task['input'].get('script_key'))
        voiceover = await self.artifacts.get(task['project_id'],
                                              task['input'].get('voiceover_key'))

        self.state = "GENERATING"
        segments = script.get('segments', [])
        voice_duration = voiceover.get('duration', 0) if voiceover else 0

        # 生成字幕条目
        entries = self._script_to_entries(segments, voice_duration)

        # 选择样式
        style_name = task['input'].get('subtitle_style', 'default')
        style = SUBTITLE_STYLES.get(style_name, SUBTITLE_STYLES['default'])

        self.state = "EXPORTING"
        srt_content = self._to_srt(entries)

        self.state = "PUBLISHING"
        artifact = {
            'subtitle_id': f"{task['project_id']}_subtitle_v1",
            'entries': [e.__dict__ for e in entries],
            'srt_content': srt_content,
            'total_entries': len(entries),
            'style': style.__dict__,
            'total_duration_sec': voice_duration,
        }

        ref = await self.artifacts.put(task['project_id'], task['output_key'], artifact)
        await self.bus.publish('RESULT_PUBLISH', {
            'node_id': task['node_id'],
            'output_key': task['output_key'],
            'artifact_ref': ref,
        })
        self.state = "IDLE"

    def _script_to_entries(
        self, segments: List[dict], total_duration: float
    ) -> List[SubtitleEntry]:
        """脚本段落 → 字幕条目"""
        entries = []
        if not segments:
            return entries

        current_time = 0.0
        total_chars = sum(len(s.get('text', '')) for s in segments)
        if total_chars == 0:
            return entries

        # 按字符数比例分配时间
        for i, seg in enumerate(segments):
            text = seg.get('text', '')
            char_ratio = len(text) / total_chars
            seg_duration = total_duration * char_ratio

            # 长句拆分
            sentences = re.split(r'(?<=[。！？.!?])', text)
            sentences = [s.strip() for s in sentences if s.strip()]

            if sentences:
                sub_dur = seg_duration / len(sentences)
                for sent in sentences:
                    entries.append(SubtitleEntry(
                        index=len(entries) + 1,
                        start_sec=current_time,
                        end_sec=current_time + sub_dur,
                        text=sent,
                    ))
                    current_time += sub_dur
            elif text:
                entries.append(SubtitleEntry(
                    index=len(entries) + 1,
                    start_sec=current_time,
                    end_sec=current_time + seg_duration,
                    text=text,
                ))
                current_time += seg_duration

        return entries

    def _to_srt(self, entries: List[SubtitleEntry]) -> str:
        """导出 SRT 格式"""
        lines = []
        for e in entries:
            start = self._format_time(e.start_sec)
            end = self._format_time(e.end_sec)
            lines.append(str(e.index))
            lines.append(f"{start} --> {end}")
            lines.append(e.text)
            lines.append("")
        return "\n".join(lines)

    def _to_ass(self, entries: List[SubtitleEntry], style: SubtitleStyle) -> str:
        """导出 ASS 格式（带样式）"""
        header = f"""[Script Info]
Title: quanquan AI Subtitle
ScriptType: v4.00+
Collisions: Normal
PlayDepth: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, Italic, Alignment, MarginV
Style: Default,{style.font},{style.font_size},&H{self._color_to_ass(style.color)},&H{self._color_to_ass(style.outline_color)},{1 if style.bold else 0},0,2,{style.margin_v}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = [header]
        for e in entries:
            start = self._format_ass_time(e.start_sec)
            end = self._format_ass_time(e.end_sec)
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{e.text}")

        return "\n".join(lines)

    @staticmethod
    def _format_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _format_ass_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds - int(seconds)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    @staticmethod
    def _color_to_ass(hex_color: str) -> str:
        """#FFFFFF → 00FFFF (BGR)"""
        hex_color = hex_color.lstrip('#')
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        return f"00{b}{g}{r}"  # ASS 是 BGR 顺序

    # ── 3.0 critique() ──

    async def critique(self, output: dict, context: dict = None) -> dict:
        """自我批判：审查字幕方案质量。"""
        context = context or {}
        output_json = json.dumps(output, ensure_ascii=False, indent=2)[:3000]
        messages = [
            {"role": "system", "content": (
                "你是资深字幕导演。请审查字幕方案质量，从以下维度评分(0-100)：\n"
                "1. timing_accuracy: 时间轴是否准确\n"
                "2. readability: 长度/断句是否易读\n"
                "3. style_appropriateness: 样式是否恰当\n"
                "4. sync_quality: 与配音同步性\n"
                "5. completeness: 内容覆盖完整度\n"
                "\n只输出JSON: {\"scores\": {dim: 0-100}, \"issues\": [...], \"suggestions\": [...], \"overall\": 0-100}"
            )},
            {"role": "user", "content": f"字幕方案：\n{output_json}\n\n请审查。"},
        ]
        try:
            from core.llm_client import llm
            result = await llm.chat_json(messages, temperature=0.3, max_tokens=1024)
            result.setdefault("overall", 70)
            result.setdefault("scores", {})
            result.setdefault("issues", [])
            result.setdefault("suggestions", [])
            return result
        except Exception as e:
            return {"overall": 60, "scores": {}, "issues": [f"critique failed: {e}"], "suggestions": []}
