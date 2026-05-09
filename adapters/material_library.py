"""
素材库引擎 (Material Library)

功能：
- 素材索引与元数据管理
- 语义搜索（基于 CLIP embedding）
- 素材版权追踪
- 美学评分
"""

import asyncio
import json
import os
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Material:
    """素材条目"""
    material_id: str
    path: str
    media_type: str          # video / image / audio
    duration_sec: float = 0
    width: int = 0
    height: int = 0
    fps: float = 30
    tags: List[str] = field(default_factory=list)
    license_type: str = "unknown"  # cc0 / commercial / custom
    source_url: str = ""
    aesthetic_score: float = 0.5
    embedding: Optional[List[float]] = None  # 512-dim CLIP
    metadata: Dict[str, Any] = field(default_factory=dict)
    indexed_at: str = ""
    usage_count: int = 0

    @property
    def resolution_label(self) -> str:
        if self.width >= 3840: return "4K"
        if self.width >= 1920: return "1080p"
        if self.width >= 1280: return "720p"
        return "SD"


class MaterialLibrary:
    """素材库管理"""

    def __init__(self, base_dir: str = "materials/"):
        self.base_dir = base_dir
        self.materials: Dict[str, Material] = {}
        self.tag_index: Dict[str, List[str]] = {}  # tag → material_ids
        self._loaded = False

    async def load(self, index_file: str = "material_index.json"):
        """从索引文件加载素材库"""
        path = os.path.join(self.base_dir, index_file)
        if os.path.exists(path):
            with open(path, 'r') as f:
                data = json.load(f)
            for m in data.get('materials', []):
                mat = Material(**m)
                self.materials[mat.material_id] = mat
                for tag in mat.tags:
                    self.tag_index.setdefault(tag, []).append(mat.material_id)
            self._loaded = True
            logger.info(f"Material library loaded: {len(self.materials)} items")

    async def save(self, index_file: str = "material_index.json"):
        """保存索引"""
        path = os.path.join(self.base_dir, index_file)
        data = {
            'version': 1,
            'updated_at': datetime.utcnow().isoformat(),
            'total': len(self.materials),
            'materials': [m.__dict__ for m in self.materials.values()],
        }
        os.makedirs(self.base_dir, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    async def index_directory(self, directory: str, recursive: bool = True):
        """索引目录中所有媒体文件"""
        video_exts = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}
        image_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
        audio_exts = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}

        count = 0
        walker = os.walk(directory) if recursive else [(directory, [], os.listdir(directory))]

        for root, dirs, files in walker:
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in video_exts | image_exts | audio_exts:
                    continue

                full_path = os.path.join(root, fname)
                material_id = hashlib.md5(full_path.encode()).hexdigest()[:16]

                if ext in video_exts:
                    media_type = "video"
                elif ext in image_exts:
                    media_type = "image"
                else:
                    media_type = "audio"

                # 尝试获取视频信息
                duration = 0
                width, height = 0, 0
                if media_type == "video":
                    try:
                        from ..core.chunked_processor import VideoInspector
                        meta = await VideoInspector.probe(full_path)
                        duration = meta.duration_sec
                        width, height = meta.width, meta.height
                    except Exception:
                        pass

                # 生成标签
                tags = self._generate_tags(fname, media_type, full_path)

                material = Material(
                    material_id=material_id,
                    path=full_path,
                    media_type=media_type,
                    duration_sec=duration,
                    width=width,
                    height=height,
                    tags=tags,
                    indexed_at=datetime.utcnow().isoformat(),
                )
                self.materials[material_id] = material
                for tag in tags:
                    self.tag_index.setdefault(tag, []).append(material_id)
                count += 1

        logger.info(f"Indexed {count} new materials from {directory}")
        await self.save()
        return count

    def _generate_tags(self, filename: str, media_type: str, path: str) -> List[str]:
        """从文件名/路径生成标签"""
        tags = [media_type]
        name_lower = filename.lower()

        # 分辨率标签
        dir_name = os.path.basename(os.path.dirname(path)).lower()
        for res_tag in ['4k', '8k', '1080p', '720p', 'hd', 'uhd']:
            if res_tag in name_lower or res_tag in dir_name:
                tags.append(res_tag)

        # 风格标签
        style_keywords = {
            'cyberpunk': ['cyberpunk', '赛博'],
            'anime': ['anime', '二次元', '动漫'],
            'nature': ['nature', '自然', '风景'],
            'city': ['city', '城市', 'urban'],
            'aerial': ['aerial', '航拍', 'drone'],
            'slowmo': ['slow', '慢动作'],
            'timelapse': ['timelapse', '延时'],
        }
        for tag, keywords in style_keywords.items():
            if any(k in name_lower for k in keywords):
                tags.append(tag)

        return tags

    async def search(
        self,
        tags: Optional[List[str]] = None,
        media_type: Optional[str] = None,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
        min_resolution: Optional[Tuple[int, int]] = None,
        license_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Material]:
        """多条件筛选搜索"""
        results = list(self.materials.values())

        if tags:
            tag_ids = set()
            for tag in tags:
                tag_ids.update(self.tag_index.get(tag, []))
            results = [m for m in results if m.material_id in tag_ids]

        if media_type:
            results = [m for m in results if m.media_type == media_type]

        if min_duration:
            results = [m for m in results if m.duration_sec >= min_duration]

        if max_duration:
            results = [m for m in results if m.duration_sec <= max_duration]

        if min_resolution:
            min_w, min_h = min_resolution
            results = [m for m in results if m.width >= min_w and m.height >= min_h]

        if license_type:
            results = [m for m in results if m.license_type == license_type]

        # 按美学评分 + 使用次数排序
        results.sort(key=lambda m: (m.aesthetic_score * 0.7 + min(m.usage_count / 100, 0.3)), reverse=True)

        return results[:limit]

    def get_by_id(self, material_id: str) -> Optional[Material]:
        return self.materials.get(material_id)

    def record_usage(self, material_id: str):
        """记录素材使用"""
        mat = self.materials.get(material_id)
        if mat:
            mat.usage_count += 1

    async def get_stats(self) -> dict:
        """素材库统计"""
        by_type = {}
        for m in self.materials.values():
            by_type[m.media_type] = by_type.get(m.media_type, 0) + 1
        return {
            'total': len(self.materials),
            'by_type': by_type,
            'total_tags': len(self.tag_index),
            'total_duration_hours': sum(m.duration_sec for m in self.materials.values()) / 3600,
        }
