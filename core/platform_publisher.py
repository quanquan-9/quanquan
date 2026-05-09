"""
多平台视频发布引擎 (Platform Publisher)

功能：
- B站 (Bilibili) 发布: 分片上传 / bilibili-api-python, 封面, 标签, 定时发布
- 抖音 (Douyin) 发布: API 封装 / 离线发布包生成
- YouTube 发布: OAuth2 / API Key, 上传, 缩略图, 播放列表, 定时发布
- 统一 `publish(platform, video_path, metadata) -> dict` 接口
- 平台预设管理器 (Platform Presets)
- 按平台速率限制 (Rate Limiting)
- 发布队列 + 重试 (Publish Queue with Retry)

参考文档:
- B站开放平台: https://openhome.bilibili.com/doc
- YouTube Data API v3: https://developers.google.com/youtube/v3
- 抖音开放平台: https://developer.open-douyin.com/
"""

import os
import re
import json
import time
import uuid
import hashlib
import logging
import threading
import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from queue import Queue, PriorityQueue
from concurrent.futures import ThreadPoolExecutor, Future

logger = logging.getLogger(__name__)


# ============================================================================
# 枚举定义
# ============================================================================

class PublishPlatform(Enum):
    """支持的发布平台"""
    BILIBILI = "bilibili"       # B站
    DOUYIN = "douyin"            # 抖音
    YOUTUBE = "youtube"          # YouTube


class PublishStatus(Enum):
    """发布状态"""
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    PUBLISHED = "published"
    SCHEDULED = "scheduled"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class VideoVisibility(Enum):
    """视频可见性"""
    PUBLIC = "public"
    PRIVATE = "private"
    UNLISTED = "unlisted"
    FRIENDS_ONLY = "friends_only"   # B站/抖音: 仅好友可见
    DRAFT = "draft"                  # B站: 草稿


# ============================================================================
# 平台配置数据类
# ============================================================================

@dataclass
class PlatformPublishConfig:
    """平台发布配置"""
    platform: PublishPlatform
    # 视频规格要求
    supported_formats: List[str] = field(default_factory=lambda: ["mp4"])
    max_resolution: Tuple[int, int] = (1920, 1080)
    max_duration_sec: int = 600
    max_file_size_bytes: int = 4 * 1024 * 1024 * 1024  # 4GB
    recommended_bitrate_kbps: int = 10000
    video_codec: str = "h264"
    audio_codec: str = "aac"
    # 元数据限制
    title_max_chars: int = 80
    title_min_chars: int = 1
    desc_max_chars: int = 2000
    desc_min_chars: int = 0
    tag_max_count: int = 10
    tag_max_length: int = 20
    # 封面要求
    cover_max_size_bytes: int = 5 * 1024 * 1024  # 5MB
    cover_formats: List[str] = field(default_factory=lambda: ["jpg", "jpeg", "png"])
    cover_max_resolution: Tuple[int, int] = (1920, 1080)
    # 发布特性
    supports_schedule: bool = True
    supports_playlist: bool = False
    supports_ai_cover: bool = False
    # API 端点
    upload_endpoint: str = ""
    # 速率限制
    rate_limit_uploads_per_hour: int = 10
    rate_limit_uploads_per_day: int = 50


# ============================================================================
# 平台预设 (Platform Presets)
# ============================================================================

PLATFORM_PRESETS: Dict[PublishPlatform, PlatformPublishConfig] = {
    PublishPlatform.BILIBILI: PlatformPublishConfig(
        platform=PublishPlatform.BILIBILI,
        supported_formats=["mp4", "flv", "mkv", "avi", "wmv", "mov"],
        max_resolution=(3840, 2160),        # 支持4K
        max_duration_sec=36000,             # 10小时
        max_file_size_bytes=8 * 1024**3,    # 8GB
        recommended_bitrate_kbps=20000,
        video_codec="h264",
        audio_codec="aac",
        title_max_chars=80,
        title_min_chars=1,
        desc_max_chars=2000,
        tag_max_count=10,
        tag_max_length=20,
        cover_max_size_bytes=5 * 1024**2,
        cover_formats=["jpg", "jpeg", "png"],
        supports_schedule=True,
        supports_playlist=False,
        supports_ai_cover=True,             # B站支持AI封面
        upload_endpoint="https://member.bilibili.com/x/vu/client/add",
        rate_limit_uploads_per_hour=10,
        rate_limit_uploads_per_day=50,
    ),
    PublishPlatform.DOUYIN: PlatformPublishConfig(
        platform=PublishPlatform.DOUYIN,
        supported_formats=["mp4", "mov"],
        max_resolution=(1080, 1920),        # 竖屏
        max_duration_sec=1800,              # 30分钟（普通用户）
        max_file_size_bytes=4 * 1024**3,    # 4GB
        recommended_bitrate_kbps=16000,
        video_codec="h264",
        audio_codec="aac",
        title_max_chars=55,                 # 抖音描述限制
        title_min_chars=0,                  # 可不写标题
        desc_max_chars=500,
        tag_max_count=5,
        tag_max_length=15,
        cover_max_size_bytes=5 * 1024**2,
        cover_formats=["jpg", "jpeg", "png"],
        supports_schedule=True,
        supports_playlist=False,
        upload_endpoint="https://open.douyin.com/video/upload/",
        rate_limit_uploads_per_hour=5,
        rate_limit_uploads_per_day=20,
    ),
    PublishPlatform.YOUTUBE: PlatformPublishConfig(
        platform=PublishPlatform.YOUTUBE,
        supported_formats=["mp4", "mov", "avi", "wmv", "flv", "mkv", "webm"],
        max_resolution=(3840, 2160),        # 4K
        max_duration_sec=43200,             # 12小时
        max_file_size_bytes=256 * 1024**3,  # 256GB
        recommended_bitrate_kbps=85000,
        video_codec="h264",
        audio_codec="aac",
        title_max_chars=100,
        title_min_chars=1,
        desc_max_chars=5000,
        tag_max_count=30,                   # YouTube 支持更多标签
        tag_max_length=30,
        cover_max_size_bytes=2 * 1024**2,
        cover_formats=["jpg", "jpeg", "png"],
        cover_max_resolution=(3840, 2160),
        supports_schedule=True,
        supports_playlist=True,
        upload_endpoint="https://www.googleapis.com/upload/youtube/v3/videos",
        rate_limit_uploads_per_hour=6,
        rate_limit_uploads_per_day=100,
    ),
}


# ============================================================================
# 发布结果数据类
# ============================================================================

@dataclass
class PublishResult:
    """发布结果"""
    platform: str
    status: PublishStatus
    video_id: Optional[str] = None
    video_url: Optional[str] = None
    message: str = ""
    raw_response: Optional[Dict] = None
    error: Optional[str] = None
    retry_count: int = 0
    elapsed_sec: float = 0.0
    publish_time: Optional[str] = None


@dataclass
class VideoMetadata:
    """视频元数据"""
    title: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    cover_path: Optional[str] = None
    visibility: VideoVisibility = VideoVisibility.PUBLIC
    schedule_time: Optional[str] = None      # ISO 8601 格式
    playlist_id: Optional[str] = None         # YouTube 播放列表
    category_id: Optional[str] = None         # 分区/分类ID
    custom_thumbnail_path: Optional[str] = None
    # 扩展字段
    extra: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# 速率限制器 (Per-Platform Rate Limiter)
# ============================================================================

@dataclass
class PlatformRateLimit:
    """平台速率限制状态"""
    uploads_this_hour: int = 0
    uploads_today: int = 0
    hour_start: float = field(default_factory=time.monotonic)
    day_start: float = field(default_factory=time.monotonic)
    last_upload_time: float = 0.0
    min_interval_sec: float = 30.0           # 最小上传间隔


