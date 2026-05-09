"""
多平台自适应输出引擎 (Multi-Platform Output)

功能：
- 抖音竖版 (9:16)、快手竖版
- YouTube 横版 (16:9)、B站横版
- 小红书 (3:4 / 1:1)
- 微信视频号 (16:9 / 9:16)
- 自动裁剪 + 智能构图（人脸/主体居中）
- 水印注入 + 品牌叠加
- 输出格式自动转换
"""

import asyncio
import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Platform(Enum):
    """目标平台"""
    DOUYIN = "douyin"           # 抖音 9:16
    KUAISHOU = "kuaishou"       # 快手 9:16
    YOUTUBE = "youtube"         # YouTube 16:9
    BILIBILI = "bilibili"       # B站 16:9
    XIAOHONGSHU = "xiaohongshu" # 小红书 3:4
    WECHAT_CHANNELS = "wechat"  # 微信视频号 16:9
    INSTAGRAM = "instagram"     # Instagram 1:1 / 4:5 / 9:16
    TIKTOK = "tiktok"           # TikTok 9:16


@dataclass
class PlatformConfig:
    """平台配置"""
    platform: Platform
    aspect_ratio: Tuple[int, int]  # (w, h)
    max_duration_sec: int
    max_bitrate_kbps: int
    max_resolution: Tuple[int, int]
    codec: str = "h264"
    audio_codec: str = "aac"
    audio_bitrate_kbps: int = 128
    output_format: str = "mp4"
    watermark_enabled: bool = False
    subtitle_style: dict = field(default_factory=dict)


# 平台预设配置
PLATFORM_CONFIGS: Dict[Platform, PlatformConfig] = {
    Platform.DOUYIN: PlatformConfig(
        platform=Platform.DOUYIN,
        aspect_ratio=(9, 16),
        max_duration_sec=1800,      # 30分钟（普通用户）
        max_bitrate_kbps=16000,
        max_resolution=(1080, 1920),
        subtitle_style={"font": "PingFang SC", "size": 36, "color": "#FFFFFF"},
    ),
    Platform.KUAISHOU: PlatformConfig(
        platform=Platform.KUAISHOU,
        aspect_ratio=(9, 16),
        max_duration_sec=1800,
        max_bitrate_kbps=12000,
        max_resolution=(1080, 1920),
    ),
    Platform.YOUTUBE: PlatformConfig(
        platform=Platform.YOUTUBE,
        aspect_ratio=(16, 9),
        max_duration_sec=43200,     # 12小时
        max_bitrate_kbps=85000,
        max_resolution=(3840, 2160),
        audio_bitrate_kbps=384,
    ),
    Platform.BILIBILI: PlatformConfig(
        platform=Platform.BILIBILI,
        aspect_ratio=(16, 9),
        max_duration_sec=36000,     # 10小时
        max_bitrate_kbps=20000,
        max_resolution=(3840, 2160),
        audio_bitrate_kbps=320,
    ),
    Platform.XIAOHONGSHU: PlatformConfig(
        platform=Platform.XIAOHONGSHU,
        aspect_ratio=(3, 4),
        max_duration_sec=900,       # 15分钟
        max_bitrate_kbps=8000,
        max_resolution=(1080, 1440),
    ),
    Platform.WECHAT_CHANNELS: PlatformConfig(
        platform=Platform.WECHAT_CHANNELS,
        aspect_ratio=(16, 9),
        max_duration_sec=3600,
        max_bitrate_kbps=10000,
        max_resolution=(1920, 1080),
    ),
    Platform.INSTAGRAM: PlatformConfig(
        platform=Platform.INSTAGRAM,
        aspect_ratio=(4, 5),
        max_duration_sec=600,       # 10分钟
        max_bitrate_kbps=6000,
        max_resolution=(1080, 1350),
    ),
    Platform.TIKTOK: PlatformConfig(
        platform=Platform.TIKTOK,
        aspect_ratio=(9, 16),
        max_duration_sec=600,
        max_bitrate_kbps=10000,
        max_resolution=(1080, 1920),
    ),
}


