"""
视频版本管理系统 (Video Versioning)

功能：
- 视频多版本管理 (draft/v1/v2/...)
- 版本差异对比
- 版本回滚
- 版本标签
"""

import asyncio
import os
import json
import shutil
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class VersionStatus(Enum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


@dataclass
class VideoVersion:
    """视频版本"""
    version_id: str
    project_id: str
    version_number: int
    label: str = ""                # "初稿" / "终版" / "客户修改版"
    status: VersionStatus = VersionStatus.DRAFT
    file_path: str = ""
    file_hash: str = ""
    file_size_bytes: int = 0
    duration_sec: float = 0
    resolution: str = ""
    codec: str = ""
    notes: str = ""
    tags: List[str] = field(default_factory=list)
    parent_version: Optional[str] = None
    created_at: str = ""
    created_by: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class VideoVersionManager:
    """视频版本管理器"""

    def __init__(self, storage_dir: str = "versions/"):
        self.storage_dir = storage_dir
        self._versions: Dict[str, List[VideoVersion]] = {}  # project_id → versions
        Path(storage_dir).mkdir(parents=True, exist_ok=True)

    def create_version(
        self,
        project_id: str,
        file_path: str,
        label: str = "",
        notes: str = "",
        parent_version_id: Optional[str] = None,
    ) -> VideoVersion:
        """创建新版本"""
        versions = self._versions.setdefault(project_id, [])
        version_number = len(versions) + 1

        # 计算哈希
        file_hash = self._compute_hash(file_path)

        # 获取文件信息
        file_size = os.path.getsize(file_path)
        duration, resolution, codec = self._probe_video(file_path)

        version = VideoVersion(
            version_id=f"ver_{project_id}_{version_number}",
            project_id=project_id,
            version_number=version_number,
            label=label or f"v{version_number}",
            file_path=file_path,
            file_hash=file_hash,
            file_size_bytes=file_size,
            duration_sec=duration,
            resolution=resolution,
            codec=codec,
            notes=notes,
            parent_version=parent_version_id,
            created_at=datetime.utcnow().isoformat(),
        )

        # 存储版本文件
        self._archive_version(version)

        versions.append(version)
        logger.info(f"Version created: {version.version_id} ({label})")
        return version

    def get_version(self, project_id: str, version_id: str) -> Optional[VideoVersion]:
        versions = self._versions.get(project_id, [])
        for v in versions:
            if v.version_id == version_id:
                return v
        return None

    def get_latest(self, project_id: str) -> Optional[VideoVersion]:
        versions = self._versions.get(project_id, [])
        return versions[-1] if versions else None

    def list_versions(
        self, project_id: str, status: Optional[VersionStatus] = None
    ) -> List[VideoVersion]:
        versions = self._versions.get(project_id, [])
        if status:
            return [v for v in versions if v.status == status]
        return versions

    def update_status(
        self, project_id: str, version_id: str, status: VersionStatus
    ):
        version = self.get_version(project_id, version_id)
        if version:
            version.status = status
            logger.info(f"Version {version_id} status → {status.value}")

    def set_label(self, project_id: str, version_id: str, label: str):
        version = self.get_version(project_id, version_id)
        if version:
            version.label = label

    def compare_versions(
        self, project_id: str, version_id_a: str, version_id_b: str
    ) -> dict:
        """对比两个版本"""
        va = self.get_version(project_id, version_id_a)
        vb = self.get_version(project_id, version_id_b)
        if not va or not vb:
            return {}

        return {
            "version_a": {"id": va.version_id, "size": va.file_size_bytes, "duration": va.duration_sec},
            "version_b": {"id": vb.version_id, "size": vb.file_size_bytes, "duration": vb.duration_sec},
            "size_diff_bytes": vb.file_size_bytes - va.file_size_bytes,
            "duration_diff_sec": round(vb.duration_sec - va.duration_sec, 1),
            "codec_changed": va.codec != vb.codec,
            "resolution_changed": va.resolution != vb.resolution,
        }

    def _archive_version(self, version: VideoVersion):
        """存档版本文件"""
        archive_dir = os.path.join(self.storage_dir, version.project_id)
        os.makedirs(archive_dir, exist_ok=True)
        dest = os.path.join(archive_dir, f"{version.version_id}.mp4")
        if version.file_path != dest and os.path.exists(version.file_path):
            shutil.copy2(version.file_path, dest)
            version.file_path = dest

    @staticmethod
    def _compute_hash(filepath: str) -> str:
        """SHA256 文件哈希"""
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _probe_video(filepath: str) -> tuple:
        """探测视频信息"""
        try:
            import subprocess
            cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", filepath,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            data = json.loads(result.stdout)

            duration = float(data.get("format", {}).get("duration", 0))
            resolution = "unknown"
            codec = "unknown"
            for stream in data.get("streams", []):
                if stream["codec_type"] == "video":
                    resolution = f"{stream.get('width', 0)}x{stream.get('height', 0)}"
                    codec = stream.get("codec_name", "unknown")
                    break
            return duration, resolution, codec
        except Exception:
            return 0, "unknown", "unknown"


# 全局实例
version_manager = VideoVersionManager()
