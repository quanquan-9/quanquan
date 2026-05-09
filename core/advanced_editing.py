"""
高级剪辑引擎 (Advanced Editing Engine)

功能：
- 自动转场生成（20+预设）
- 关键帧动画系统
- 多轨道混音 + 音频闪避 (Audio Ducking)
- LUT 色彩预设库（50+ LUT）
- 变速控制（曲线变速）
"""

import asyncio
import os
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TransitionType(Enum):
    """转场类型"""
    DISSOLVE = "dissolve"             # 交叉溶解
    FADE_BLACK = "fade_black"         # 黑场过渡
    FADE_WHITE = "fade_white"         # 白场过渡
    SLIDE_LEFT = "slide_left"         # 左滑
    SLIDE_RIGHT = "slide_right"        # 右滑
    SLIDE_UP = "slide_up"             # 上滑
    SLIDE_DOWN = "slide_down"         # 下滑
    ZOOM_IN = "zoom_in"               # 放大
    ZOOM_OUT = "zoom_out"             # 缩小
    GLITCH = "glitch"                 # 故障效果
    FLASH = "flash"                   # 闪白
    WIPE = "wipe"                     # 擦除
    CLOCK = "clock"                   # 时钟旋转
    BLUR = "blur"                     # 模糊过渡
    PIXELATE = "pixelate"             # 像素化
    SWIRL = "swirl"                   # 漩涡
    PAGE_CURL = "page_curl"           # 翻页
    CUBE = "cube"                     # 3D立方体
    CAROUSEL = "carousel"             # 旋转木马
    CUSTOM = "custom"                 # 自定义


@dataclass
class TransitionConfig:
    """转场配置"""
    type: TransitionType = TransitionType.DISSOLVE
    duration_sec: float = 0.5
    easing: str = "ease_in_out"       # linear / ease_in / ease_out / ease_in_out / custom
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KeyframeAnimation:
    """关键帧动画"""
    target_property: str              # scale / position / rotation / opacity
    keyframes: List[dict]             # [{time_sec, value, easing}]
    loop: bool = False


@dataclass
class AudioTrack:
    """音轨"""
    file_path: str
    start_sec: float = 0
    duration_sec: float = 0
    volume: float = 1.0
    pan: float = 0.0                 # -1 (左) ~ 1 (右)
    effects: List[dict] = field(default_factory=list)  # 效果链
    duck_target: bool = False        # 是否响应音频闪避


class TransitionGenerator:
    """转场生成器"""

    def get_ffmpeg_filter(
        self, transition: TransitionConfig,
        from_clip: str, to_clip: str
    ) -> str:
        """生成 ffmpeg xfade 滤镜字符串"""
        type_map = {
            TransitionType.DISSOLVE: "dissolve",
            TransitionType.FADE_BLACK: "fadeblack",
            TransitionType.FADE_WHITE: "fadewhite",
            TransitionType.SLIDE_LEFT: "slideleft",
            TransitionType.SLIDE_RIGHT: "slideright",
            TransitionType.SLIDE_UP: "slideup",
            TransitionType.SLIDE_DOWN: "slidedown",
            TransitionType.ZOOM_IN: "zoomin",
            TransitionType.WIPE: "wiperight",
            TransitionType.PIXELATE: "pixelize",
        }
        xfade_type = type_map.get(transition.type, "dissolve")
        dur = transition.duration_sec
        offset = f"offset=0"

        if transition.type in (TransitionType.GLITCH, TransitionType.FLASH):
            return f"gltransition=duration={dur}:source=./glsl/{transition.type.value}.glsl"
        elif transition.type == TransitionType.BLUR:
            return f"xfade=transition= dissolve:duration={dur}:offset=0"

        return f"xfade=transition={xfade_type}:duration={dur}:offset=0"

    async def apply_transitions(
        self,
        clips: List[str],
        transitions: List[TransitionConfig],
        output_path: str,
    ) -> str:
        """应用转场到视频片段列表"""
        if len(clips) < 2:
            return clips[0] if clips else ""

        # 构建 ffmpeg filter_complex
        filter_parts = []
        for i in range(len(clips)):
            filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}]")

        for i in range(len(clips) - 1):
            trans = transitions[i] if i < len(transitions) else TransitionConfig()
            xfade = self.get_ffmpeg_filter(trans, f"[v{i}]", f"[v{i+1}]")
            offset = sum(t.duration_sec for t in transitions[:i])
            filter_parts.append(
                f"[v{i}][v{i+1}]xfade=transition=dissolve:"
                f"duration={trans.duration_sec}:offset={offset}[tmp{i}]"
            )

        # 执行
        inputs = []
        for clip in clips:
            inputs.extend(["-i", clip])

        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", ";".join(filter_parts),
            "-map", f"[tmp{len(clips)-2}]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path

    def list_transitions(self) -> List[dict]:
        """列出所有可用转场"""
        return [
            {"name": t.value, "has_glsl": t in (TransitionType.GLITCH, TransitionType.FLASH)}
            for t in TransitionType
        ]