class PlatformRateLimiter:
    """按平台的速率限制器"""

    def __init__(self):
        self._limits: Dict[PublishPlatform, PlatformRateLimit] = defaultdict(PlatformRateLimit)
        self._lock = threading.Lock()

    def _reset_if_needed(self, limit: PlatformRateLimit):
        """检查并重置时间窗口"""
        now = time.monotonic()
        if now - limit.hour_start >= 3600:
            limit.uploads_this_hour = 0
            limit.hour_start = now
        if now - limit.day_start >= 86400:
            limit.uploads_today = 0
            limit.day_start = now

    def check_and_acquire(self, platform: PublishPlatform) -> Tuple[bool, str]:
        """
        检查是否允许上传。返回 (allowed, reason)。

        Args:
            platform: 目标平台

        Returns:
            (是否允许, 被拒绝原因)
        """
        config = PLATFORM_PRESETS.get(platform)
        if not config:
            return False, f"未知平台: {platform.value}"

        with self._lock:
            limit = self._limits[platform]
            self._reset_if_needed(limit)

            # 检查每小时限制
            if limit.uploads_this_hour >= config.rate_limit_uploads_per_hour:
                wait_sec = int(3600 - (time.monotonic() - limit.hour_start))
                return False, f"每小时上传次数已达上限 ({config.rate_limit_uploads_per_hour}/h)，需等待 {wait_sec}s"

            # 检查每天限制
            if limit.uploads_today >= config.rate_limit_uploads_per_day:
                wait_sec = int(86400 - (time.monotonic() - limit.day_start))
                return False, f"每日上传次数已达上限 ({config.rate_limit_uploads_per_day}/d)，需等待 {wait_sec}s"

            # 检查最小间隔
            elapsed = time.monotonic() - limit.last_upload_time
            if elapsed < limit.min_interval_sec:
                wait_sec = int(limit.min_interval_sec - elapsed)
                return False, f"上传间隔太短，需等待 {wait_sec}s"

            # 获取许可
            limit.uploads_this_hour += 1
            limit.uploads_today += 1
            limit.last_upload_time = time.monotonic()
            return True, "OK"

    def get_stats(self, platform: PublishPlatform) -> Dict[str, Any]:
        """获取平台速率统计"""
        with self._lock:
            limit = self._limits[platform]
            self._reset_if_needed(limit)
            config = PLATFORM_PRESETS.get(platform)
            return {
                "platform": platform.value,
                "uploads_this_hour": limit.uploads_this_hour,
                "hourly_limit": config.rate_limit_uploads_per_hour if config else 0,
                "uploads_today": limit.uploads_today,
                "daily_limit": config.rate_limit_uploads_per_day if config else 0,
                "next_upload_in_sec": max(0, int(limit.min_interval_sec - (time.monotonic() - limit.last_upload_time))),
            }

    def reset(self, platform: Optional[PublishPlatform] = None):
        """重置指定平台或所有平台的速率限制"""
        with self._lock:
            if platform:
                self._limits[platform] = PlatformRateLimit()
            else:
                self._limits.clear()


# ============================================================================
# 元数据验证器
# ============================================================================

class MetadataValidator:
    """验证视频元数据是否符合平台要求"""

    @staticmethod
    def validate(metadata: VideoMetadata, platform: PublishPlatform) -> Tuple[bool, List[str]]:
        """
        验证元数据。返回 (valid, errors)。

        Args:
            metadata: 视频元数据
            platform: 目标平台

        Returns:
            (是否通过验证, 错误列表)
        """
        config = PLATFORM_PRESETS.get(platform)
        if not config:
            return False, [f"未知平台: {platform.value}"]

        errors = []

        # 验证标题
        title_len = len(metadata.title)
        if title_len < config.title_min_chars:
            errors.append(
                f"标题过短: {title_len} 字符 (最小 {config.title_min_chars})"
            )
        if title_len > config.title_max_chars:
            errors.append(
                f"标题过长: {title_len} 字符 (最大 {config.title_max_chars})"
            )

        # 验证描述
        desc_len = len(metadata.description or "")
        if desc_len > config.desc_max_chars:
            errors.append(
                f"描述过长: {desc_len} 字符 (最大 {config.desc_max_chars})"
            )

        # 验证标签
        if len(metadata.tags) > config.tag_max_count:
            errors.append(
                f"标签过多: {len(metadata.tags)} 个 (最大 {config.tag_max_count})"
            )
        for tag in metadata.tags:
            if len(tag) > config.tag_max_length:
                errors.append(
                    f"标签过长: '{tag}' ({len(tag)} 字符, 最大 {config.tag_max_length})"
                )
                break

        # 验证封面（如果提供）
        if metadata.cover_path:
            cover_path = Path(metadata.cover_path)
            if not cover_path.exists():
                errors.append(f"封面文件不存在: {metadata.cover_path}")
            else:
                suffix = cover_path.suffix.lstrip(".").lower()
                if suffix not in [f.lstrip(".") for f in config.cover_formats]:
                    errors.append(
                        f"封面格式不支持: .{suffix} (支持: {config.cover_formats})"
                    )
                if cover_path.stat().st_size > config.cover_max_size_bytes:
                    errors.append(
                        f"封面文件过大: {cover_path.stat().st_size} 字节 "
                        f"(最大 {config.cover_max_size_bytes})"
                    )

        return len(errors) == 0, errors


# ============================================================================
# 抽象平台客户端
# ============================================================================

class BasePlatformClient(ABC):
    """平台客户端基类"""

    def __init__(self, config: PlatformPublishConfig):
        self.config = config
        self.platform = config.platform

    @abstractmethod
    def upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> PublishResult:
        """
        上传视频到平台。

        Args:
            video_path: 视频文件路径
            metadata: 视频元数据
            progress_callback: 进度回调 (进度比例 0~1, 状态描述)

        Returns:
            PublishResult
        """
        ...

    def validate_video(self, video_path: str) -> Tuple[bool, str]:
        """
        验证视频文件是否符合平台要求。

        Returns:
            (valid, error_message)
        """
        path = Path(video_path)
        if not path.exists():
            return False, f"视频文件不存在: {video_path}"

        suffix = path.suffix.lstrip(".").lower()
        if suffix not in self.config.supported_formats:
            return False, (
                f"不支持视频格式 .{suffix}，"
                f"{self.platform.value} 支持: {self.config.supported_formats}"
            )

        file_size = path.stat().st_size
        if file_size > self.config.max_file_size_bytes:
            size_mb = file_size / (1024 * 1024)
            max_mb = self.config.max_file_size_bytes / (1024 * 1024)
            return False, f"视频文件过大: {size_mb:.0f}MB (最大 {max_mb:.0f}MB)"

        return True, "OK"


# ============================================================================
# Bilibili 客户端
# ============================================================================