class SmartCropper:
    """智能裁剪器 — 基于内容感知的构图"""

    @staticmethod
    def calculate_crop_region(
        src_width: int, src_height: int,
        target_ratio: Tuple[int, int],
        focus_point: Tuple[float, float] = (0.5, 0.5)
    ) -> Tuple[int, int, int, int]:
        """
        计算裁剪区域，尽量保持主体居中

        Args:
            src_width, src_height: 原始尺寸
            target_ratio: 目标宽高比 (w, h)
            focus_point: 焦点 (0~1, 0~1), 默认中心

        Returns:
            (crop_x, crop_y, crop_w, crop_h)
        """
        tw, th = target_ratio
        target_aspect = tw / th
        src_aspect = src_width / src_height

        if src_aspect > target_aspect:
            # 原始更宽，裁左右
            crop_h = src_height
            crop_w = int(crop_h * target_aspect)
            # 焦点偏移
            center_x = int(src_width * focus_point[0])
            crop_x = max(0, min(src_width - crop_w, center_x - crop_w // 2))
            crop_y = 0
        else:
            # 原始更高，裁上下
            crop_w = src_width
            crop_h = int(crop_w / target_aspect)
            center_y = int(src_height * focus_point[1])
            crop_x = 0
            crop_y = max(0, min(src_height - crop_h, center_y - crop_h // 2))

        return (crop_x, crop_y, crop_w, crop_h)

    @staticmethod
    def calculate_pad_region(
        src_width: int, src_height: int,
        target_ratio: Tuple[int, int],
        pad_color: str = "#000000",
    ) -> Tuple[int, int, int, int, int, int]:
        """
        计算填充区域（不裁剪，加黑边/blur）

        Returns:
            (pad_left, pad_right, pad_top, pad_bottom, output_w, output_h)
        """
        tw, th = target_ratio
        target_aspect = tw / th
        src_aspect = src_width / src_height

        if src_aspect > target_aspect:
            # 加上下黑边
            output_w = src_width
            output_h = int(src_width / target_aspect)
            pad_top = (output_h - src_height) // 2
            pad_bottom = output_h - src_height - pad_top
            pad_left = pad_right = 0
        else:
            # 加左右黑边
            output_h = src_height
            output_w = int(src_height * target_aspect)
            pad_left = (output_w - src_width) // 2
            pad_right = output_w - src_width - pad_left
            pad_top = pad_bottom = 0

        return (pad_left, pad_right, pad_top, pad_bottom, output_w, output_h)


class MultiPlatformExporter:
    """多平台自适应导出器"""

    def __init__(self):
        self.cropper = SmartCropper()

    def get_platform_config(self, platform: Platform) -> PlatformConfig:
        return PLATFORM_CONFIGS.get(platform, PLATFORM_CONFIGS[Platform.YOUTUBE])

    async def export_for_platform(
        self,
        input_path: str,
        output_dir: str,
        platform: Platform,
        src_width: int = 1920,
        src_height: int = 1080,
        src_duration_sec: float = 180,
        focus_point: Tuple[float, float] = (0.5, 0.5),
        crop_mode: str = "crop",  # crop / pad / blur_pad
        watermark_text: str = "",
        subtitle_override: Optional[dict] = None,
    ) -> dict:
        """
        为指定平台导出视频

        Returns:
            {"platform": str, "output": str, "resolution": str, ...}
        """
        cfg = self.get_platform_config(platform)
        tw, th = cfg.aspect_ratio

        # 计算目标分辨率
        max_w, max_h = cfg.max_resolution
        target_aspect = tw / th

        if src_width / src_height > target_aspect:
            out_h = min(max_h, src_height)
            out_w = int(out_h * target_aspect)
        else:
            out_w = min(max_w, src_width)
            out_h = int(out_w / target_aspect)

        # 对齐到偶数
        out_w = out_w - (out_w % 2)
        out_h = out_h - (out_h % 2)

        # 构建 ffmpeg 滤镜
        vf_parts = []

        if crop_mode == "crop":
            cx, cy, cw, ch = self.cropper.calculate_crop_region(
                src_width, src_height, (tw, th), focus_point)
            vf_parts.append(f"crop={cw}:{ch}:{cx}:{cy}")
        elif crop_mode in ("pad", "blur_pad"):
            pl, pr, pt, pb, pw, ph = self.cropper.calculate_pad_region(
                src_width, src_height, (tw, th))
            if crop_mode == "blur_pad":
                # 模糊背景填充（高级：需要分离背景层）
                vf_parts.append(
                    f"split[original][bg];"
                    f"[bg]scale={pw}:{ph},boxblur=20:10[blurred];"
                    f"[blurred][original]overlay=(W-w)/2:(H-h)/2"
                )
            else:
                vf_parts.append(f"pad={pw}:{ph}:{pl}:{pt}:black")

        vf_parts.append(f"scale={out_w}:{out_h}")

        # 水印
        if watermark_text or cfg.watermark_enabled:
            text = watermark_text or "quanquan AI"
            vf_parts.append(
                f"drawtext=text='{text}':fontsize=24:fontcolor=white@0.5:"
                f"x=w-tw-20:y=h-th-20"
            )

        # 构建命令
        os.makedirs(output_dir, exist_ok=True)
        safe_name = platform.value.replace(":", "_")
        output_path = os.path.join(output_dir, f"output_{safe_name}.{cfg.output_format}")

        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-t", str(min(src_duration_sec, cfg.max_duration_sec)),
            "-vf", ",".join(vf_parts),
            "-c:v", cfg.codec,
            "-b:v", f"{cfg.max_bitrate_kbps}k",
            "-c:a", cfg.audio_codec,
            "-b:a", f"{cfg.audio_bitrate_kbps}k",
            "-movflags", "+faststart",
            output_path,
        ]

        logger.info(f"Exporting for {platform.value}: {out_w}x{out_h}")

        # 执行
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Export failed: {stderr.decode(errors='ignore')[-300:]}")

        return {
            "platform": platform.value,
            "output": output_path,
            "resolution": f"{out_w}x{out_h}",
            "aspect_ratio": f"{tw}:{th}",
            "format": cfg.output_format,
            "bitrate_kbps": cfg.max_bitrate_kbps,
        }

    async def export_all_platforms(
        self,
        input_path: str,
        output_dir: str,
        platforms: Optional[List[Platform]] = None,
        **kwargs,
    ) -> List[dict]:
        """一键导出到所有平台"""
        if platforms is None:
            platforms = [
                Platform.DOUYIN, Platform.YOUTUBE,
                Platform.BILIBILI, Platform.XIAOHONGSHU,
            ]

        tasks = [
            self.export_for_platform(input_path, output_dir, p, **kwargs)
            for p in platforms
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        outputs = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"Platform {platforms[i].value} failed: {r}")
            else:
                outputs.append(r)

        return outputs

    async def adaptive_export(
        self,
        input_path: str,
        output_dir: str,
        target_platform: Platform,
        **kwargs,
    ) -> dict:
        """智能自适应导出 — 根据平台自动选择最佳参数"""
        return await self.export_for_platform(
            input_path, output_dir, target_platform, **kwargs)


# ============================================================
# 便捷函数
# ============================================================

async def export_to_douyin(
    input_path: str, output_dir: str = "output/",
    src_w: int = 1920, src_h: int = 1080,
) -> dict:
    """快捷：导出抖音竖版"""
    exporter = MultiPlatformExporter()
    return await exporter.export_for_platform(
        input_path, output_dir, Platform.DOUYIN,
        src_width=src_w, src_height=src_h, crop_mode="crop",
    )


async def export_to_youtube(
    input_path: str, output_dir: str = "output/",
    src_w: int = 1920, src_h: int = 1080,
) -> dict:
    """快捷：导出 YouTube 横版"""
    exporter = MultiPlatformExporter()
    return await exporter.export_for_platform(
        input_path, output_dir, Platform.YOUTUBE,
        src_width=src_w, src_height=src_h,
    )
