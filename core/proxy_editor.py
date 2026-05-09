"""
quanquan 代理剪辑引擎 (Proxy Editing)

原理：
1. 对高分辨率素材（4K/8K）生成低分辨率代理（720p）
2. 编辑/预览时使用代理文件，保证流畅
3. 最终导出时自动替换为原始高分辨率素材
4. 支持代理/原始文件的自动映射管理

优势：
- 4K视频在普通硬件上流畅编辑
- 代理文件体积小（~1/16），磁盘友好
- 导出时零质量损失（切回原始素材）
"""

import os
import json
import hashlib
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class ProxyStatus(Enum):
    """代理文件状态"""
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"
    NOT_NEEDED = "not_needed"  # 分辨率低，不需要代理


@dataclass
class ProxyMapping:
    """代理文件映射"""
    original_path: str
    proxy_path: str
    original_width: int
    original_height: int
    proxy_width: int
    proxy_height: int
    original_size_bytes: int
    proxy_size_bytes: int
    status: ProxyStatus = ProxyStatus.PENDING
    created_at: str = ""
    checksum: str = ""  # 原始文件 checksum，用于验证一致性

    @property
    def size_ratio(self) -> float:
        """代理/原始大小比"""
        if self.original_size_bytes == 0:
            return 0
        return self.proxy_size_bytes / self.original_size_bytes

    @property
    def resolution_label(self) -> str:
        return f"{self.original_width}x{self.original_height} → {self.proxy_width}x{self.proxy_height}"


@dataclass
class ProxyConfig:
    """代理配置"""
    proxy_resolution: int = 720          # 代理目标分辨率（取较小边）
    proxy_codec: str = "h264"            # 代理编码格式
    proxy_crf: int = 28                  # 代理质量（越高压缩越大）
    proxy_fps: Optional[float] = None    # 代理帧率（None=保持原样）
    proxy_audio_codec: str = "aac"
    proxy_audio_bitrate: int = 128       # kbps
    auto_proxy_threshold_width: int = 1920  # 超过此宽度的素材自动代理
    proxy_dir: str = "proxy/"            # 代理文件存储目录（相对输出目录）
    enable_cache: bool = True            # 是否缓存代理文件
    max_concurrent_generations: int = 3  # 最大并发生成数


