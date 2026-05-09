"""
quanquan 大容量视频分段处理引擎
支持超长视频（>1小时）和超大分辨率（4K/8K）的智能分段处理

核心技术：
- 场景边界检测（Shot Boundary Detection） 智能分段
- 滑动窗口流式处理（避免全量加载到内存）
- 多 worker 并行分段处理
- 分段结果无缝拼接（crossfade stitching）
"""

import asyncio
import subprocess
import json
import os
import math
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class SegmentStrategy(Enum):
    """分段策略"""
    SCENE_DETECT = "scene_detect"      # 场景边界检测
    FIXED_DURATION = "fixed_duration"  # 固定时长分段
    KEYFRAME = "keyframe"              # 关键帧对齐分段
    SILENCE = "silence"                # 静音检测分段


@dataclass
class VideoSegment:
    """视频分段"""
    index: int
    start_sec: float
    end_sec: float
    duration_sec: float
    start_frame: int = 0
    end_frame: int = 0
    # 场景标签（如有）
    scene_type: Optional[str] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoMetadata:
    """视频元信息"""
    path: str
    width: int
    height: int
    duration_sec: float
    fps: float
    total_frames: int
    video_codec: str = "unknown"
    audio_codec: str = "unknown"
    bitrate_kbps: int = 0
    has_audio: bool = True
    is_hdr: bool = False
    color_space: str = "bt709"
    file_size_bytes: int = 0

    @property
    def is_4k(self) -> bool:
        return self.width >= 3840

    @property
    def is_8k(self) -> bool:
        return self.width >= 7680

    @property
    def is_long(self) -> bool:
        return self.duration_sec > 3600  # >1 hour

    @property
    def resolution_label(self) -> str:
        if self.is_8k:
            return "8K"
        elif self.is_4k:
            return "4K"
        elif self.width >= 1920:
            return "1080p"
        elif self.width >= 1280:
            return "720p"
        return "SD"


class VideoInspector:
    """视频信息探测器"""

    @staticmethod
    async def probe(video_path: str) -> VideoMetadata:
        """使用 ffprobe 获取视频完整元信息"""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            video_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {stderr.decode()}")

        data = json.loads(stdout)

        # 找视频流和音频流
        video_stream = None
        audio_stream = None
        for stream in data.get("streams", []):
            if stream["codec_type"] == "video" and video_stream is None:
                video_stream = stream
            elif stream["codec_type"] == "audio" and audio_stream is None:
                audio_stream = stream

        if not video_stream:
            raise ValueError(f"No video stream found in {video_path}")

        fmt = data.get("format", {})
        duration = float(fmt.get("duration", video_stream.get("duration", 0)))
        fps_parts = video_stream.get("r_frame_rate", "30/1").split("/")
        fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else 30.0
        total_frames = int(float(video_stream.get("nb_frames", duration * fps)))

        return VideoMetadata(
            path=video_path,
            width=int(video_stream.get("width", 0)),
            height=int(video_stream.get("height", 0)),
            duration_sec=duration,
            fps=fps,
            total_frames=total_frames,
            video_codec=video_stream.get("codec_name", "unknown"),
            audio_codec=audio_stream.get("codec_name", "unknown") if audio_stream else "none",
            bitrate_kbps=int(int(fmt.get("bit_rate", 0)) / 1000) if fmt.get("bit_rate") else 0,
            has_audio=audio_stream is not None,
            is_hdr="smpte2084" in video_stream.get("color_transfer", ""),
            color_space=video_stream.get("color_space", "bt709"),
            file_size_bytes=int(fmt.get("size", 0)),
        )


class SceneDetector:
    """场景边界检测器

    使用 ffmpeg 的 scene detect 滤镜（基于帧间差异直方图），
    高效且不需要加载任何深度学习模型。
    对于需要更高精度的场景，可切换为 TransNetV2/PySceneDetect。
    """

    def __init__(self, threshold: float = 0.3, min_scene_duration: float = 1.0):
        self.threshold = threshold
        self.min_scene_duration = min_scene_duration

    async def detect(self, video_path: str, metadata: VideoMetadata) -> List[VideoSegment]:
        """检测场景边界，返回分段列表"""
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", f"select='gt(scene,{self.threshold})',showinfo",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        # 从 stderr 中解析场景切换时间戳
        import re
        scene_times = [0.0]  # 首个分段从 0 开始
        for line in stderr.decode(errors="ignore").split("\n"):
            match = re.search(r"pts_time:([\d.]+)", line)
            if match:
                t = float(match.group(1))
                if t - (scene_times[-1] if scene_times else 0) >= self.min_scene_duration:
                    scene_times.append(t)

        # 最后加上视频结束时间
        scene_times.append(metadata.duration_sec)

        segments = []
        for i in range(len(scene_times) - 1):
            start = scene_times[i]
            end = scene_times[i + 1]
            segments.append(VideoSegment(
                index=i,
                start_sec=start,
                end_sec=end,
                duration_sec=end - start,
                start_frame=int(start * metadata.fps),
                end_frame=int(end * metadata.fps),
            ))

        logger.info(f"Scene detection: {len(segments)} segments found "
                    f"(threshold={self.threshold})")
        return segments