class BilibiliClient(BasePlatformClient):
    """
    B站视频发布客户端。

    支持两种上传模式:
    1. bilibili-api-python SDK (推荐，需安装)
    2. 手动分片上传 (手动实现 HTTP 分片)

    B站开放平台文档: https://openhome.bilibili.com/doc

    环境变量:
        BILIBILI_SESSDATA: B站 SESSDATA Cookie
        BILIBILI_CSRF: B站 CSRF Token (bili_jct)
        BILIBILI_ACCESS_TOKEN: B站开放平台 Access Token
        BILIBILI_REFRESH_TOKEN: B站开放平台 Refresh Token
    """

    # B站上传API端点
    UPLOAD_URL = "https://member.bilibili.com/x/vu/client/add"
    COVER_UPLOAD_URL = "https://member.bilibili.com/x/vu/client/cover/up"
    PREUPLOAD_URL = "https://member.bilibili.com/x/vu/client/preupload"
    CHUNK_UPLOAD_URL = "https://upos-sz-mirrorcos.bilivideo.com/ugc/v3"
    CHUNK_SIZE = 10 * 1024 * 1024  # 10MB 每片

    def __init__(self, config: PlatformPublishConfig = None):
        super().__init__(config or PLATFORM_PRESETS[PublishPlatform.BILIBILI])
        self._sessdata = os.environ.get("BILIBILI_SESSDATA", "")
        self._csrf = os.environ.get("BILIBILI_CSRF", "")
        self._access_token = os.environ.get("BILIBILI_ACCESS_TOKEN", "")
        self._refresh_token = os.environ.get("BILIBILI_REFRESH_TOKEN", "")

    def _get_headers(self) -> Dict[str, str]:
        """构建请求头"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://member.bilibili.com/",
            "Origin": "https://member.bilibili.com",
        }
        if self._sessdata:
            headers["Cookie"] = f"SESSDATA={self._sessdata}; bili_jct={self._csrf}"
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def _use_sdk_upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable] = None,
    ) -> Optional[PublishResult]:
        """
        尝试使用 bilibili-api-python SDK 上传。
        如果 SDK 不可用，返回 None 以回退到手动上传。
        """
        try:
            from bilibili_api import video_uploader, Credential
            logger.info("[Bilibili] 使用 bilibili-api-python SDK 上传")

            credential = Credential(
                sessdata=self._sessdata,
                bili_jct=self._csrf,
                ac_time_value=self._access_token,
            )

            # 构建上传参数
            uploader = video_uploader.VideoUploader(
                parts=video_uploader.VideoUploaderPage(
                    path=video_path,
                    title=metadata.title,
                    description=metadata.description,
                ),
                credential=credential,
            )

            # 同步上传（bilibili-api-python 的 uploader 本身支持进度回调）
            if progress_callback:
                progress_callback(0.0, "正在上传到B站...")

            # 使用 asyncio 运行异步上传
            async def _do_upload():
                result = await uploader.start()
                return result

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(_do_upload())
            finally:
                loop.close()

            if progress_callback:
                progress_callback(1.0, "B站上传完成")

            video_id = result.get("bvid") or result.get("aid", "")
            return PublishResult(
                platform="bilibili",
                status=PublishStatus.PUBLISHED,
                video_id=video_id,
                video_url=f"https://www.bilibili.com/video/{video_id}" if video_id else "",
                message="上传成功 (SDK)",
                raw_response=result,
            )

        except ImportError:
            logger.warning("[Bilibili] bilibili-api-python 未安装，回退到手动上传模式")
            return None
        except Exception as e:
            logger.error(f"[Bilibili] SDK 上传失败: {e}")
            return None

    def _manual_chunked_upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable] = None,
    ) -> PublishResult:
        """
        手动分片上传到B站。

        流程:
        1. 请求预上传 (preupload) → 获取 upload_id 和分片URL
        2. 逐片上传
        3. 合并分片 → 提交
        4. 设置封面、标签
        """
        import requests

        file_size = os.path.getsize(video_path)
        file_name = os.path.basename(video_path)
        headers = self._get_headers()

        # Step 1: 预上传
        logger.info("[Bilibili] 步骤1: 预上传请求...")
        preupload_data = {
            "name": file_name,
            "size": file_size,
            "r": "upos",
            "profile": "ugcfx/bup",
            "ssl": 1,
            "version": "2.10.0",
        }

        try:
            resp = requests.post(
                self.PREUPLOAD_URL,
                data=preupload_data,
                headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
                timeout=30,
            )
            resp.raise_for_status()
            pre_result = resp.json()
        except Exception as e:
            return PublishResult(
                platform="bilibili",
                status=PublishStatus.FAILED,
                error=f"预上传失败: {e}",
                message="B站预上传请求失败",
            )

        if pre_result.get("code") != 0:
            return PublishResult(
                platform="bilibili",
                status=PublishStatus.FAILED,
                error=f"预上传失败: {pre_result.get('message', '未知错误')}",
                raw_response=pre_result,
            )

        upload_url = pre_result.get("data", {}).get("url", "")
        complete_url = pre_result.get("data", {}).get("complete", "")
        if not upload_url:
            return PublishResult(
                platform="bilibili",
                status=PublishStatus.FAILED,
                error="预上传返回的 upload_url 为空",
            )

        # Step 2: 分片上传
        total_chunks = (file_size + self.CHUNK_SIZE - 1) // self.CHUNK_SIZE
        logger.info(f"[Bilibili] 步骤2: 分片上传 ({total_chunks} 片, 每片 {self.CHUNK_SIZE // 1024 // 1024}MB)")

        with open(video_path, "rb") as f:
            for chunk_idx in range(total_chunks):
                start = chunk_idx * self.CHUNK_SIZE
                end = min(start + self.CHUNK_SIZE, file_size)
                chunk_data = f.read(end - start)

                chunk_url = f"{upload_url}&chunk={chunk_idx}&chunks={total_chunks}&start={start}&end={end}&total={file_size}"

                for attempt in range(3):
                    try:
                        resp = requests.put(
                            chunk_url,
                            data=chunk_data,
                            headers={**headers, "Content-Type": "application/octet-stream"},
                            timeout=120,
                        )
                        if resp.status_code in (200, 201, 204):
                            break
                    except Exception as e:
                        if attempt == 2:
                            return PublishResult(
                                platform="bilibili",
                                status=PublishStatus.FAILED,
                                error=f"分片 {chunk_idx + 1}/{total_chunks} 上传失败: {e}",
                            )
                        time.sleep(2 ** attempt)

                if progress_callback:
                    progress_callback((chunk_idx + 1) / total_chunks * 0.8,
                                     f"B站分片上传 {chunk_idx + 1}/{total_chunks}")

        # Step 3: 完成上传
        logger.info("[Bilibili] 步骤3: 合并分片...")
        try:
            resp = requests.post(
                complete_url,
                headers=headers,
                timeout=30,
            )
            complete_result = resp.json()
        except Exception as e:
            return PublishResult(
                platform="bilibili",
                status=PublishStatus.FAILED,
                error=f"合并分片失败: {e}",
            )

        if progress_callback:
            progress_callback(0.9, "B站: 提交视频信息...")

        # Step 4: 提交视频信息
        publish_result = self._submit_video_info(
            metadata,
            headers,
            progress_callback,
        )

        return publish_result

    def _submit_video_info(
        self,
        metadata: VideoMetadata,
        headers: Dict[str, str],
        progress_callback: Optional[Callable] = None,
    ) -> PublishResult:
        """提交视频元信息（标题、描述、标签、封面、定时发布）"""
        import requests

        submit_data = {
            "title": metadata.title[:self.config.title_max_chars],
            "desc": (metadata.description or "")[:self.config.desc_max_chars],
            "tag": ",".join(metadata.tags[:self.config.tag_max_count]),
            "source": "",
            "cover": "",
            "no_reprint": 0,
            "open_elec": 0,
            "csrf": self._csrf,
        }

        # 定时发布
        if metadata.schedule_time:
            submit_data["dtime"] = metadata.schedule_time

        # 可见性
        if metadata.visibility == VideoVisibility.PRIVATE:
            submit_data["copyright"] = 2  # 自制且私有
        elif metadata.visibility == VideoVisibility.DRAFT:
            submit_data["draft"] = 1

        try:
            resp = requests.post(
                self.UPLOAD_URL,
                data=submit_data,
                headers=headers,
                timeout=30,
            )
            result = resp.json()
        except Exception as e:
            return PublishResult(
                platform="bilibili",
                status=PublishStatus.FAILED,
                error=f"提交视频信息失败: {e}",
            )

        if result.get("code") != 0:
            return PublishResult(
                platform="bilibili",
                status=PublishStatus.FAILED,
                error=f"提交失败: {result.get('message', '未知错误')}",
                raw_response=result,
            )

        video_url = result.get("data", {}).get("url", "")
        bvid = ""
        aid = ""
        if video_url:
            # 从URL提取BV号
            match = re.search(r'/video/(BV\w+)', video_url)
            if match:
                bvid = match.group(1)

        if progress_callback:
            progress_callback(0.95, "B站: 设置封面...")

        # Step 5: 设置封面
        if metadata.cover_path and bvid:
            self._set_cover(bvid, metadata.cover_path, headers)

        if progress_callback:
            progress_callback(1.0, "B站发布完成!")

        status = PublishStatus.SCHEDULED if metadata.schedule_time else PublishStatus.PUBLISHED
        return PublishResult(
            platform="bilibili",
            status=status,
            video_id=bvid or str(result.get("data", {}).get("aid", "")),
            video_url=video_url or f"https://www.bilibili.com/video/{bvid}",
            message="发布成功" if not metadata.schedule_time else f"已定时: {metadata.schedule_time}",
            raw_response=result,
        )

    def _set_cover(self, bvid: str, cover_path: str, headers: Dict[str, str]):
        """设置B站视频封面"""
        import requests

        cover_url = f"{self.COVER_UPLOAD_URL}?bvid={bvid}&csrf={self._csrf}"
        try:
            with open(cover_path, "rb") as f:
                files = {"file": (os.path.basename(cover_path), f, "image/jpeg")}
                resp = requests.post(
                    cover_url,
                    files=files,
                    headers=headers,
                    timeout=30,
                )
                result = resp.json()
                if result.get("code") == 0:
                    logger.info(f"[Bilibili] 封面设置成功: {cover_path}")
                else:
                    logger.error(f"[Bilibili] 封面设置失败: {result.get('message')}")
        except Exception as e:
            logger.error(f"[Bilibili] 封面上传异常: {e}")

    def upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable] = None,
    ) -> PublishResult:
        """B站上传入口"""
        # 验证
        valid, msg = self.validate_video(video_path)
        if not valid:
            return PublishResult(
                platform="bilibili",
                status=PublishStatus.FAILED,
                error=msg,
            )

        # 尝试 SDK 上传
        sdk_result = self._use_sdk_upload(video_path, metadata, progress_callback)
        if sdk_result is not None:
            return sdk_result

        # 回退手动分片上传
        return self._manual_chunked_upload(video_path, metadata, progress_callback)


# ============================================================================
# 抖音客户端
# ============================================================================

class DouyinClient(BasePlatformClient):
    """
    抖音视频发布客户端。

    抖音开放平台文档: https://developer.open-douyin.com/

    注意:
    - 抖音视频发布 API 需要企业认证或特定权限
    - 对于无 API 权限的用户，提供"离线发布包"模式：
      生成符合抖音规范的视频 + 元数据文件 + 图文发布指南

    环境变量:
        DOUYIN_ACCESS_TOKEN: 抖音开放平台 Access Token
        DOUYIN_OPEN_ID: 抖音用户 Open ID
    """

    # 抖音 API 端点
    VIDEO_UPLOAD_URL = "https://open.douyin.com/video/upload/"
    VIDEO_CREATE_URL = "https://open.douyin.com/video/create/"
    VIDEO_PART_INIT_URL = "https://open.douyin.com/video/part/init/"
    VIDEO_PART_UPLOAD_URL = "https://open.douyin.com/video/part/upload/"
    VIDEO_PART_COMPLETE_URL = "https://open.douyin.com/video/part/complete/"

    def __init__(self, config: PlatformPublishConfig = None):
        super().__init__(config or PLATFORM_PRESETS[PublishPlatform.DOUYIN])
        self._access_token = os.environ.get("DOUYIN_ACCESS_TOKEN", "")
        self._open_id = os.environ.get("DOUYIN_OPEN_ID", "")

    def _get_headers(self) -> Dict[str, str]:
        return {
            "access-token": self._access_token,
            "Content-Type": "application/json",
        }

    def _direct_api_upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable] = None,
    ) -> Optional[PublishResult]:
        """
        尝试通过抖音开放平台 API 直接上传。

        如果 API 凭证不可用，返回 None。
        需要企业认证账号。
        """
        if not self._access_token or not self._open_id:
            logger.warning("[Douyin] 缺少 API 凭证 (DOUYIN_ACCESS_TOKEN / DOUYIN_OPEN_ID)")
            return None

        import requests

        try:
            # Step 1: 初始化分片上传
            file_size = os.path.getsize(video_path)
            init_resp = requests.post(
                self.VIDEO_UPLOAD_URL,
                headers=self._get_headers(),
                json={
                    "open_id": self._open_id,
                },
                timeout=30,
            )
            init_data = init_resp.json()

            if init_data.get("data", {}).get("error_code") != 0:
                return PublishResult(
                    platform="douyin",
                    status=PublishStatus.FAILED,
                    error=f"抖音API初始化失败: {init_data.get('data', {}).get('description', '')}",
                    raw_response=init_data,
                )

            upload_id = init_data.get("data", {}).get("upload_id", "")

            # Step 2: 分片上传
            chunk_size = 10 * 1024 * 1024
            total_chunks = (file_size + chunk_size - 1) // chunk_size

            with open(video_path, "rb") as f:
                for i in range(total_chunks):
                    chunk = f.read(chunk_size)
                    part_num = i + 1

                    resp = requests.post(
                        self.VIDEO_PART_UPLOAD_URL,
                        headers={"access-token": self._access_token},
                        data={"upload_id": upload_id, "part_number": part_num},
                        files={"video": (f"chunk_{part_num}", chunk)},
                        timeout=120,
                    )

                    if progress_callback:
                        progress_callback(part_num / total_chunks * 0.8,
                                         f"抖音分片上传 {part_num}/{total_chunks}")

            # Step 3: 完成上传
            complete_resp = requests.post(
                self.VIDEO_PART_COMPLETE_URL,
                headers=self._get_headers(),
                json={
                    "open_id": self._open_id,
                    "upload_id": upload_id,
                },
                timeout=30,
            )

            # Step 4: 创建视频（设置元数据）
            create_data = {
                "open_id": self._open_id,
                "upload_id": upload_id,
                "video_name": metadata.title[:55],
            }
            if metadata.description:
                create_data["video_description"] = metadata.description[:500]

            create_resp = requests.post(
                self.VIDEO_CREATE_URL,
                headers=self._get_headers(),
                json=create_data,
                timeout=30,
            )
            create_result = create_resp.json()

            if progress_callback:
                progress_callback(1.0, "抖音发布完成!")

            return PublishResult(
                platform="douyin",
                status=PublishStatus.PUBLISHED,
                video_id=create_result.get("data", {}).get("item_id", ""),
                message="抖音发布成功",
                raw_response=create_result,
            )

        except Exception as e:
            logger.error(f"[Douyin] API 上传失败: {e}")
            return PublishResult(
                platform="douyin",
                status=PublishStatus.FAILED,
                error=str(e),
            )

    def _generate_offline_package(
        self,
        video_path: str,
        metadata: VideoMetadata,
        output_dir: str = "",
    ) -> PublishResult:
        """
        生成抖音离线发布包。

        包含:
        - 符合规范的视频文件（复制/转码后）
        - 元数据 JSON（标题、描述、标签）
        - 封面图片（如提供）
        - 发布指南 README.txt
        """
        if not output_dir:
            output_dir = os.path.join(os.path.dirname(video_path) or ".", "douyin_package")

        os.makedirs(output_dir, exist_ok=True)

        # 复制视频
        import shutil
        video_name = os.path.basename(video_path)
        dest_video = os.path.join(output_dir, f"douyin_{video_name}")
        if os.path.abspath(video_path) != os.path.abspath(dest_video):
            shutil.copy2(video_path, dest_video)

        # 元数据文件
        package_meta = {
            "title": metadata.title[:self.config.title_max_chars],
            "description": (metadata.description or "")[:self.config.desc_max_chars],
            "tags": metadata.tags[:self.config.tag_max_count],
            "schedule_time": metadata.schedule_time,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "video_file": f"douyin_{video_name}",
        }

        if metadata.cover_path:
            cover_dest = os.path.join(output_dir, f"cover_{os.path.basename(metadata.cover_path)}")
            shutil.copy2(metadata.cover_path, cover_dest)
            package_meta["cover_file"] = os.path.basename(cover_dest)

        meta_path = os.path.join(output_dir, "metadata.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(package_meta, f, ensure_ascii=False, indent=2)

        # 发布指南
        readme = self._generate_douyin_guide(package_meta)
        guide_path = os.path.join(output_dir, "发布指南_README.txt")
        with open(guide_path, "w", encoding="utf-8") as f:
            f.write(readme)

        logger.info(f"[Douyin] 离线发布包已生成: {output_dir}")

        return PublishResult(
            platform="douyin",
            status=PublishStatus.PENDING,
            message=f"离线发布包已生成于: {output_dir}。请按照发布指南手动发布。",
            video_url=output_dir,
        )

    def _generate_douyin_guide(self, meta: Dict) -> str:
        """生成抖音发布图文指南"""
        guide = f"""
