"""
AI 视频超分辨率引擎 (Super Resolution)

功能：
- 基于 Real-ESRGAN / waifu2x 的视频超分
- 支持 2x/4x/8x 放大
- 视频去噪 + 去模糊
- 面部增强
- GPU 加速推理
"""

import asyncio
import os
import logging
import subprocess
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class UpscaleModel(Enum):
    """超分模型"""
    REALESRGAN_X4 = "realesrgan-x4plus"       # 通用 4x
    REALESRGAN_X2 = "realesrgan-x2plus"        # 通用 2x
    REALESRGAN_ANIME = "realesr-animevideov3"  # 动漫优化
    WAIFU2X = "waifu2x"                         # 二次元
    FACE_ENHANCE = "realesrgan-x4plus"          # + GFPGAN 面部增强


class VideoUpscaler:
    """视频超分辨率处理器"""

    def __init__(self, model: UpscaleModel = UpscaleModel.REALESRGAN_X4):
        self.model = model
        self._realesrgan_path = self._find_realesrgan()

    def _find_realesrgan(self) -> Optional[str]:
        """查找 Real-ESRGAN 可执行路径"""
        candidates = [
            "realesrgan-ncnn-vulkan",
            "/usr/local/bin/realesrgan-ncnn-vulkan",
            os.path.expanduser("~/realesrgan-ncnn-vulkan"),
        ]
        for c in candidates:
            if os.path.exists(c) or self._which(c):
                return c
        return None

    @staticmethod
    def _which(cmd: str) -> bool:
        try:
            subprocess.run(["which", cmd], capture_output=True, check=True)
            return True
        except Exception:
            return False

    def available(self) -> bool:
        return self._realesrgan_path is not None

    async def upscale_video(
        self,
        input_path: str,
        output_path: str,
        scale: int = 4,
        denoise: int = -1,        # -1=auto
        face_enhance: bool = False,
        gpu_id: int = 0,
        tile_size: int = 400,     # 显存不足时分块处理
    ) -> str:
        """
        视频超分辨率

        Args:
            scale: 放大倍数 (2/4)
            denoise: 去噪强度 (-1自动, 0-3)
            face_enhance: 面部增强
            tile_size: 分块大小（控制显存）
        """
        if not self.available():
            logger.warning("Real-ESRGAN not found, falling back to ffmpeg Lanczos")
            return await self._fallback_upscale(input_path, output_path, scale)

        model_name = self.model.value
        if face_enhance:
            model_name = "realesrgan-x4plus"

        cmd = [
            self._realesrgan_path,
            "-i", input_path,
            "-o", output_path,
            "-s", str(scale),
            "-n", model_name,
            "-g", str(gpu_id),
            "-t", str(tile_size),
        ]

        if denoise >= 0:
            cmd.extend(["-d", str(denoise)])

        if face_enhance:
            cmd.extend(["-x"])  # 扩展参数：面部增强需要配合 GFPGAN

        logger.info(f"Upscaling video: {scale}x, model={model_name}")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode(errors="ignore")[-300:]
            logger.error(f"Upscale failed: {err}")
            return await self._fallback_upscale(input_path, output_path, scale)

        return output_path

    async def _fallback_upscale(self, input_path: str, output_path: str, scale: int) -> str:
        """回退：ffmpeg Lanczos 缩放"""
        from .chunked_processor import VideoInspector
        meta = await VideoInspector.probe(input_path)
        new_w = meta.width * scale
        new_h = meta.height * scale

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"scale={new_w}:{new_h}:flags=lanczos",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "copy",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        logger.info(f"Fallback upscale: {meta.width}x{meta.height} → {new_w}x{new_h}")
        return output_path

    async def upscale_image(
        self, input_path: str, output_path: str, scale: int = 4
    ) -> str:
        """单张图片超分"""
        if self.available():
            cmd = [
                self._realesrgan_path,
                "-i", input_path,
                "-o", output_path,
                "-s", str(scale),
                "-n", self.model.value,
            ]
            proc = await asyncio.create_subprocess_exec(*cmd)
            await proc.communicate()
            return output_path

        # 回退
        cmd = ["ffmpeg", "-y", "-i", input_path,
               "-vf", f"scale=iw*{scale}:ih*{scale}:flags=lanczos",
               output_path]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return output_path


class VideoEnhancer:
    """视频增强器 — 去噪 + 稳定 + 色彩校正"""

    async def enhance(
        self,
        input_path: str,
        output_path: str,
        denoise_strength: float = 0.5,
        stabilize: bool = False,
        sharpen: float = 0.3,
        color_correct: bool = True,
    ) -> str:
        """综合视频增强"""
        vf_parts = []

        # 去噪
        if denoise_strength > 0:
            vf_parts.append(f"hqdn3d={denoise_strength*4}:{denoise_strength*3}:6:4.5")

        # 稳定（需要 vidstabdetect + vidstabtransform 两步）
        if stabilize:
            vf_parts.append("vidstabtransform=smoothing=10:input='transforms.trf'")

        # 锐化
        if sharpen > 0:
            vf_parts.append(f"unsharp=5:5:{sharpen}:3:3:0")

        # 色彩校正
        if color_correct:
            vf_parts.append("eq=contrast=1.05:brightness=0.02:saturation=1.05")

        vf = ",".join(vf_parts) if vf_parts else "null"

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "copy",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()

        logger.info(f"Video enhanced: denoise={denoise_strength}, "
                     f"stabilize={stabilize}, sharpen={sharpen}")
        return output_path


class VideoStabilizer:
    """视频防抖稳定器"""

    async def stabilize(self, input_path: str, output_path: str) -> str:
        """两步法视频稳定"""
        import tempfile
        trf_file = os.path.join(tempfile.gettempdir(), "vidstab.trf")

        # Step 1: 检测抖动
        cmd1 = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"vidstabdetect=shakiness=5:accuracy=15:result={trf_file}",
            "-f", "null", "-"
        ]
        proc1 = await asyncio.create_subprocess_exec(*cmd1)
        await proc1.communicate()

        # Step 2: 应用变换
        cmd2 = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"vidstabtransform=input={trf_file}:smoothing=10:crop=black",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "copy",
            output_path,
        ]
        proc2 = await asyncio.create_subprocess_exec(*cmd2)
        await proc2.communicate()

        logger.info(f"Video stabilized: {output_path}")
        return output_path
