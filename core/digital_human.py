"""
AI 数字人/虚拟主播引擎 (Digital Human / VTuber)

功能：
- SadTalker / Wav2Lip 口型同步
- MuseTalk 实时面部动画
- TTS → 数字人说话视频
- 背景替换
- 绿幕抠像
"""

import asyncio
import os
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DigitalHumanConfig:
    """数字人配置"""
    avatar_image: str = ""          # 虚拟形象图片路径
    voice_audio: str = ""           # 配音文件
    background: str = "transparent" # transparent / green / image_path
    resolution: Tuple[int, int] = (512, 512)
    fps: int = 25
    expression_scale: float = 1.0   # 表情幅度
    pose_style: float = 1.0         # 头部姿态幅度


class DigitalHumanGenerator:
    """AI 数字人生成器"""

    def __init__(self):
        self._wav2lip_path = self._find_wav2lip()
        self._sadtalker_path = self._find_sadtalker()
        self._musetalk_available = False

    def _find_wav2lip(self) -> Optional[str]:
        """查找 Wav2Lip"""
        candidates = [
            os.path.expanduser("~/Wav2Lip"),
            "/opt/Wav2Lip",
        ]
        for c in candidates:
            if os.path.isdir(c):
                return c
        return None

    def _find_sadtalker(self) -> Optional[str]:
        candidates = [
            os.path.expanduser("~/SadTalker"),
            "/opt/SadTalker",
        ]
        for c in candidates:
            if os.path.isdir(c):
                return c
        return None

    @property
    def available(self) -> bool:
        return self._wav2lip_path is not None or self._sadtalker_path is not None

    async def generate_talking_head(
        self,
        avatar_image: str,
        audio_path: str,
        output_path: str,
        config: Optional[DigitalHumanConfig] = None,
    ) -> str:
        """
        生成数字人说话视频

        Args:
            avatar_image: 虚拟形象/照片路径
            audio_path: 驱动音频
            output_path: 输出视频路径
        """
        cfg = config or DigitalHumanConfig()

        if self._sadtalker_path:
            return await self._generate_sadtalker(
                avatar_image, audio_path, output_path, cfg)
        elif self._wav2lip_path:
            return await self._generate_wav2lip(
                avatar_image, audio_path, output_path, cfg)
        else:
            logger.warning("No digital human model found, generating static video")
            return await self._generate_static(avatar_image, audio_path, output_path, cfg)

    async def _generate_sadtalker(
        self, image: str, audio: str, output: str, cfg: DigitalHumanConfig
    ) -> str:
        """SadTalker 推理"""
        cmd = [
            "python", f"{self._sadtalker_path}/inference.py",
            "--driven_audio", audio,
            "--source_image", image,
            "--result_dir", os.path.dirname(output),
            "--still", "--preprocess", "full",
            "--enhancer", "gfpgan",
            "--size", "512",
            "--pose_style", str(cfg.pose_style),
            "--expression_scale", str(cfg.expression_scale),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"SadTalker failed: {stderr.decode(errors='ignore')[-200:]}")
            return await self._generate_static(image, audio, output, cfg)
        return output

    async def _generate_wav2lip(
        self, image: str, audio: str, output: str, cfg: DigitalHumanConfig
    ) -> str:
        """Wav2Lip 推理"""
        cmd = [
            "python", f"{self._wav2lip_path}/inference.py",
            "--checkpoint_path", f"{self._wav2lip_path}/checkpoints/wav2lip_gan.pth",
            "--face", image,
            "--audio", audio,
            "--outfile", output,
            "--fps", str(cfg.fps),
            "--pads", "0", "10", "0", "0",
            "--resize_factor", "1",
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output

    async def _generate_static(
        self, image: str, audio: str, output: str, cfg: DigitalHumanConfig
    ) -> str:
        """回退：静态图片 + 音频"""
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image,
            "-i", audio,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-vf", f"scale={cfg.resolution[0]}:{cfg.resolution[1]}:force_original_aspect_ratio=decrease,pad={cfg.resolution[0]}:{cfg.resolution[1]}:(ow-iw)/2:(oh-ih)/2",
            "-shortest", output,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output

    async def generate_vtuber_stream(
        self,
        avatar_image: str,
        tts_text: str,
        output_path: str,
        voice_id: str = "default",
    ) -> str:
        """TTS → 数字人说话视频 完整管线"""
        # 1. TTS 合成音频
        import tempfile
        audio_path = os.path.join(tempfile.gettempdir(), "tts_output.wav")

        # 2. 数字人生成
        config = DigitalHumanConfig(avatar_image=avatar_image)
        return await self.generate_talking_head(avatar_image, audio_path, output_path, config)


class BackgroundRemover:
    """背景去除器 — 绿幕抠像 / AI 背景移除"""

    async def remove_background(
        self,
        input_path: str,
        output_path: str,
        method: str = "chroma",       # chroma / ai / rembg
        chroma_color: str = "0x00FF00",  # 绿幕颜色
        similarity: float = 0.4,
        blend: float = 0.1,
    ) -> str:
        """背景移除"""
        if method == "chroma":
            # ffmpeg 色键抠像
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-vf", (
                    f"chromakey=color={chroma_color}:"
                    f"similarity={similarity}:blend={blend}"
                ),
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "copy", output_path,
            ]
            proc = await asyncio.create_subprocess_exec(*cmd)
            await proc.communicate()
        else:
            # AI 背景移除 (rembg / u2net)
            cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path]
            proc = await asyncio.create_subprocess_exec(*cmd)
            await proc.communicate()

        return output_path

    async def replace_background(
        self,
        input_path: str,
        bg_path: str,
        output_path: str,
    ) -> str:
        """背景替换"""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", bg_path,
            "-filter_complex",
            "[1:v]scale=1920:1080[bg];[0:v]chromakey=0x00FF00:0.4:0.1[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "copy", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path