╔══════════════════════════════════════════════════════════════╗
║           抖音短视频发布指南 (Douyin Publish Guide)          ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  视频文件: {meta.get('video_file', 'N/A')}
║  标题: {meta.get('title', 'N/A')}
║  描述: {meta.get('description', 'N/A')}
║  标签: {', '.join(meta.get('tags', []))}
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  📱 手机端发布步骤:                                          ║
║                                                              ║
║  1. 将 "{meta.get('video_file', 'video.mp4')}" 传到手机     ║
║     - 微信文件传输助手 / AirDrop / QQ 均可                   ║
║                                                              ║
║  2. 打开抖音 App，点击底部 [+] 号                            ║
║                                                              ║
║  3. 选择「上传」→ 选择视频文件                               ║
║                                                              ║
║  4. 编辑页面设置:                                            ║
║     - 标题粘贴: {meta.get('title', '见上方')}
║     - 添加话题标签: {' '.join('#' + t for t in meta.get('tags', []))}
║                                                              ║
║  5. 设置封面 (如提供了封面文件)                              ║
║                                                              ║
║  6. 选择「发布」或「定时发布」                               ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  💻 电脑端发布步骤 (抖音创作服务平台):                       ║
║                                                              ║
║  1. 打开 https://creator.douyin.com/                        ║
║  2. 登录您的抖音创作者账号                                   ║
║  3. 点击「发布视频」→ 上传视频文件                           ║
║  4. 填写标题、描述、标签                                     ║
║  5. 设置封面和定时发布                                       ║
║  6. 点击「发布」                                             ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  🔧 如需 API 自动发布，请配置以下环境变量:                   ║
║     DOUYIN_ACCESS_TOKEN=<您的抖音开放平台Access Token>       ║
║     DOUYIN_OPEN_ID=<您的抖音用户Open ID>                    ║
║                                                              ║
║  获取流程:                                                   ║
║  1. https://developer.open-douyin.com/ 注册开发者           ║
║  2. 创建应用 → 获取 Client Key / Client Secret               ║
║  3. 完成企业认证 (需要营业执照)                              ║
║  4. 获取 Access Token                                        ║
║                                                              ║
║  视频规格要求:                                               ║
║  - 格式: MP4 / MOV                                           ║
║  - 分辨率: 推荐 1080x1920 (9:16 竖屏)                       ║
║  - 时长: ≤30分钟 (普通用户)                                  ║
║  - 大小: ≤4GB                                                ║
║  - 编码: H.264 + AAC                                         ║
║  - 帧率: 推荐 30fps                                          ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
        return guide

    def upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable] = None,
    ) -> PublishResult:
        """抖音上传入口"""
        # 验证
        valid, msg = self.validate_video(video_path)
        if not valid:
            return PublishResult(
                platform="douyin",
                status=PublishStatus.FAILED,
                error=msg,
            )

        # 尝试 API 直接上传
        api_result = self._direct_api_upload(video_path, metadata, progress_callback)
        if api_result is not None:
            return api_result

        # 回退：生成离线发布包
        logger.info("[Douyin] API 不可用，生成离线发布包...")
        if progress_callback:
            progress_callback(0.5, "抖音: 生成离线发布包...")

        result = self._generate_offline_package(video_path, metadata)

        if progress_callback:
            progress_callback(1.0, "抖音: 离线发布包已生成")

        return result