class ProxyGenerator:
    """代理文件生成器"""

    def __init__(self, config: Optional[ProxyConfig] = None):
        self.config = config or ProxyConfig()
        self._mappings: Dict[str, ProxyMapping] = {}
        self._mapping_file: str = ""

    def _get_proxy_filename(self, original_path: str) -> str:
        """为原始文件生成代理文件名（基于路径 MD5）"""
        path_hash = hashlib.md5(original_path.encode()).hexdigest()[:12]
        ext = os.path.splitext(original_path)[1] or ".mp4"
        return f"proxy_{path_hash}{ext}"

    def _get_checksum(self, filepath: str) -> str:
        """快速文件 checksum（取头尾1KB）"""
        try:
            size = os.path.getsize(filepath)
            with open(filepath, "rb") as f:
                head = f.read(1024)
                if size > 2048:
                    f.seek(size - 1024)
                    tail = f.read(1024)
                else:
                    tail = b""
            return hashlib.md5(head + tail).hexdigest()
        except OSError:
            return ""

    def needs_proxy(self, filepath: str, width: int, height: int) -> bool:
        """判断素材是否需要代理"""
        return max(width, height) > self.config.proxy_resolution

    async def generate(
        self,
        original_path: str,
        output_dir: str,
        width: int,
        height: int,
        force: bool = False,
    ) -> ProxyMapping:
        """
        为原始素材生成代理文件

        Args:
            original_path: 原始素材路径
            output_dir: 输出目录
            width/height: 原始分辨率
            force: 强制重新生成

        Returns:
            ProxyMapping 对象
        """
        # 检查缓存
        cache_key = f"{original_path}:{width}x{height}"
        if not force and cache_key in self._mappings:
            cached = self._mappings[cache_key]
            if cached.status == ProxyStatus.READY and os.path.exists(cached.proxy_path):
                return cached

        if not self.needs_proxy(original_path, width, height):
            return ProxyMapping(
                original_path=original_path,
                proxy_path=original_path,
                original_width=width,
                original_height=height,
                proxy_width=width,
                proxy_height=height,
                original_size_bytes=os.path.getsize(original_path),
                proxy_size_bytes=os.path.getsize(original_path),
                status=ProxyStatus.NOT_NEEDED,
            )

        # 创建代理目录
        proxy_dir = os.path.join(output_dir, self.config.proxy_dir)
        os.makedirs(proxy_dir, exist_ok=True)

        proxy_filename = self._get_proxy_filename(original_path)
        proxy_path = os.path.join(proxy_dir, proxy_filename)

        # 计算代理分辨率（保持宽高比）
        scale = self.config.proxy_resolution / max(width, height)
        proxy_width = int(width * scale)
        proxy_height = int(height * scale)
        # 对齐到偶数（编码器要求）
        proxy_width = proxy_width - (proxy_width % 2)
        proxy_height = proxy_height - (proxy_height % 2)

        # 创建映射（标记生成中）
        mapping = ProxyMapping(
            original_path=original_path,
            proxy_path=proxy_path,
            original_width=width,
            original_height=height,
            proxy_width=proxy_width,
            proxy_height=proxy_height,
            original_size_bytes=os.path.getsize(original_path),
            proxy_size_bytes=0,
            status=ProxyStatus.GENERATING,
            checksum=self._get_checksum(original_path),
        )
        self._mappings[cache_key] = mapping

        # 使用 ffmpeg 生成代理
        try:
            from .gpu_encoder import GPUEncoder, EncodeConfig, EncoderPreset
            encoder = GPUEncoder()
            await encoder.ensure_gpus_detected()

            config = EncodeConfig(
                codec=self.config.proxy_codec,
                preset=EncoderPreset.ULTRAFAST,
                crf=self.config.proxy_crf,
                width=proxy_width,
                height=proxy_height,
                fps=self.config.proxy_fps,
                audio_codec=self.config.proxy_audio_codec,
                audio_bitrate_kbps=self.config.proxy_audio_bitrate,
                use_hw_encode=True,
            )
            await encoder.encode(original_path, proxy_path, config)

            mapping.proxy_size_bytes = os.path.getsize(proxy_path)
            mapping.status = ProxyStatus.READY
            mapping.created_at = str(Path(proxy_path).stat().st_mtime)

            ratio = mapping.size_ratio
            logger.info(f"Proxy generated: {mapping.resolution_label} "
                       f"({mapping.proxy_size_bytes/1e6:.1f}MB, {ratio:.1%} of original)")

        except Exception as e:
            mapping.status = ProxyStatus.FAILED
            logger.error(f"Proxy generation failed for {original_path}: {e}")
            # 失败时回退到原始文件
            mapping.proxy_path = original_path

        return mapping

    async def batch_generate(
        self,
        files: List[Tuple[str, int, int]],  # [(path, width, height), ...]
        output_dir: str,
        force: bool = False,
    ) -> List[ProxyMapping]:
        """批量生成代理文件"""
        semaphore = asyncio.Semaphore(self.config.max_concurrent_generations)

        async def gen_one(path, w, h):
            async with semaphore:
                return await self.generate(path, output_dir, w, h, force)

        tasks = [gen_one(p, w, h) for p, w, h in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        mappings = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"Batch proxy failed for {files[i][0]}: {r}")
                mappings.append(ProxyMapping(
                    original_path=files[i][0],
                    proxy_path=files[i][0],
                    original_width=files[i][1],
                    original_height=files[i][2],
                    proxy_width=files[i][1],
                    proxy_height=files[i][2],
                    original_size_bytes=0,
                    proxy_size_bytes=0,
                    status=ProxyStatus.FAILED,
                ))
            else:
                mappings.append(r)

        return mappings

    def save_mappings(self, filepath: str):
        """保存代理映射到 JSON（供后续使用）"""
        data = {
            "version": 1,
            "mappings": {
                k: {
                    "original_path": m.original_path,
                    "proxy_path": m.proxy_path,
                    "original_width": m.original_width,
                    "original_height": m.original_height,
                    "proxy_width": m.proxy_width,
                    "proxy_height": m.proxy_height,
                    "original_size_bytes": m.original_size_bytes,
                    "proxy_size_bytes": m.proxy_size_bytes,
                    "status": m.status.value,
                    "created_at": m.created_at,
                    "checksum": m.checksum,
                }
                for k, m in self._mappings.items()
            }
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._mapping_file = filepath
        logger.info(f"Proxy mappings saved: {len(self._mappings)} entries → {filepath}")

    def load_mappings(self, filepath: str):
        """从 JSON 恢复代理映射"""
        with open(filepath, "r") as f:
            data = json.load(f)
        self._mappings = {}
        for k, m in data.get("mappings", {}).items():
            self._mappings[k] = ProxyMapping(
                original_path=m["original_path"],
                proxy_path=m["proxy_path"],
                original_width=m["original_width"],
                original_height=m["original_height"],
                proxy_width=m["proxy_width"],
                proxy_height=m["proxy_height"],
                original_size_bytes=m["original_size_bytes"],
                proxy_size_bytes=m["proxy_size_bytes"],
                status=ProxyStatus(m["status"]),
                created_at=m.get("created_at", ""),
                checksum=m.get("checksum", ""),
            )
        self._mapping_file = filepath

    def resolve(self, original_path: str, width: int, height: int) -> str:
        """
        解析文件路径：编辑时返回代理路径，导出时返回原始路径

        用法：在最终编码时调用 resolve_for_export()，在预览时调用 resolve()
        """
        cache_key = f"{original_path}:{width}x{height}"
        mapping = self._mappings.get(cache_key)
        if mapping and mapping.status == ProxyStatus.READY:
            # 验证 checksum，如果原始文件变了则重新生成
            if self.config.enable_cache:
                current_checksum = self._get_checksum(original_path)
                if current_checksum == mapping.checksum:
                    return mapping.proxy_path
            else:
                return mapping.proxy_path
        return original_path

    def resolve_for_export(self, original_path: str) -> str:
        """导出时始终返回原始文件路径"""
        return original_path

    def get_stats(self) -> Dict:
        """获取代理文件统计"""
        ready = sum(1 for m in self._mappings.values() if m.status == ProxyStatus.READY)
        total_original = sum(m.original_size_bytes for m in self._mappings.values())
        total_proxy = sum(m.proxy_size_bytes for m in self._mappings.values())
        return {
            "total_mappings": len(self._mappings),
            "ready": ready,
            "generating": sum(1 for m in self._mappings.values() if m.status == ProxyStatus.GENERATING),
            "failed": sum(1 for m in self._mappings.values() if m.status == ProxyStatus.FAILED),
            "total_original_gb": total_original / 1024**3,
            "total_proxy_gb": total_proxy / 1024**3,
            "saved_gb": (total_original - total_proxy) / 1024**3,
            "saved_ratio": 1 - (total_proxy / total_original) if total_original > 0 else 0,
        }


class ProxyAwareFFmpeg:
    """
    代理感知的 FFmpeg 封装

    在编辑/预览阶段自动使用代理文件；
    在最终导出阶段自动切换回原始文件。
    """

    def __init__(self, proxy_generator: ProxyGenerator):
        self.proxy = proxy_generator
        self._is_export_mode = False

    def set_export_mode(self, export: bool = True):
        """切换为导出模式（使用原始文件）"""
        self._is_export_mode = export

    def resolve_path(self, filepath: str, width: int = 0, height: int = 0) -> str:
        """根据模式自动选择代理或原始文件"""
        if self._is_export_mode:
            return self.proxy.resolve_for_export(filepath)
        return self.proxy.resolve(filepath, width, height)


# ============================================================
# 便捷函数
# ============================================================

_proxy_cache: Dict[str, ProxyGenerator] = {}


async def get_proxy_generator(
    output_dir: str, config: Optional[ProxyConfig] = None
) -> ProxyGenerator:
    """获取或创建代理生成器（每个 output_dir 一个）"""
    global _proxy_cache
    if output_dir not in _proxy_cache:
        gen = ProxyGenerator(config)
        # 尝试加载已有映射
        mapping_file = os.path.join(output_dir, "proxy_mappings.json")
        if os.path.exists(mapping_file):
            gen.load_mappings(mapping_file)
        _proxy_cache[output_dir] = gen
    return _proxy_cache[output_dir]