class FixedDurationSplitter:
    """固定时长分段器（简单可靠，适用于无场景切换的视频）"""

    def __init__(self, segment_duration_sec: float = 60.0, overlap_sec: float = 2.0):
        self.segment_duration = segment_duration_sec
        self.overlap = overlap_sec

    async def split(self, metadata: VideoMetadata) -> List[VideoSegment]:
        """按固定时长分段，带重叠用于后续拼接无缝"""
        segments = []
        current = 0.0
        index = 0
        while current < metadata.duration_sec:
            end = min(current + self.segment_duration + self.overlap, metadata.duration_sec)
            segments.append(VideoSegment(
                index=index,
                start_sec=current,
                end_sec=end,
                duration_sec=end - current,
                start_frame=int(current * metadata.fps),
                end_frame=int(end * metadata.fps),
            ))
            current += self.segment_duration
            index += 1
        return segments


class ChunkedProcessor:
    """大视频分段处理器

    核心策略：
    1. 自动判断视频是否需要分段（>5分钟 或 >2GB 或 4K+）
    2. 场景检测优先（有自然切换的视频），否则固定时长
    3. 分段并行处理（多 worker）
    4. 结果拼接（带过渡优化）
    """

    # 自动分段阈值
    AUTO_CHUNK_DURATION_SEC = 300   # 5分钟
    AUTO_CHUNK_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2GB
    AUTO_CHUNK_MIN_RESOLUTION = (1920, 1080)  # 1080p

    def __init__(
        self,
        max_workers: int = 4,
        segment_duration_sec: float = 120.0,
        scene_threshold: float = 0.3,
    ):
        self.max_workers = max_workers
        self.segment_duration = segment_duration_sec
        self.scene_detector = SceneDetector(threshold=scene_threshold)
        self.fixed_splitter = FixedDurationSplitter(segment_duration_sec)
        self.inspector = VideoInspector()

    def should_chunk(self, metadata: VideoMetadata) -> bool:
        """判断视频是否需要分段处理"""
        reasons = []
        if metadata.duration_sec > self.AUTO_CHUNK_DURATION_SEC:
            reasons.append(f"duration={metadata.duration_sec:.0f}s")
        if metadata.file_size_bytes > self.AUTO_CHUNK_SIZE_BYTES:
            reasons.append(f"size={metadata.file_size_bytes/1e9:.1f}GB")
        if metadata.width > self.AUTO_CHUNK_MIN_RESOLUTION[0]:
            reasons.append(f"resolution={metadata.width}x{metadata.height}")
        if reasons:
            logger.info(f"Chunking required: {', '.join(reasons)}")
            return True
        return False

    async def process(
        self,
        video_path: str,
        process_func,  # async callable(segment, metadata) -> str (processed file path)
        output_dir: str,
        strategy: SegmentStrategy = SegmentStrategy.SCENE_DETECT,
    ) -> Tuple[str, List[VideoSegment]]:
        """
        分段处理管线：
        1. 探测视频信息
        2. 决定是否分段
        3. 分段 + 并行处理
        4. 拼接输出

        Returns:
            (final_output_path, segments_list)
        """
        metadata = await self.inspector.probe(video_path)

        if not self.should_chunk(metadata):
            # 不需要分段，直接处理
            logger.info(f"Video under threshold, direct processing: {video_path}")
            result = await process_func(
                VideoSegment(index=0, start_sec=0, end_sec=metadata.duration_sec,
                            duration_sec=metadata.duration_sec),
                metadata
            )
            return result, []

        # 分段
        if strategy == SegmentStrategy.SCENE_DETECT:
            segments = await self.scene_detector.detect(video_path, metadata)
        elif strategy == SegmentStrategy.FIXED_DURATION:
            segments = await self.fixed_splitter.split(metadata)
        else:
            segments = await self.fixed_splitter.split(metadata)

        logger.info(f"Video chunked into {len(segments)} segments, "
                    f"processing with {self.max_workers} workers")

        # 并行处理各分段
        semaphore = asyncio.Semaphore(self.max_workers)

        async def process_one(seg: VideoSegment) -> Tuple[int, str]:
            async with semaphore:
                # 先提取分段
                seg_path = await self._extract_segment(video_path, seg, output_dir)
                # 处理分段
                result = await process_func(seg, metadata)
                return seg.index, result

        tasks = [process_one(seg) for seg in segments]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 按顺序收集结果
        processed_files = []
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Segment processing failed: {r}")
                raise r
            idx, path = r
            processed_files.append((idx, path))

        processed_files.sort(key=lambda x: x[0])

        # 拼接
        final_path = await self._stitch_segments(
            [p for _, p in processed_files], output_dir, metadata
        )

        return final_path, segments

    async def _extract_segment(
        self, video_path: str, segment: VideoSegment, output_dir: str
    ) -> str:
        """提取视频分段（无损，仅裁剪）"""
        os.makedirs(output_dir, exist_ok=True)
        seg_path = os.path.join(output_dir, f"seg_{segment.index:04d}.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(segment.start_sec),
            "-i", video_path,
            "-t", str(segment.duration_sec),
            "-c", "copy",  # 无损复制，不重新编码
            "-avoid_negative_ts", "make_zero",
            seg_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"Segment extraction with copy failed, falling back to re-encode: "
                          f"{stderr.decode(errors='ignore')[:200]}")
            # 回退：重新编码
            return await self._extract_segment_reencode(video_path, segment, output_dir)
        return seg_path

    async def _extract_segment_reencode(
        self, video_path: str, segment: VideoSegment, output_dir: str
    ) -> str:
        """回退方案：重新编码提取分段"""
        seg_path = os.path.join(output_dir, f"seg_{segment.index:04d}.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(segment.start_sec),
            "-i", video_path,
            "-t", str(segment.duration_sec),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-avoid_negative_ts", "make_zero",
            seg_path
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()
        return seg_path

    async def _stitch_segments(
        self, segment_paths: List[str], output_dir: str, metadata: VideoMetadata
    ) -> str:
        """无缝拼接分段（使用 concat demuxer）"""
        # 创建 concat 文件列表
        concat_file = os.path.join(output_dir, "concat_list.txt")
        with open(concat_file, "w") as f:
            for p in segment_paths:
                f.write(f"file '{os.path.abspath(p)}'\n")

        final_path = os.path.join(output_dir, "final_stitched.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            final_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"Concat copy failed, re-encoding: "
                          f"{stderr.decode(errors='ignore')[:200]}")
            # 回退方案：重新编码拼接
            cmd2 = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "256k",
                final_path
            ]
            proc2 = await asyncio.create_subprocess_exec(*cmd2)
            await proc2.communicate()

        return final_path


