"""
Artifact Store — 版本化制品存储
===============================
所有 Agent 产出物（脚本/分镜/配音/BGM/QC报告）存入制品库。
- 后端：文件系统 (JSON) · 生产可切 MinIO/S3
- 版本控制：自动递增版本号，旧版本保留追溯
- 内存缓存：TTL 300s 减少磁盘 I/O
"""

import asyncio
import json
import os
import time
import hashlib
import logging
from pathlib import Path
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger("quanquan.artifact_store")


@dataclass
class ArtifactMeta:
    """制品元数据"""
    key: str
    version: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    content_hash: str = ""
    size_bytes: int = 0


class ArtifactStore:
    """
    版本化制品存储。

    文件布局:
        artifacts/{project_id}/{key}/
            v1.json
            v2.json
            _meta.json

    用法:
        store = ArtifactStore(base_dir="/data/quanquan/artifacts")
        await store.put("proj_001", "script", {"scenes": [...]})
        data = await store.get("proj_001", "script")  # 最新版本
        data = await store.get("proj_001", "script", version="v1")
    """

    CACHE_TTL = 300.0  # 内存缓存过期时间（秒）
    MAX_CACHE_SIZE = 1000

    def __init__(self, base_dir: str = "/data/quanquan/artifacts"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # 内存缓存: {cache_key: (data, cached_at)}
        self._cache: Dict[str, tuple] = {}
        self._cache_lock = asyncio.Lock()

    # ── 核心操作 ──

    async def put(
        self,
        project_id: str,
        key: str,
        data: Any,
        version: Optional[str] = None,
    ) -> str:
        """
        存入制品。返回版本号。

        version=None 时自动递增（v1 → v2 → v3...）
        """
        # 序列化
        raw = json.dumps(data, ensure_ascii=False, indent=2)
        content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]

        # 确定版本号
        if version is None:
            version = await self._next_version(project_id, key)
        elif not version.startswith("v"):
            version = f"v{version}"

        # 写入文件
        file_path = self._artifact_path(project_id, key, version)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        def _write():
            file_path.write_text(raw, encoding="utf-8")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write)

        # 更新元数据
        meta = ArtifactMeta(
            key=key,
            version=version,
            content_hash=content_hash,
            size_bytes=len(raw.encode("utf-8")),
        )
        await self._save_meta(project_id, key, meta)

        # 更新缓存
        cache_key = f"{project_id}:{key}:{version}"
        async with self._cache_lock:
            self._cache[cache_key] = (data, time.time())
            # LRU 清理
            if len(self._cache) > self.MAX_CACHE_SIZE:
                oldest = min(self._cache, key=lambda k: self._cache[k][1])
                del self._cache[oldest]

        logger.debug("Artifact stored: %s/%s/%s size=%s", project_id, key, version, meta.size_bytes)
        return version

    async def get(
        self,
        project_id: str,
        key: str,
        version: Optional[str] = None,
    ) -> Optional[Any]:
        """获取制品。version=None 取最新版本。"""
        # 查缓存
        if version:
            cache_key = f"{project_id}:{key}:{version}"
            async with self._cache_lock:
                if cache_key in self._cache:
                    data, cached_at = self._cache[cache_key]
                    if time.time() - cached_at < self.CACHE_TTL:
                        return data
                    del self._cache[cache_key]
        else:
            # 取最新版本：先查元数据
            version = await self._latest_version(project_id, key)
            if version is None:
                return None
            cache_key = f"{project_id}:{key}:{version}"
            async with self._cache_lock:
                if cache_key in self._cache:
                    data, cached_at = self._cache[cache_key]
                    if time.time() - cached_at < self.CACHE_TTL:
                        return data

        # 读文件
        file_path = self._artifact_path(project_id, key, version)
        if not file_path.exists():
            return None

        def _read():
            return file_path.read_text(encoding="utf-8")

        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, _read)
        data = json.loads(raw)

        # 回写缓存
        cache_key = f"{project_id}:{key}:{version}"
        async with self._cache_lock:
            self._cache[cache_key] = (data, time.time())

        return data

    async def list_versions(self, project_id: str, key: str) -> List[str]:
        """列出某个 key 的所有版本号（排序）。"""
        dir_path = self._artifact_path(project_id, key).parent
        if not dir_path.exists():
            return []
        versions = []
        key_dir = dir_path / key
        if key_dir.exists():
            for f in key_dir.glob("v*.json"):
                v = f.stem  # e.g. "v1"
                try:
                    versions.append((int(v[1:]), v))
                except ValueError:
                    versions.append((0, v))
            versions.sort(key=lambda x: x[0])
            return [v for _, v in versions]
        return []

    async def delete(self, project_id: str, key: Optional[str] = None) -> bool:
        """删除制品。key=None 删除整个项目。"""
        import shutil
        if key is None:
            path = self.base_dir / project_id
        else:
            path = self._artifact_path(project_id, key).parent / key

        if path.exists():
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, shutil.rmtree, path)
        # 清理缓存
        async with self._cache_lock:
            prefix = f"{project_id}:{key or ''}"
            stale = [k for k in self._cache if k.startswith(prefix)]
            for k in stale:
                del self._cache[k]
        return True

    # ── 上下文管理器 ──

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    # ── 内部 ──

    def _artifact_path(self, project_id: str, key: str, version: str = "") -> Path:
        if version:
            return self.base_dir / project_id / key / f"{version}.json"
        return self.base_dir / project_id / key

    async def _next_version(self, project_id: str, key: str) -> str:
        versions = await self.list_versions(project_id, key)
        if not versions:
            return "v1"
        last_num = max(int(v[1:]) for v in versions if v.startswith("v"))
        return f"v{last_num + 1}"

    async def _latest_version(self, project_id: str, key: str) -> Optional[str]:
        versions = await self.list_versions(project_id, key)
        return versions[-1] if versions else None

    async def _save_meta(self, project_id: str, key: str, meta: ArtifactMeta) -> None:
        meta_path = self.base_dir / project_id / key / "_meta.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        existing = {}
        if meta_path.exists():
            def _read():
                return meta_path.read_text(encoding="utf-8")
            loop = asyncio.get_event_loop()
            existing_text = await loop.run_in_executor(None, _read)
            existing = json.loads(existing_text)

        existing[meta.version] = {
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
            "content_hash": meta.content_hash,
            "size_bytes": meta.size_bytes,
        }

        def _write():
            meta_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write)


# ── 全局单例 ──
artifact_store = ArtifactStore()

