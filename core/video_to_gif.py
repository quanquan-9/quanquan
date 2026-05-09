"""
视频转 GIF / 动图生成器

功能：
- 视频片段 → 高质量 GIF/WebP
- 智能调色板优化
- 尺寸控制
- 批量生成
"""

import asyncio
import os
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class VideoToGIF:
    """视频转 GIF/WebP"""

    async def convert(
        self,
        input_path: str,
        output_path: str,
        start_sec: float = 0,
        duration_sec: float = 5.0,
        width: int = 480,
        fps: int = 15,
        quality: str = "high",  # high / medium / low
        output_format: str = "gif",  # gif / webp
    ) -> str:
        """视频片段 → GIF/WebP"""

        # 调色板生成（高质量 GIF 需要两步法）
        palette_path = os.path.join(os.path.dirname(output_path), "palette.png")

        crf_map = {"high": "18", "medium": "23", "low": "28"}

        # Step 1: 生成调色板
        cmd1 = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-t", str(duration_sec),
            "-i", input_path,
            "-vf", (
                f"fps={fps},scale={width}:-1:flags=lanczos,"
                f"palettegen=stats_mode=diff"
            ),
            palette_path,
        ]
        proc1 = await asyncio.create_subprocess_exec(*cmd1)
        await proc1.communicate()

        # Step 2: 生成 GIF
        if output_format == "gif":
            cmd2 = [
                "ffmpeg", "-y",
                "-ss", str(start_sec),
                "-t", str(duration_sec),
                "-i", input_path,
                "-i", palette_path,
                "-lavfi", (
                    f"fps={fps},scale={width}:-1:flags=lanczos[x];"
                    f"[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
                ),
                output_path,
            ]
        else:
            # WebP 动图 (更小体积)
            cmd2 = [
                "ffmpeg", "-y",
                "-ss", str(start_sec),
                "-t", str(duration_sec),
                "-i", input_path,
                "-vf", f"fps={fps},scale={width}:-1:flags=lanczos",
                "-c:v", "libwebp",
                "-lossless", "0",
                "-quality", {"high": "80", "medium": "60", "low": "40"}[quality],
                "-loop", "0",
                output_path,
            ]

        proc2 = await asyncio.create_subprocess_exec(*cmd2)
        await proc2.communicate()

        # 清理
        if os.path.exists(palette_path):
            os.remove(palette_path)

        size_kb = os.path.getsize(output_path) // 1024 if os.path.exists(output_path) else 0
        logger.info(f"GIF generated: {output_path} ({size_kb}KB, {width}w, {fps}fps)")
        return output_path

    async def convert_to_platform_gif(
        self,
        input_path: str,
        output_dir: str,
        platform: str = "wechat",  # wechat / weibo / twitter / telegram
    ) -> str:
        """按平台限制生成 GIF"""
        platform_limits = {
            "wechat": {"width": 360, "fps": 10, "max_size_mb": 1},
            "weibo": {"width": 440, "fps": 15, "max_size_mb": 5},
            "twitter": {"width": 480, "fps": 15, "max_size_mb": 5},
            "telegram": {"width": 320, "fps": 10, "max_size_mb": 1},
            "discord": {"width": 480, "fps": 15, "max_size_mb": 8},
        }

        limits = platform_limits.get(platform, platform_limits["wechat"])
        output_path = os.path.join(output_dir, f"output_{platform}.gif")

        return await self.convert(
            input_path, output_path,
            width=limits["width"],
            fps=limits["fps"],
            quality="medium" if limits["max_size_mb"] <= 1 else "high",
        )

    async def batch_convert(
        self,
        segments: list,  # [(input_path, start_sec, duration_sec), ...]
        output_dir: str,
        **kwargs,
    ) -> list:
        """批量转 GIF"""
        tasks = [
            self.convert(
                p, os.path.join(output_dir, f"gif_{i}.gif"),
                start_sec=s, duration_sec=d, **kwargs
            )
            for i, (p, s, d) in enumerate(segments)
        ]
        return await asyncio.gather(*tasks)
