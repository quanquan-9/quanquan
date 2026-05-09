"""
quanquan GPU 加速编码引擎

支持：
- NVIDIA NVENC/NVDEC（通过 ffmpeg hwaccel）
- Intel QSV（Quick Sync Video）
- AMD AMF
- 自动检测可用 GPU 并选择最佳编码器
- 硬件解码 → 滤镜处理 → 硬件编码的零拷贝管线
"""

import asyncio
import subprocess
import json
import os
import logging
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class GPUType(Enum):
    NVIDIA = "nvidia"
    INTEL = "intel"
    AMD = "amd"
    NONE = "none"


class EncoderPreset(Enum):
    """编码质量/速度预设"""
    ULTRAFAST = "ultrafast"
    VERYFAST = "veryfast"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    LOSSLESS = "lossless"


@dataclass
class GPUInfo:
    """GPU 信息"""
    gpu_type: GPUType
    name: str
    driver_version: str
    vram_mb: int
    cuda_cores: int = 0
    encoder_name: str = ""

    @property
    def available(self) -> bool:
        return self.gpu_type != GPUType.NONE


@dataclass
class EncodeConfig:
    """编码配置"""
    codec: str = "h264"              # h264 / h265 (hevc) / av1
    preset: EncoderPreset = EncoderPreset.FAST
    crf: int = 20                    # 0-51, lower = better quality
    bitrate_kbps: Optional[int] = None
    max_bitrate_kbps: Optional[int] = None
    width: Optional[int] = None      # 输出分辨率（None=保持原样）
    height: Optional[int] = None
    fps: Optional[float] = None
    audio_codec: str = "aac"
    audio_bitrate_kbps: int = 256
    hdr: bool = False                # HDR10 输出
    use_hw_decode: bool = True       # 硬件解码
    use_hw_encode: bool = True       # 硬件编码
    gpu_index: int = 0               # 多GPU时选择