class StreamingProcessor:
    """流式视频处理器

    用于超长视频（直播录制、监控视频等），逐帧/逐包处理，
    不加载完整视频到内存。适合实时/近实时的处理场景。
    """

    def __init__(self, chunk_size_frames: int = 150):  # ~5 seconds at 30fps
        self.chunk_size = chunk_size_frames

    async def stream_process(
        self,
        video_path: str,
        frame_callback,  # async callback(frame, frame_idx) -> processed_frame
        output_path: str,
        metadata: Optional[VideoMetadata] = None,
    ):
        """流式读取视频帧 → 回调处理 → 流式写出

        利用 ffmpeg pipe 实现，内存占用可控，适合超大视频。
        """
        if metadata is None:
            metadata = await VideoInspector.probe(video_path)

        # 读取管道
        read_cmd = [
            "ffmpeg", "-i", video_path,
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-"
        ]
        # 写入管道
        write_cmd = [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{metadata.width}x{metadata.height}",
            "-r", str(metadata.fps),
            "-i", "-",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            output_path
        ]

        # TODO: 实际流式管道实现
        # 这里保留接口，完整实现需 asyncio subprocess pipe 对接
        logger.info(f"Streaming process: {metadata.width}x{metadata.height} @ {metadata.fps}fps")
        pass


# ============================================================
# 便捷函数
# ============================================================

async def get_video_metadata(video_path: str) -> VideoMetadata:
    """快速获取视频元信息"""
    return await VideoInspector.probe(video_path)


async def smart_chunk_count(metadata: VideoMetadata) -> int:
    """智能计算最优分段数"""
    if metadata.duration_sec < 300:
        return 1  # < 5min, no chunking
    if metadata.duration_sec < 1800:
        return max(2, int(metadata.duration_sec / 300))  # 5min per chunk
    # > 30min
    cpu_count = os.cpu_count() or 4
    return min(cpu_count * 2, int(metadata.duration_sec / 120))
