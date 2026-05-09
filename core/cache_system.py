"""
缓存系统 (Cache System)

功能：
- 多级缓存 (内存 → Redis → 磁盘)
- 自动过期与淘汰
- 缓存预热
- 命中率统计
"""

import asyncio
import hashlib
import json
import os
import time
import pickle
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from collections import OrderedDict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    ttl_sec: float = 3600           # 默认1小时
    access_count: int = 0
    last_access: float = field(default_factory=time.time)
    size_bytes: int = 0

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_sec


class MemoryCache:
    """内存缓存 (LRU)"""

    def __init__(self, max_size: int = 1000, max_memory_mb: int = 256):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.max_size = max_size
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self._current_memory = 0
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        entry = self._cache.get(key)
        if entry and not entry.expired:
            entry.access_count += 1
            entry.last_access = time.time()
            self._cache.move_to_end(key)
            self._hits += 1
            return entry.value
        elif entry:
            self._cache.pop(key, None)
        self._misses += 1
        return None

    def set(self, key: str, value: Any, ttl_sec: float = 3600):
        """设置缓存"""
        size = len(pickle.dumps(value))
        entry = CacheEntry(key=key, value=value, ttl_sec=ttl_sec, size_bytes=size)

        if key in self._cache:
            old = self._cache[key]
            self._current_memory -= old.size_bytes

        self._cache[key] = entry
        self._current_memory += size
        self._cache.move_to_end(key)

        # LRU 淘汰
        while len(self._cache) > self.max_size or self._current_memory > self.max_memory_bytes:
            self._evict_one()

    def delete(self, key: str):
        entry = self._cache.pop(key, None)
        if entry:
            self._current_memory -= entry.size_bytes

    def _evict_one(self):
        """淘汰最久未使用的条目"""
        try:
            _, entry = self._cache.popitem(last=False)
            self._current_memory -= entry.size_bytes
        except KeyError:
            pass

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0

    def stats(self) -> dict:
        return {
            "size": len(self._cache),
            "memory_mb": self._current_memory / 1024 / 1024,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{self.hit_rate:.1%}",
            "max_size": self.max_size,
        }


class DiskCache:
    """磁盘缓存"""

    def __init__(self, cache_dir: str = "cache/"):
        self.cache_dir = cache_dir
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

    def _key_to_path(self, key: str) -> str:
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return os.path.join(self.cache_dir, key_hash[:2], key_hash)

    def get(self, key: str) -> Optional[Any]:
        path = self._key_to_path(key)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    data = pickle.load(f)
                entry = data.get("entry")
                if entry and time.time() - entry.get("created_at", 0) < entry.get("ttl_sec", 3600):
                    return data.get("value")
                else:
                    os.remove(path)
            except Exception:
                pass
        return None

    def set(self, key: str, value: Any, ttl_sec: float = 86400):
        path = self._key_to_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "entry": {"created_at": time.time(), "ttl_sec": ttl_sec},
            "value": value,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)

    def delete(self, key: str):
        path = self._key_to_path(key)
        if os.path.exists(path):
            os.remove(path)

    def cleanup_expired(self):
        """清理过期缓存"""
        count = 0
        for root, dirs, files in os.walk(self.cache_dir):
            for f in files:
                path = os.path.join(root, f)
                try:
                    with open(path, "rb") as fh:
                        data = pickle.load(fh)
                    entry = data.get("entry", {})
                    if time.time() - entry.get("created_at", 0) > entry.get("ttl_sec", 86400):
                        os.remove(path)
                        count += 1
                except Exception:
                    os.remove(path)
                    count += 1
        if count:
            logger.info(f"Cleaned up {count} expired cache files")


class MultiLevelCache:
    """多级缓存 (内存 → 磁盘)"""

    def __init__(
        self,
        memory_cache: Optional[MemoryCache] = None,
        disk_cache: Optional[DiskCache] = None,
    ):
        self.memory = memory_cache or MemoryCache()
        self.disk = disk_cache or DiskCache()

    async def get(self, key: str) -> Optional[Any]:
        # L1: 内存
        value = self.memory.get(key)
        if value is not None:
            return value

        # L2: 磁盘
        value = self.disk.get(key)
        if value is not None:
            # 回填到内存
            self.memory.set(key, value)
            return value

        return None

    async def set(self, key: str, value: Any, ttl_sec: float = 3600):
        self.memory.set(key, value, ttl_sec)
        self.disk.set(key, value, ttl_sec * 2)  # 磁盘缓存时间更长

    async def get_or_compute(
        self, key: str, compute_fn: Callable, ttl_sec: float = 3600
    ) -> Any:
        """缓存未命中时自动计算"""
        value = await self.get(key)
        if value is not None:
            return value

        value = await compute_fn() if asyncio.iscoroutinefunction(compute_fn) else compute_fn()
        await self.set(key, value, ttl_sec)
        return value

    def stats(self) -> dict:
        return {
            "memory": self.memory.stats(),
        }

    def invalidate(self, key: str):
        self.memory.delete(key)
        self.disk.delete(key)


# 全局缓存
cache = MultiLevelCache()
