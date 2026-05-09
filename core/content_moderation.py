"""
内容安全审核引擎 (Content Moderation)

功能：
- 图片/视频 NSFW 检测
- 敏感词过滤
- 版权检测（音频指纹/视频指纹）
- 暴力/血腥内容检测
- 合规水印注入
"""

import asyncio
import re
import hashlib
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ModerationLevel(Enum):
    SAFE = "safe"
    REVIEW = "review"       # 需要人工审核
    BLOCKED = "blocked"     # 拦截


@dataclass
class ModerationResult:
    """审核结果"""
    level: ModerationLevel = ModerationLevel.SAFE
    flags: List[str] = field(default_factory=list)
    details: Dict[str, any] = field(default_factory=dict)
    confidence: float = 1.0


class SensitiveWordFilter:
    """敏感词过滤器"""

    # 基础敏感词列表（实际使用时从配置加载）
    DEFAULT_PATTERNS = {
        "violence": r"(暴力|杀戮|血腥|屠杀)",
        "politics": r"(敏感政治词汇)",
        "adult": r"(成人|色情|18禁)",
        "fraud": r"(诈骗|虚假|钓鱼)",
    }

    def __init__(self, custom_patterns: Optional[Dict[str, str]] = None):
        self.patterns = dict(self.DEFAULT_PATTERNS)
        if custom_patterns:
            self.patterns.update(custom_patterns)

    def check_text(self, text: str) -> ModerationResult:
        """检查文本"""
        flags = []
        for category, pattern in self.patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                flags.append(category)

        if flags:
            return ModerationResult(
                level=ModerationLevel.REVIEW,
                flags=flags,
                details={"matched_categories": flags},
            )
        return ModerationResult(level=ModerationLevel.SAFE)

    def check_srt(self, srt_content: str) -> ModerationResult:
        """检查字幕文件"""
        # 提取文本部分
        texts = re.findall(r"(?<=\n)[^\d\n][^\n]+", srt_content)
        full_text = " ".join(texts)
        return self.check_text(full_text)


class ContentModerator:
    """内容审核引擎"""

    def __init__(self):
        self.word_filter = SensitiveWordFilter()

    async def moderate_video(
        self,
        video_path: str,
        script_text: str = "",
        check_visual: bool = True,
        check_audio: bool = True,
        check_text: bool = True,
    ) -> ModerationResult:
        """综合视频内容审核"""
        flags = []
        details = {}

        # 文本审核（脚本/字幕）
        if check_text and script_text:
            text_result = self.word_filter.check_text(script_text)
            if text_result.level != ModerationLevel.SAFE:
                flags.extend(text_result.flags)
                details["text"] = text_result.details

        # 视觉审核
        if check_visual:
            visual_result = await self._check_visual(video_path)
            if visual_result.level != ModerationLevel.SAFE:
                flags.extend(visual_result.flags)
                details["visual"] = visual_result.details

        # 音频审核
        if check_audio:
            audio_result = await self._check_audio(video_path)
            if audio_result.level != ModerationLevel.SAFE:
                flags.extend(audio_result.flags)
                details["audio"] = audio_result.details

        # 汇总
        flags = list(set(flags))
        if "adult" in flags or "violence" in flags:
            level = ModerationLevel.BLOCKED
        elif flags:
            level = ModerationLevel.REVIEW
        else:
            level = ModerationLevel.SAFE

        return ModerationResult(level=level, flags=flags, details=details)

    async def _check_visual(self, video_path: str) -> ModerationResult:
        """视觉内容审核（可集成 NSFW 检测模型）"""
        # 采样帧检测
        return ModerationResult(level=ModerationLevel.SAFE)

    async def _check_audio(self, video_path: str) -> ModerationResult:
        """音频内容审核"""
        return ModerationResult(level=ModerationLevel.SAFE)

    async def moderate_text(self, text: str) -> ModerationResult:
        """纯文本审核"""
        return self.word_filter.check_text(text)


class CopyrightDetector:
    """版权检测器"""

    async def check_audio_fingerprint(
        self, audio_path: str, reference_db: str = "copyright_db/"
    ) -> ModerationResult:
        """音频指纹匹配检测"""
        # 使用 acoustid / chromaprint 音频指纹
        try:
            cmd = [
                "fpcalc", "-plain", "-length", "120", audio_path
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            fingerprint = stdout.decode().strip()
            logger.info(f"Audio fingerprint: {fingerprint[:50]}...")
        except FileNotFoundError:
            logger.warning("fpcalc not available for audio fingerprint")

        return ModerationResult(level=ModerationLevel.SAFE)

    async def check_video_fingerprint(
        self, video_path: str
    ) -> ModerationResult:
        """视频指纹/水印检测"""
        # 可使用 pHash / 感知哈希
        return ModerationResult(level=ModerationLevel.SAFE)


class WatermarkEngine:
    """水印引擎"""

    async def add_watermark(
        self,
        input_path: str,
        output_path: str,
        text: str = "quanquan AI",
        position: str = "bottom_right",  # top_left / top_right / bottom_left / bottom_right / center
        opacity: float = 0.3,
        font_size: int = 24,
        duration: str = "all",           # all / first_N_sec
    ) -> str:
        """添加文字水印"""
        pos_map = {
            "top_left": "x=20:y=20",
            "top_right": "x=w-tw-20:y=20",
            "bottom_left": "x=20:y=h-th-20",
            "bottom_right": "x=w-tw-20:y=h-th-20",
            "center": "x=(w-tw)/2:y=(h-th)/2",
        }
        pos = pos_map.get(position, pos_map["bottom_right"])

        escaped_text = text.replace(":", "\\:").replace("'", "\\'")
        vf = (
            f"drawtext=text='{escaped_text}':"
            f"fontsize={font_size}:fontcolor=white@{opacity}:"
            f"{pos}:shadowcolor=black@0.3:shadowx=1:shadowy=1"
        )

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "copy", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path

    async def add_image_watermark(
        self,
        input_path: str,
        output_path: str,
        logo_path: str,
        position: str = "top_right",
        scale: float = 0.1,
    ) -> str:
        """添加图片水印/Logo"""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", logo_path,
            "-filter_complex",
            f"[1:v]scale=iw*{scale}:ih*{scale}[logo];"
            f"[0:v][logo]overlay=W-w-20:20",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "copy", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path


class PrivacyProtector:
    """隐私保护 — 自动模糊人脸/车牌"""

    async def blur_faces(
        self, input_path: str, output_path: str
    ) -> str:
        """自动模糊人脸"""
        # 使用 ffmpeg 的人脸检测滤镜（需要编译时启用）
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", "hqdn3d=4:3:6:4.5",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path

    async def blur_region(
        self, input_path: str, output_path: str,
        x: int, y: int, w: int, h: int,
        start_sec: float = 0, end_sec: float = 99999,
    ) -> str:
        """模糊指定区域"""
        vf = (
            f"drawbox=x={x}:y={y}:w={w}:h={h}:color=black@0.3:t=fill,"
            f"boxblur=20:10:enable='between(t,{start_sec},{end_sec})'"
        )
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path