class GPUDetector:
    """GPU 自动检测"""

    @staticmethod
    async def detect() -> List[GPUInfo]:
        """检测系统中所有可用 GPU"""
        gpus = []

        # 1. 检测 NVIDIA GPU
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                for line in stdout.decode().strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        gpus.append(GPUInfo(
                            gpu_type=GPUType.NVIDIA,
                            name=parts[0],
                            driver_version=parts[1],
                            vram_mb=int(float(parts[2])),
                            encoder_name="h264_nvenc",
                        ))
                logger.info(f"Detected {len(gpus)} NVIDIA GPU(s)")
        except FileNotFoundError:
            pass

        # 2. 检测 Intel QSV
        try:
            proc = await asyncio.create_subprocess_exec(
                "vainfo", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and "iHD" in stdout.decode():
                gpus.append(GPUInfo(
                    gpu_type=GPUType.INTEL,
                    name="Intel Quick Sync",
                    driver_version="iHD",
                    vram_mb=0,  # 共享内存
                    encoder_name="h264_qsv",
                ))
                logger.info("Detected Intel QSV GPU")
        except FileNotFoundError:
            pass

        # 3. 检测 AMD AMF
        try:
            proc = await asyncio.create_subprocess_exec(
                "rocm-smi", "--showproductname",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout.decode().strip():
                gpus.append(GPUInfo(
                    gpu_type=GPUType.AMD,
                    name=stdout.decode().strip(),
                    driver_version="ROCm",
                    vram_mb=0,
                    encoder_name="h264_amf",
                ))
                logger.info("Detected AMD GPU via ROCm")
        except FileNotFoundError:
            pass

        return gpus

    @staticmethod
    async def get_best_encoder(available_gpus: List[GPUInfo], codec: str = "h264") -> str:
        """获取当前最优的硬件编码器名称"""
        # 默认软件编码器
        codec_map = {
            "h264": "libx264",
            "h265": "libx265",
            "hevc": "libx265",
            "av1": "libaom-av1",
        }

        # NVENC 优先级最高（质量和速度最好）
        nvidia_codec_map = {
            "h264": "h264_nvenc",
            "h265": "hevc_nvenc",
            "hevc": "hevc_nvenc",
            "av1": "av1_nvenc",
        }
        intel_codec_map = {
            "h264": "h264_qsv",
            "h265": "hevc_qsv",
            "hevc": "hevc_qsv",
            "av1": "av1_qsv",
        }
        amd_codec_map = {
            "h264": "h264_amf",
            "h265": "hevc_amf",
            "hevc": "hevc_amf",
        }

        for gpu in available_gpus:
            if gpu.gpu_type == GPUType.NVIDIA and codec in nvidia_codec_map:
                return nvidia_codec_map[codec]
            elif gpu.gpu_type == GPUType.INTEL and codec in intel_codec_map:
                return intel_codec_map[codec]
            elif gpu.gpu_type == GPUType.AMD and codec in amd_codec_map:
                return amd_codec_map[codec]

        return codec_map.get(codec, "libx264")


class GPUEncoder:
    """GPU 加速编码器"""

    def __init__(self, config: Optional[EncodeConfig] = None):
        self.config = config or EncodeConfig()
        self._gpus: Optional[List[GPUInfo]] = None
        self._detector = GPUDetector()

    async def ensure_gpus_detected(self):
        """惰性检测 GPU"""
        if self._gpus is None:
            self._gpus = await self._detector.detect()

    async def encode(
        self,
        input_path: str,
        output_path: str,
        config: Optional[EncodeConfig] = None,
        filters: Optional[List[str]] = None,
        start_sec: Optional[float] = None,
        duration_sec: Optional[float] = None,
    ) -> str:
        """
        GPU 加速编码

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            config: 编码配置（覆盖默认）
            filters: ffmpeg 滤镜链
            start_sec: 起始时间（裁剪）
            duration_sec: 持续时长（裁剪）

        Returns:
            输出文件路径
        """
        await self.ensure_gpus_detected()
        cfg = config or self.config

        # 构建 ffmpeg 命令
        cmd = ["ffmpeg", "-y"]

        # --- 硬件解码 ---
        if cfg.use_hw_decode and self._gpus:
            gpu = self._gpus[cfg.gpu_index] if cfg.gpu_index < len(self._gpus) else None
            if gpu:
                hwaccel_map = {
                    GPUType.NVIDIA: ("cuda", "-hwaccel_output_format", "cuda"),
                    GPUType.INTEL: ("qsv", "-hwaccel_output_format", "qsv"),
                    GPUType.AMD: ("d3d11va",),
                }
                hw = hwaccel_map.get(gpu.gpu_type, ())
                if hw:
                    cmd.extend(["-hwaccel", hw[0]])
                    if len(hw) > 1:
                        cmd.extend(list(hw[1:]))

        # --- 起始时间 ---
        if start_sec is not None:
            cmd.extend(["-ss", str(start_sec)])

        # --- 输入 ---
        cmd.extend(["-i", input_path])

        # --- 时长 ---
        if duration_sec is not None:
            cmd.extend(["-t", str(duration_sec)])

        # --- 滤镜链 ---
        filter_parts = []

        # 硬件解码需要从 GPU 内存下载到系统内存做滤镜
        gpu = self._gpus[cfg.gpu_index] if self._gpus and cfg.gpu_index < len(self._gpus) else None
        if gpu and cfg.use_hw_decode:
            if gpu.gpu_type == GPUType.NVIDIA:
                filter_parts.append("hwdownload")
                filter_parts.append("format=nv12")

        # 分辨率缩放
        if cfg.width or cfg.height:
            scale = f"scale={cfg.width or -1}:{cfg.height or -1}"
            filter_parts.append(scale)

        # FPS
        if cfg.fps:
            filter_parts.append(f"fps={cfg.fps}")

        # 用户自定义滤镜
        if filters:
            filter_parts.extend(filters)

        # 硬件编码需要上传回 GPU
        if gpu and cfg.use_hw_encode:
            if gpu.gpu_type == GPUType.NVIDIA:
                filter_parts.append("format=nv12")
                filter_parts.append("hwupload")

        if filter_parts:
            cmd.extend(["-vf", ",".join(filter_parts)])

        # --- 编码器 ---
        if cfg.use_hw_encode and self._gpus:
            encoder = await self._detector.get_best_encoder(self._gpus, cfg.codec)
        else:
            codec_map = {"h264": "libx264", "h265": "libx265", "hevc": "libx265", "av1": "libaom-av1"}
            encoder = codec_map.get(cfg.codec, "libx264")

        cmd.extend(["-c:v", encoder])

        # --- 编码参数 ---
        if "nvenc" in encoder:
            # NVENC 特定参数
            cmd.extend([
                "-preset", "p4",    # p1(fastest) ~ p7(slowest)
                "-rc", "vbr" if cfg.bitrate_kbps else "constqp",
            ])
            if cfg.bitrate_kbps:
                cmd.extend(["-b:v", f"{cfg.bitrate_kbps}k"])
                if cfg.max_bitrate_kbps:
                    cmd.extend(["-maxrate", f"{cfg.max_bitrate_kbps}k"])
                    cmd.extend(["-bufsize", f"{cfg.max_bitrate_kbps * 2}k"])
            else:
                cmd.extend(["-qp", str(cfg.crf)])
            cmd.extend(["-temporal-aq", "1"])
            cmd.extend(["-spatial-aq", "1"])
            cmd.extend(["-rc-lookahead", "32"])

        elif "qsv" in encoder:
            cmd.extend(["-global_quality", str(cfg.crf)])
            cmd.extend(["-look_ahead", "1"])

        elif "amf" in encoder:
            cmd.extend(["-quality", "balanced"])
            cmd.extend(["-rc", "vbr_latency"])

        else:
            # 软件编码器
            cmd.extend(["-preset", cfg.preset.value])
            if cfg.bitrate_kbps:
                cmd.extend(["-b:v", f"{cfg.bitrate_kbps}k"])
            else:
                cmd.extend(["-crf", str(cfg.crf)])

        # --- 音频 ---
        cmd.extend(["-c:a", cfg.audio_codec])
        cmd.extend(["-b:a", f"{cfg.audio_bitrate_kbps}k"])

        # --- HDR ---
        if cfg.hdr:
            cmd.extend([
                "-color_primaries", "bt2020",
                "-color_trc", "smpte2084",
                "-colorspace", "bt2020nc",
            ])

        # --- 其他 ---
        cmd.extend(["-movflags", "+faststart"])  # Web 播放优化
        cmd.append(output_path)

        logger.info(f"GPU encode: {' '.join(cmd[:8])}...")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode(errors="ignore")[-500:]
            logger.error(f"GPU encode failed: {err}")
            raise RuntimeError(f"GPU encode failed: {err}")

        return output_path

    async def encode_fast_preview(
        self, input_path: str, output_path: str, max_resolution: int = 720
    ) -> str:
        """快速预览编码（低分辨率，高速度）"""
        import math
        from .chunked_processor import VideoInspector

        metadata = await VideoInspector.probe(input_path)
        scale = max_resolution / max(metadata.width, metadata.height)
        w = int(metadata.width * scale)
        h = int(metadata.height * scale)
        # 对齐到偶数
        w = w - (w % 2)
        h = h - (h % 2)

        config = EncodeConfig(
            codec="h264",
            preset=EncoderPreset.ULTRAFAST,
            crf=28,
            width=w,
            height=h,
            use_hw_encode=True,
        )
        return await self.encode(input_path, output_path, config)

    async def batch_encode(
        self,
        tasks: List[Tuple[str, str]],  # [(input, output), ...]
        config: Optional[EncodeConfig] = None,
        max_concurrent: int = 2,
    ) -> List[str]:
        """批量编码（受 GPU VRAM 限制并发数）"""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def encode_one(inp, out):
            async with semaphore:
                return await self.encode(inp, out, config)

        results = await asyncio.gather(
            *[encode_one(inp, out) for inp, out in tasks]
        )
        return list(results)


# ============================================================
# 便捷函数
# ============================================================

_gpu_encoder_cache: Optional[GPUEncoder] = None


async def get_encoder(config: Optional[EncodeConfig] = None) -> GPUEncoder:
    """获取全局 GPU 编码器实例"""
    global _gpu_encoder_cache
    if _gpu_encoder_cache is None:
        _gpu_encoder_cache = GPUEncoder(config)
        await _gpu_encoder_cache.ensure_gpus_detected()
    return _gpu_encoder_cache