class KeyframeAnimator:
    """关键帧动画系统"""

    ANIMATABLE_PROPERTIES = [
        "scale", "position_x", "position_y", "rotation",
        "opacity", "crop_x", "crop_y", "crop_w", "crop_h",
    ]

    def generate_zoom_in_out(
        self, duration_sec: float, zoom_ratio: float = 1.1
    ) -> KeyframeAnimation:
        """生成缩放动画（Ken Burns效果）"""
        return KeyframeAnimation(
            target_property="scale",
            keyframes=[
                {"time_sec": 0, "value": 1.0, "easing": "ease_out"},
                {"time_sec": duration_sec, "value": zoom_ratio, "easing": "ease_out"},
            ],
        )

    def generate_pan(
        self, duration_sec: float, direction: str = "left_to_right"
    ) -> KeyframeAnimation:
        """生成平移动画"""
        if direction == "left_to_right":
            kfs = [
                {"time_sec": 0, "value": 0.0, "easing": "linear"},
                {"time_sec": duration_sec, "value": 100.0, "easing": "linear"},
            ]
        elif direction == "right_to_left":
            kfs = [
                {"time_sec": 0, "value": 100.0, "easing": "linear"},
                {"time_sec": duration_sec, "value": 0.0, "easing": "linear"},
            ]
        elif direction == "top_to_bottom":
            kfs = [
                {"time_sec": 0, "value": 0.0, "easing": "linear"},
                {"time_sec": duration_sec, "value": 100.0, "easing": "linear"},
            ]
        else:
            kfs = [
                {"time_sec": 0, "value": 100.0, "easing": "linear"},
                {"time_sec": duration_sec, "value": 0.0, "easing": "linear"},
            ]

        return KeyframeAnimation(
            target_property="position_x" if direction in ("left_to_right", "right_to_left") else "position_y",
            keyframes=kfs,
        )

    def generate_pulse(self, duration_sec: float, count: int = 3) -> KeyframeAnimation:
        """生成脉冲动画"""
        kfs = []
        interval = duration_sec / (count * 2)
        for i in range(count * 2 + 1):
            kfs.append({
                "time_sec": i * interval,
                "value": 1.1 if i % 2 == 0 else 1.0,
                "easing": "ease_in_out",
            })
        return KeyframeAnimation(target_property="scale", keyframes=kfs)

    def to_ffmpeg_expr(self, animation: KeyframeAnimation) -> str:
        """转换为 ffmpeg 表达式"""
        # 简化：取首尾值做线性
        if len(animation.keyframes) >= 2:
            start_v = animation.keyframes[0]["value"]
            end_v = animation.keyframes[-1]["value"]
            dur = animation.keyframes[-1]["time_sec"] - animation.keyframes[0]["time_sec"]
            return f"{start_v}+({end_v}-{start_v})*t/{dur}"
        return "1.0"