# ============================================================================
# YouTube 客户端
# ============================================================================

class YouTubeClient(BasePlatformClient):
    """
    YouTube 视频发布客户端。

    使用 YouTube Data API v3 + Google OAuth2。

    文档: https://developers.google.com/youtube/v3

    环境变量:
        YOUTUBE_API_KEY: YouTube Data API Key (用于公开数据)
        YOUTUBE_CLIENT_ID: OAuth2 Client ID
        YOUTUBE_CLIENT_SECRET: OAuth2 Client Secret
        YOUTUBE_REFRESH_TOKEN: OAuth2 Refresh Token
        YOUTUBE_ACCESS_TOKEN: OAuth2 Access Token (短期)
        YOUTUBE_CLIENT_SECRETS_FILE: client_secrets.json 文件路径
    """

    YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
    YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"
    THUMBNAIL_URL = "https://www.googleapis.com/youtube/v3/thumbnails/set"

    def __init__(self, config: PlatformPublishConfig = None):
        super().__init__(config or PLATFORM_PRESETS[PublishPlatform.YOUTUBE])
        self._api_key = os.environ.get("YOUTUBE_API_KEY", "")
        self._client_id = os.environ.get("YOUTUBE_CLIENT_ID", "")
        self._client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
        self._refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
        self._access_token = os.environ.get("YOUTUBE_ACCESS_TOKEN", "")
        self._secrets_file = os.environ.get("YOUTUBE_CLIENT_SECRETS_FILE", "")
        self._service = None

    def _get_access_token(self) -> Optional[str]:
        """
        获取有效的 Access Token。
        优先级: YOUTUBE_ACCESS_TOKEN > Refresh Token > client_secrets.json
        """
        # 1. 直接使用环境变量中的 Access Token
        if self._access_token:
            return self._access_token

        # 2. 使用 Refresh Token 刷新
        if self._refresh_token and self._client_id and self._client_secret:
            return self._refresh_access_token()

        # 3. 使用 client_secrets.json
        if self._secrets_file and os.path.exists(self._secrets_file):
            return self._load_token_from_file()

        return None

    def _refresh_access_token(self) -> Optional[str]:
        """使用 Refresh Token 获取新的 Access Token"""
        import requests

        try:
            resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )
            data = resp.json()
            self._access_token = data.get("access_token", "")
            return self._access_token
        except Exception as e:
            logger.error(f"[YouTube] Token 刷新失败: {e}")
            return None

    def _load_token_from_file(self) -> Optional[str]:
        """从 client_secrets.json 加载或刷新 Token"""
        try:
            with open(self._secrets_file, "r") as f:
                secrets = json.load(f)

            # 检查是否有已保存的 token
            token_path = os.path.join(
                os.path.dirname(self._secrets_file),
                "youtube_token.json",
            )
            if os.path.exists(token_path):
                with open(token_path, "r") as f:
                    token_data = json.load(f)
                self._access_token = token_data.get("access_token", "")
                self._refresh_token = token_data.get("refresh_token", "")

                # 如果 access_token 过期，刷新
                if self._refresh_token:
                    self._client_id = secrets.get("installed", {}).get("client_id", "")
                    self._client_secret = secrets.get("installed", {}).get("client_secret", "")
                    return self._refresh_access_token()

                return self._access_token
        except Exception as e:
            logger.error(f"[YouTube] 加载 Token 文件失败: {e}")

        return None

    def _sdk_upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable] = None,
    ) -> Optional[PublishResult]:
        """
        使用 google-api-python-client SDK 上传。
        如果 SDK 不可用，返回 None。
        """
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from google.oauth2.credentials import Credentials
            import google.auth.transport.requests
        except ImportError:
            logger.warning("[YouTube] google-api-python-client 未安装")
            return None

        access_token = self._get_access_token()
        if not access_token:
            return PublishResult(
                platform="youtube",
                status=PublishStatus.FAILED,
                error="无法获取 YouTube 有效 Access Token。请配置 YOUTUBE_ACCESS_TOKEN 或 YOUTUBE_REFRESH_TOKEN",
            )

        try:
            credentials = Credentials(token=access_token)

            youtube = build(
                "youtube", "v3",
                credentials=credentials,
                cache_discovery=False,
            )

            # 构建请求体
            body = {
                "snippet": {
                    "title": metadata.title[:self.config.title_max_chars],
                    "description": (metadata.description or "")[:self.config.desc_max_chars],
                    "tags": metadata.tags[:self.config.tag_max_count],
                    "categoryId": metadata.category_id or "22",  # 默认: People & Blogs
                },
                "status": {
                    "privacyStatus": self._map_visibility(metadata.visibility),
                    "selfDeclaredMadeForKids": False,
                },
            }

            # 定时发布
            if metadata.schedule_time:
                body["status"]["publishAt"] = metadata.schedule_time

            # 上传
            if progress_callback:
                progress_callback(0.0, "YouTube: 开始上传...")

            media = MediaFileUpload(
                video_path,
                mimetype="video/*",
                resumable=True,
                chunksize=10 * 1024 * 1024,  # 10MB
            )

            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )

            # 分片上传回调
            response = None
            last_progress = 0
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pct = status.progress()
                    if pct is not None and pct - last_progress > 0.05:
                        last_progress = pct
                        if progress_callback:
                            progress_callback(pct * 0.9, f"YouTube上传中... {int(pct * 100)}%")

            video_id = response.get("id", "")
            video_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""

            if progress_callback:
                progress_callback(0.9, "YouTube: 设置缩略图/播放列表...")

            # 设置缩略图
            if metadata.custom_thumbnail_path and video_id:
                self._set_thumbnail(youtube, video_id, metadata.custom_thumbnail_path)

            # 添加到播放列表
            if metadata.playlist_id and video_id:
                self._add_to_playlist(youtube, video_id, metadata.playlist_id)

            if progress_callback:
                progress_callback(1.0, "YouTube发布完成!")

            status = PublishStatus.SCHEDULED if metadata.schedule_time else PublishStatus.PUBLISHED
            return PublishResult(
                platform="youtube",
                status=status,
                video_id=video_id,
                video_url=video_url,
                message="YouTube发布成功",
                raw_response=response,
            )

        except Exception as e:
            logger.error(f"[YouTube] SDK 上传失败: {e}")
            return PublishResult(
                platform="youtube",
                status=PublishStatus.FAILED,
                error=str(e),
            )

    def _manual_upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable] = None,
    ) -> PublishResult:
        """
        手动 HTTP 实现 YouTube 上传（分片上传）。
        使用 YouTube Resumable Upload 协议。
        """
        import requests

        access_token = self._get_access_token()
        if not access_token:
            return PublishResult(
                platform="youtube",
                status=PublishStatus.FAILED,
                error="无法获取 YouTube Access Token",
            )

        file_size = os.path.getsize(video_path)
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Upload-Content-Type": "video/*",
            "X-Upload-Content-Length": str(file_size),
        }

        # Step 1: 初始化上传会话
        snippet = {
            "snippet": {
                "title": metadata.title[:self.config.title_max_chars],
                "description": (metadata.description or "")[:self.config.desc_max_chars],
                "tags": metadata.tags[:self.config.tag_max_count],
                "categoryId": metadata.category_id or "22",
            },
            "status": {
                "privacyStatus": self._map_visibility(metadata.visibility),
                "selfDeclaredMadeForKids": False,
            },
        }

        try:
            init_resp = requests.post(
                f"{self.YOUTUBE_UPLOAD_URL}?uploadType=resumable&part=snippet,status",
                headers={
                    **headers,
                    "Content-Type": "application/json",
                },
                json=snippet,
                timeout=30,
            )

            if init_resp.status_code != 200:
                return PublishResult(
                    platform="youtube",
                    status=PublishStatus.FAILED,
                    error=f"YouTube 初始化失败: HTTP {init_resp.status_code} - {init_resp.text[:500]}",
                )

            upload_url = init_resp.headers.get("Location", "")
            if not upload_url:
                return PublishResult(
                    platform="youtube",
                    status=PublishStatus.FAILED,
                    error="YouTube 未返回上传 URL",
                )

            # Step 2: 分片上传
            chunk_size = 10 * 1024 * 1024
            total_chunks = (file_size + chunk_size - 1) // chunk_size

            with open(video_path, "rb") as f:
                for i in range(total_chunks):
                    chunk = f.read(chunk_size)
                    start = i * chunk_size
                    end = min(start + chunk_size, file_size) - 1

                    chunk_headers = {
                        "Content-Range": f"bytes {start}-{end}/{file_size}",
                    }

                    for attempt in range(3):
                        try:
                            resp = requests.put(
                                upload_url,
                                data=chunk,
                                headers=chunk_headers,
                                timeout=120,
                            )
                            if resp.status_code in (200, 201, 308):
                                break
                        except Exception as e:
                            if attempt == 2:
                                return PublishResult(
                                    platform="youtube",
                                    status=PublishStatus.FAILED,
                                    error=f"YouTube 分片 {i + 1} 上传失败: {e}",
                                )
                            time.sleep(2 ** attempt)

                    if progress_callback:
                        progress_callback((i + 1) / total_chunks * 0.9,
                                         f"YouTube上传 {i + 1}/{total_chunks}")

            # 最终响应
            final_response = resp.json() if resp.status_code in (200, 201) else {}
            video_id = final_response.get("id", "")

            if progress_callback:
                progress_callback(1.0, "YouTube发布完成!")

            return PublishResult(
                platform="youtube",
                status=PublishStatus.PUBLISHED,
                video_id=video_id,
                video_url=f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
                message="YouTube发布成功",
                raw_response=final_response,
            )

        except Exception as e:
            return PublishResult(
                platform="youtube",
                status=PublishStatus.FAILED,
                error=f"YouTube 上传异常: {e}",
            )

    def _map_visibility(self, visibility: VideoVisibility) -> str:
        """映射可见性到 YouTube API 参数"""
        mapping = {
            VideoVisibility.PUBLIC: "public",
            VideoVisibility.PRIVATE: "private",
            VideoVisibility.UNLISTED: "unlisted",
        }
        return mapping.get(visibility, "public")

    def _set_thumbnail(self, youtube_service, video_id: str, thumbnail_path: str):
        """设置YouTube视频缩略图"""
        try:
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            youtube_service.thumbnails().set(
                videoId=video_id,
                media_body=media,
            ).execute()
            logger.info(f"[YouTube] 缩略图设置成功: {video_id}")
        except Exception as e:
            logger.error(f"[YouTube] 缩略图设置失败: {e}")

    def _add_to_playlist(self, youtube_service, video_id: str, playlist_id: str):
        """将视频添加到播放列表"""
        try:
            youtube_service.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id,
                        },
                    },
                },
            ).execute()
            logger.info(f"[YouTube] 已添加到播放列表 {playlist_id}: {video_id}")
        except Exception as e:
            logger.error(f"[YouTube] 播放列表添加失败: {e}")

    def upload(
        self,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable] = None,
    ) -> PublishResult:
        """YouTube 上传入口"""
        # 验证
        valid, msg = self.validate_video(video_path)
        if not valid:
            return PublishResult(
                platform="youtube",
                status=PublishStatus.FAILED,
                error=msg,
            )

        # 尝试 SDK 上传
        sdk_result = self._sdk_upload(video_path, metadata, progress_callback)
        if sdk_result is not None:
            return sdk_result

        # 回退手动上传
        return self._manual_upload(video_path, metadata, progress_callback)


# ============================================================================
# 发布队列 (Publish Queue with Retry)
# ============================================================================

@dataclass(order=True)
class PublishTask:
    """发布队列任务"""
    priority: int
    task_id: str = field(compare=False)
    platform: PublishPlatform = field(compare=False)
    video_path: str = field(compare=False)
    metadata: VideoMetadata = field(compare=False)
    created_at: float = field(compare=False, default_factory=time.time)
    max_retries: int = field(compare=False, default=3)
    retry_delay_sec: int = field(compare=False, default=60)
    retry_count: int = field(compare=False, default=0)
    callback: Optional[Callable] = field(compare=False, default=None)


class PublishQueue:
    """
    发布队列管理器。

    特性:
    - 优先级队列（支持高优先级插队）
    - 自动重试（指数退避）
    - 并发控制（按平台限制）
    - 回调通知
    """

    def __init__(self, max_workers: int = 2):
        self._queue: PriorityQueue = PriorityQueue()
        self._results: Dict[str, PublishResult] = {}
        self._active: Dict[str, PublishTask] = {}
        self._rate_limiter = PlatformRateLimiter()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        self._running = False
        self._clients: Dict[PublishPlatform, BasePlatformClient] = {
            PublishPlatform.BILIBILI: BilibiliClient(),
            PublishPlatform.DOUYIN: DouyinClient(),
            PublishPlatform.YOUTUBE: YouTubeClient(),
        }

    def enqueue(
        self,
        platform: PublishPlatform,
        video_path: str,
        metadata: VideoMetadata,
        priority: int = 10,
        max_retries: int = 3,
        retry_delay_sec: int = 60,
        callback: Optional[Callable[[PublishResult], None]] = None,
    ) -> str:
        """
        将发布任务加入队列。

        Args:
            platform: 目标平台
            video_path: 视频文件路径
            metadata: 视频元数据
            priority: 优先级（越小越高）
            max_retries: 最大重试次数
            retry_delay_sec: 重试间隔
            callback: 完成回调

        Returns:
            task_id: 任务ID
        """
        task_id = str(uuid.uuid4())[:8]
        task = PublishTask(
            priority=priority,
            task_id=task_id,
            platform=platform,
            video_path=video_path,
            metadata=metadata,
            max_retries=max_retries,
            retry_delay_sec=retry_delay_sec,
            callback=callback,
        )

        self._queue.put(task)
        self._results[task_id] = PublishResult(
            platform=platform.value,
            status=PublishStatus.PENDING,
            message="已加入发布队列",
        )

        logger.info(f"[PublishQueue] 任务已入队: {task_id} -> {platform.value}: {metadata.title[:30]}")

        # 触发处理
        self._process_next()

        return task_id

    def _process_next(self):
        """处理队列中的下一个任务"""
        if self._queue.empty():
            return

        with self._lock:
            if len(self._active) >= self._executor._max_workers:
                return

            try:
                task = self._queue.get_nowait()
            except:
                return

            self._active[task.task_id] = task
            self._update_result(task.task_id, status=PublishStatus.UPLOADING, message="开始上传...")

            future = self._executor.submit(self._execute_task, task)
            self._futures[task.task_id] = future
            future.add_done_callback(lambda f, tid=task.task_id: self._on_task_done(tid))

    def _execute_task(self, task: PublishTask) -> PublishResult:
        """执行单个发布任务"""
        logger.info(f"[PublishQueue] 执行任务: {task.task_id} -> {task.platform.value}")

        # 速率限制检查
        allowed, reason = self._rate_limiter.check_and_acquire(task.platform)
        if not allowed:
            result = PublishResult(
                platform=task.platform.value,
                status=PublishStatus.FAILED,
                error=reason,
                message=f"速率限制: {reason}",
            )
            # 延迟重试
            if task.retry_count < task.max_retries:
                self._schedule_retry(task)
            return result

        # 获取客户端
        client = self._clients.get(task.platform)
        if not client:
            return PublishResult(
                platform=task.platform.value,
                status=PublishStatus.FAILED,
                error=f"无可用客户端: {task.platform.value}",
            )

        # 执行上传
        start_time = time.time()
        try:
            result = client.upload(
                task.video_path,
                task.metadata,
                progress_callback=lambda p, m: logger.debug(
                    f"[{task.task_id}] {m} ({p:.0%})"
                ),
            )
            result.elapsed_sec = time.time() - start_time
            result.retry_count = task.retry_count

            # 失败重试
            if result.status == PublishStatus.FAILED and task.retry_count < task.max_retries:
                logger.warning(
                    f"[PublishQueue] 任务 {task.task_id} 失败，"
                    f"将重试 ({task.retry_count + 1}/{task.max_retries}): {result.error}"
                )
                return self._schedule_retry(task, result)

            return result

        except Exception as e:
            elapsed = time.time() - start_time
            result = PublishResult(
                platform=task.platform.value,
                status=PublishStatus.FAILED,
                error=str(e),
                elapsed_sec=elapsed,
                retry_count=task.retry_count,
            )
            if task.retry_count < task.max_retries:
                return self._schedule_retry(task, result)
            return result

    def _schedule_retry(self, task: PublishTask, failed_result: Optional[PublishResult] = None) -> PublishResult:
        """安排重试"""
        retry_count = task.retry_count + 1
        delay = task.retry_delay_sec * (2 ** (retry_count - 1))  # 指数退避

        logger.info(f"[PublishQueue] 任务 {task.task_id} 将在 {delay}s 后重试 (第 {retry_count} 次)")

        # 创建新任务（更新重试计数和优先级）
        retry_task = PublishTask(
            priority=task.priority + retry_count,  # 重试优先级降低
            task_id=task.task_id,
            platform=task.platform,
            video_path=task.video_path,
            metadata=task.metadata,
            max_retries=task.max_retries,
            retry_delay_sec=task.retry_delay_sec,
            retry_count=retry_count,
            callback=task.callback,
        )

        self._update_result(
            task.task_id,
            status=PublishStatus.RETRYING,
            message=f"将在 {delay}s 后重试 ({retry_count}/{task.max_retries})",
            error=failed_result.error if failed_result else "",
            retry_count=retry_count,
        )

        # 延迟入队
        threading.Timer(delay, self._retry_enqueue, args=[retry_task]).start()

        return failed_result or PublishResult(
            platform=task.platform.value,
            status=PublishStatus.RETRYING,
            message=f"将在 {delay}s 后重试",
        )

    def _retry_enqueue(self, task: PublishTask):
        """重试任务入队"""
        self._queue.put(task)
        self._process_next()

    def _on_task_done(self, task_id: str):
        """任务完成回调"""
        with self._lock:
            task = self._active.pop(task_id, None)
            future = self._futures.pop(task_id, None)

            if future and future.done():
                try:
                    result = future.result()
                    self._results[task_id] = result
                    logger.info(
                        f"[PublishQueue] 任务完成: {task_id} -> {result.status.value}: {result.message[:100]}"
                    )
                except Exception as e:
                    self._results[task_id] = PublishResult(
                        platform=task.platform.value if task else "",
                        status=PublishStatus.FAILED,
                        error=str(e),
                    )
                    logger.error(f"[PublishQueue] 任务异常: {task_id}: {e}")

            # 触发回调
            if task and task.callback:
                try:
                    result = self._results.get(task_id)
                    if result:
                        task.callback(result)
                except Exception as e:
                    logger.error(f"[PublishQueue] 回调异常: {e}")

        # 处理下一个任务
        self._process_next()

    def _update_result(self, task_id: str, **kwargs):
        """更新任务结果状态"""
        with self._lock:
            if task_id in self._results:
                for key, value in kwargs.items():
                    if hasattr(self._results[task_id], key):
                        setattr(self._results[task_id], key, value)

    def get_status(self, task_id: str) -> Optional[PublishResult]:
        """获取任务状态"""
        return self._results.get(task_id)

    def get_all_statuses(self) -> Dict[str, PublishResult]:
        """获取所有任务状态"""
        with self._lock:
            return dict(self._results)

    def get_queue_stats(self) -> Dict[str, Any]:
        """获取队列统计"""
        with self._lock:
            return {
                "queue_size": self._queue.qsize(),
                "active_tasks": len(self._active),
                "total_tasks": len(self._results),
                "completed": sum(
                    1 for r in self._results.values()
                    if r.status == PublishStatus.PUBLISHED
                ),
                "failed": sum(
                    1 for r in self._results.values()
                    if r.status == PublishStatus.FAILED
                ),
                "rate_limits": {
                    p.value: self._rate_limiter.get_stats(p)
                    for p in PublishPlatform
                },
            }

    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        with self._lock:
            # 如果尚未开始，从活跃列表移除
            if task_id in self._active:
                future = self._futures.get(task_id)
                if future and not future.done():
                    future.cancel()
                self._active.pop(task_id, None)
                self._futures.pop(task_id, None)
                self._results[task_id] = PublishResult(
                    platform=self._results[task_id].platform if task_id in self._results else "",
                    status=PublishStatus.CANCELLED,
                    message="任务已取消",
                )
                return True
        return False

    def shutdown(self):
        """关闭队列"""
        self._running = False
        self._executor.shutdown(wait=True)
        logger.info("[PublishQueue] 发布队列已关闭")


# ============================================================================
# 统一发布接口 (PlatformPublisher)
# ============================================================================

class PlatformPublisher:
    """
    多平台视频发布器 —— 统一入口。

    用法:
        publisher = PlatformPublisher()
        result = publisher.publish(
            platform=PublishPlatform.BILIBILI,
            video_path="/path/to/video.mp4",
            metadata=VideoMetadata(
                title="我的视频",
                description="视频描述",
                tags=["标签1", "标签2"],
            ),
        )

    异步队列模式:
        publisher = PlatformPublisher(use_queue=True)
        task_id = publisher.publish_async(
            platform=PublishPlatform.YOUTUBE,
            video_path="/path/to/video.mp4",
            metadata=VideoMetadata(title="队列发布测试"),
        )
        # ... 稍后查询
        status = publisher.get_publish_status(task_id)
    """

    def __init__(self, use_queue: bool = False, max_workers: int = 2):
        """
        初始化发布器。

        Args:
            use_queue: 是否使用发布队列（异步模式）
            max_workers: 队列最大并发数
        """
        self.use_queue = use_queue
        self._queue: Optional[PublishQueue] = None
        self._rate_limiter = PlatformRateLimiter()

        # 初始化各平台客户端
        self._clients: Dict[PublishPlatform, BasePlatformClient] = {
            PublishPlatform.BILIBILI: BilibiliClient(),
            PublishPlatform.DOUYIN: DouyinClient(),
            PublishPlatform.YOUTUBE: YouTubeClient(),
        }

        if use_queue:
            self._queue = PublishQueue(max_workers=max_workers)

    def publish(
        self,
        platform: PublishPlatform,
        video_path: str,
        metadata: VideoMetadata,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> PublishResult:
        """
        同步发布视频到指定平台。

        Args:
            platform: 目标平台 (BILIBILI, DOUYIN, YOUTUBE)
            video_path: 视频文件路径
            metadata: 视频元数据 (标题/描述/标签/封面/定时等)
            progress_callback: 进度回调 (0.0~1.0, 状态描述)

        Returns:
            PublishResult: 包含状态、视频ID、URL等

        示例:
            result = publisher.publish(
                platform=PublishPlatform.BILIBILI,
                video_path="/videos/my_video.mp4",
                metadata=VideoMetadata(
                    title="精彩集锦 #1",
                    description="本周精彩内容汇总",
                    tags=["游戏", "集锦", "2024"],
                    cover_path="/videos/cover.jpg",
                    schedule_time="2024-12-25T10:00:00+08:00",
                ),
            )
            if result.status == PublishStatus.PUBLISHED:
                print(f"发布成功: {result.video_url}")
        """
        # 验证元数据
        valid, errors = MetadataValidator.validate(metadata, platform)
        if not valid:
            return PublishResult(
                platform=platform.value,
                status=PublishStatus.FAILED,
                error="; ".join(errors),
                message="元数据验证失败",
            )

        # 速率限制检查
        allowed, reason = self._rate_limiter.check_and_acquire(platform)
        if not allowed:
            return PublishResult(
                platform=platform.value,
                status=PublishStatus.FAILED,
                error=reason,
                message=f"速率限制: {reason}",
            )

        # 获取客户端并上传
        client = self._clients.get(platform)
        if not client:
            return PublishResult(
                platform=platform.value,
                status=PublishStatus.FAILED,
                error=f"不支持的平台: {platform.value}",
                message=f"平台 {platform.value} 尚不支持",
            )

        start_time = time.time()
        logger.info(f"[PlatformPublisher] 开始发布到 {platform.value}: {metadata.title[:40]}")

        try:
            result = client.upload(video_path, metadata, progress_callback)
            result.elapsed_sec = time.time() - start_time
            result.platform = platform.value
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"[PlatformPublisher] 发布异常: {e}")
            return PublishResult(
                platform=platform.value,
                status=PublishStatus.FAILED,
                error=str(e),
                elapsed_sec=elapsed,
            )

    def publish_async(
        self,
        platform: PublishPlatform,
        video_path: str,
        metadata: VideoMetadata,
        priority: int = 10,
        max_retries: int = 3,
        callback: Optional[Callable[[PublishResult], None]] = None,
    ) -> str:
        """
        异步发布（使用队列）。

        Args:
            platform: 目标平台
            video_path: 视频文件路径
            metadata: 视频元数据
            priority: 优先级 (越小越高)
            max_retries: 最大重试次数
            callback: 完成回调

        Returns:
            task_id: 任务ID（用于查询状态）
        """
        if not self._queue:
            self._queue = PublishQueue()
            self.use_queue = True

        # 验证元数据
        valid, errors = MetadataValidator.validate(metadata, platform)
        if not valid:
            task_id = str(uuid.uuid4())[:8]
            self._queue._results[task_id] = PublishResult(
                platform=platform.value,
                status=PublishStatus.FAILED,
                error="; ".join(errors),
                message="元数据验证失败",
            )
            return task_id

        return self._queue.enqueue(
            platform=platform,
            video_path=video_path,
            metadata=metadata,
            priority=priority,
            max_retries=max_retries,
            callback=callback,
        )

    def get_publish_status(self, task_id: str) -> Optional[PublishResult]:
        """查询异步发布任务状态"""
        if self._queue:
            return self._queue.get_status(task_id)
        return PublishResult(
            platform="",
            status=PublishStatus.FAILED,
            error="未启用队列模式。请使用 publish_async() 或初始化时设置 use_queue=True",
        )

    def get_queue_stats(self) -> Dict[str, Any]:
        """获取发布队列统计"""
        if self._queue:
            return self._queue.get_queue_stats()
        return {"error": "队列未启用"}

    def cancel_publish(self, task_id: str) -> bool:
        """取消异步发布任务"""
        if self._queue:
            return self._queue.cancel(task_id)
        return False

    def get_platform_config(self, platform: PublishPlatform) -> Optional[PlatformPublishConfig]:
        """获取平台发布配置"""
        return PLATFORM_PRESETS.get(platform)

    def get_all_platform_configs(self) -> Dict[str, PlatformPublishConfig]:
        """获取所有平台配置"""
        return {p.value: cfg for p, cfg in PLATFORM_PRESETS.items()}

    def get_rate_limit_stats(self, platform: PublishPlatform) -> Dict[str, Any]:
        """获取平台速率限制统计"""
        return self._rate_limiter.get_stats(platform)

    def shutdown(self):
        """关闭发布器"""
        if self._queue:
            self._queue.shutdown()


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    # 简单自测
    print("=== PlatformPublisher 自测 ===")
    publisher = PlatformPublisher()

    # 测试配置获取
    for p in PublishPlatform:
        cfg = publisher.get_platform_config(p)
        print(f"\n[{p.value}]")
        print(f"  分辨率: {cfg.max_resolution}")
        print(f"  时长上限: {cfg.max_duration_sec // 60} 分钟")
        print(f"  标题限制: {cfg.title_min_chars}-{cfg.title_max_chars} 字符")
        print(f"  标签上限: {cfg.tag_max_count} 个")
        print(f"  支持格式: {cfg.supported_formats}")

    # 测试元数据验证
    print("\n=== 元数据验证测试 ===")
    meta = VideoMetadata(
        title="A" * 100,  # B站限制80字符，会失败
        tags=["t" * 25],  # B站标签限制20字符，会失败
    )
    valid, errors = MetadataValidator.validate(meta, PublishPlatform.BILIBILI)
    print(f"B站验证: {'通过' if valid else '失败'}")
    for e in errors:
        print(f"  - {e}")

    # 有效元数据
    meta2 = VideoMetadata(
        title="精彩视频",
        description="这是一个测试视频",
        tags=["测试", "demo"],
    )
    valid2, _ = MetadataValidator.validate(meta2, PublishPlatform.BILIBILI)
    print(f"B站验证(有效): {'通过' if valid2 else '失败'}")

    # 测试杜比离线包生成
    print("\n=== 抖音离线包测试 ===")
    douyin_client = DouyinClient()
    result = douyin_client._generate_offline_package(
        "/tmp/test_video.mp4",
        VideoMetadata(title="测试抖音视频", tags=["测试", "quanquan"]),
        output_dir="/tmp/douyin_test_package",
    )
    print(f"结果: {result.status.value} - {result.message[:100]}")

    # 速率限制测试
    print("\n=== 速率限制测试 ===")
    limiter = PlatformRateLimiter()
    allowed, reason = limiter.check_and_acquire(PublishPlatform.BILIBILI)
    print(f"B站上传许可: {'允许' if allowed else '拒绝'} - {reason}")
    stats = limiter.get_stats(PublishPlatform.BILIBILI)
    print(f"  统计: 本小时 {stats['uploads_this_hour']}/{stats['hourly_limit']}")

    print("\n=== 所有测试完成 ===")