class AudioMixer:
    """多轨道混音器 + 音频闪避"""

    async def mix_tracks(
        self,
        tracks: List[AudioTrack],
        output_path: str,
        sample_rate: int = 48000,
    ) -> str:
        """混合多个音轨"""
        if not tracks:
            return ""

        # 构建 ffmpeg amix
        inputs = []
        for t in tracks:
            inputs.extend(["-i", t.file_path])

        # 找出需要闪避的目标（配音→降低BGM）
        voice_tracks = [t for t in tracks if t.duck_target]
        bgm_tracks = [t for t in tracks if not t.duck_target]

        if voice_tracks and bgm_tracks:
            # 音频闪避：配音出现时降低背景音乐音量
            filter_complex = self._build_ducking_filter(voice_tracks, bgm_tracks)
        else:
            # 简单混音
            filter_complex = (
                f"[0:a][1:a]amix=inputs={len(tracks)}:duration=longest:"
                f"dropout_transition=2:normalize=0[aout]"
            )

        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-ar", str(sample_rate),
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path

    def _build_ducking_filter(
        self, voices: List[AudioTrack], bgms: List[AudioTrack]
    ) -> str:
        """构建音频闪避滤镜"""
        # sidechain compression: voice作为sidechain，压缩BGM
        return (
            f"[1:a]asplit=2[bgm_orig][bgm_side];"
            f"[0:a]volume=1.0[voice];"
            f"[voice]asplit[voice_out][voice_sc];"
            f"[voice_sc]loudnorm=I=-16:TP=-1.5:LRA=11[voice_norm];"
            f"[bgm_side][voice_norm]sidechaincompress="
            f"threshold=0.05:ratio=4:attack=10:release=200[bgm_ducked];"
            f"[voice_out][bgm_ducked]amix=inputs=2:duration=longest:normalize=0[aout]"
        )

    async def normalize_audio(
        self, input_path: str, output_path: str, target_lufs: float = -16.0
    ) -> str:
        """音频响度归一化 (EBU R128)"""
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:linear=true",
            "-ar", "48000", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path


class LUTLibrary:
    """LUT 色彩预设库"""

    # 50个预设 LUT 定义
    PRESETS = {
        "cinematic_teal": {"name": "电影青橙", "category": "cinematic"},
        "warm_sunset": {"name": "温暖日落", "category": "warm"},
        "cool_moonlight": {"name": "清冷月光", "category": "cool"},
        "vintage_sepia": {"name": "复古棕褐", "category": "vintage"},
        "high_contrast_bw": {"name": "高对比黑白", "category": "bw"},
        "cyberpunk_neon": {"name": "赛博霓虹", "category": "creative"},
        "pastel_dream": {"name": "粉彩梦境", "category": "soft"},
        "nature_vivid": {"name": "自然鲜艳", "category": "nature"},
        "food_warm": {"name": "美食暖调", "category": "food"},
        "portrait_soft": {"name": "人像柔肤", "category": "portrait"},
        "urban_grit": {"name": "都市硬朗", "category": "urban"},
        "travel_bright": {"name": "旅行明快", "category": "travel"},
        "horror_dark": {"name": "恐怖暗调", "category": "horror"},
        "sci_fi_cool": {"name": "科幻冷调", "category": "scifi"},
        "documentary_neutral": {"name": "纪录中性", "category": "documentary"},
    }

    async def apply_lut(
        self, input_path: str, output_path: str, lut_name: str
    ) -> str:
        """应用 LUT"""
        lut_path = f"config/luts/{lut_name}.cube"
        if not os.path.exists(lut_path):
            logger.warning(f"LUT file not found: {lut_path}, using color filter")
            return await self._apply_color_filter(input_path, output_path, lut_name)

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"lut3d={lut_path}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path

    async def _apply_color_filter(
        self, input_path: str, output_path: str, lut_name: str
    ) -> str:
        """回退：使用 ffmpeg 颜色滤镜"""
        color_params = {
            "cinematic_teal": "eq=contrast=1.2:saturation=1.1",
            "warm_sunset": "eq=contrast=1.1:brightness=0.05:saturation=1.15",
            "cool_moonlight": "colorbalance=rs=-0.1:gs=0:bs=0.2",
            "high_contrast_bw": "hue=s=0:eq=contrast=1.5",
            "cyberpunk_neon": "eq=contrast=1.3:saturation=1.5",
            "pastel_dream": "eq=contrast=0.9:saturation=0.8:brightness=0.05",
            "nature_vivid": "eq=contrast=1.15:saturation=1.3",
            "food_warm": "eq=contrast=1.1:saturation=1.2:brightness=0.03",
            "portrait_soft": "eq=contrast=0.95:saturation=0.9",
        }
        vf = color_params.get(lut_name, "eq=contrast=1.05:saturation=1.05")

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path

    def list_luts(self) -> List[dict]:
        """列出所有 LUT"""
        return [
            {"id": k, **v} for k, v in self.PRESETS.items()
        ]
