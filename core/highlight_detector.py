"""
高光时刻提取引擎 (Highlight Detection)

功能：
- 基于音频能量检测精彩片段
- 基于视觉运动/场景切换检测
- 基于情绪曲线峰值提取
- 自动生成短视频素材
"""

import asyncio
import json
import os
import logging
import subprocess
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class HighlightSegment:
    """高光片段"""
    start_sec: float
    end_sec: float
    duration_sec: float
    score: float           # 0~1, 高光得分
    reason: str            # 检测原因
    peak_type: str         # audio / visual / emotion / combined
    confidence: float = 0.5


class AudioEnergyDetector:
    """基于音频能量的高光检测

    原理：精彩片段通常伴随音量/能量峰值（欢呼、爆炸、重鼓点等）
    """

    def __init__(self, window_sec: float = 2.0, threshold_percentile: float = 80):
        self.window_sec = window_sec
        self.threshold_percentile = threshold_percentile

    async def detect(self, video_path: str, top_k: int = 5) -> List[HighlightSegment]:
        """检测音频能量峰值"""
        # 使用 ffmpeg 提取音频 RMS 能量
        cmd = [
            "ffmpeg", "-i", video_path,
            "-af", f"astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        stderr_text = stderr.decode(errors="ignore")

        # 解析 RMS 值
        import re
        rms_values = []
        for line in stderr_text.split("\n"):
            match = re.search(r"lavfi\.astats\.Overall\.RMS_level=([-\d.]+)", line)
            if match:
                rms_values.append(float(match.group(1)))

        if not rms_values:
            return []

        # 计算阈值
        import math
        sorted_rms = sorted(rms_values)
        idx = int(len(sorted_rms) * self.threshold_percentile / 100)
        threshold = sorted_rms[min(idx, len(sorted_rms) - 1)]

        # 找峰值区间
        # 简易实现：取 top K 最高能量的窗口
        window_size = max(1, len(rms_values) // 100)  # ~1% of video = one window
        window_scores = []
        for i in range(0, len(rms_values) - window_size, window_size // 2):
            window = rms_values[i:i + window_size]
            avg_energy = sum(window) / len(window)
            if avg_energy >= threshold:
                # 估算时间（假设每秒检测约 10 次）
                start_sec = i / 10.0
                end_sec = (i + window_size) / 10.0
                score = min(1.0, (avg_energy - threshold) / max(1, abs(threshold)))
                window_scores.append((start_sec, end_sec, score))

        window_scores.sort(key=lambda x: x[2], reverse=True)
        highlights = [
            HighlightSegment(
                start_sec=s, end_sec=e, duration_sec=e - s,
                score=sc, reason="音频能量峰值",
                peak_type="audio",
            )
            for s, e, sc in window_scores[:top_k]
        ]
        return highlights


class SceneChangeDetector:
    """基于场景切换的高光检测

    原理：快节奏场景切换通常对应精彩片段
    """

    def __init__(self, scene_threshold: float = 0.4):
        self.scene_threshold = scene_threshold

    async def detect(self, video_path: str, top_k: int = 5) -> List[HighlightSegment]:
        """检测场景切换密集区域"""
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", f"select='gt(scene,{self.scene_threshold})',showinfo",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        import re
        scene_times = []
        for line in stderr.decode(errors="ignore").split("\n"):
            match = re.search(r"pts_time:([\d.]+)", line)
            if match:
                scene_times.append(float(match.group(1)))

        if len(scene_times) < 3:
            return []

        # 找切换最密集的区域
        segments = []
        window = 10.0  # 10秒窗口
        for i in range(len(scene_times)):
            start = scene_times[i]
            count = sum(1 for t in scene_times if start <= t <= start + window)
            if count >= 3:  # 至少3次切换
                score = min(1.0, count / 10)
                segments.append(HighlightSegment(
                    start_sec=start,
                    end_sec=start + window,
                    duration_sec=window,
                    score=score,
                    reason=f"快节奏切换 ({count}次/{window}s)",
                    peak_type="visual",
                ))

        segments.sort(key=lambda x: x.score, reverse=True)
        return segments[:top_k]


class EmotionPeakDetector:
    """基于情绪曲线的高光检测"""

    async def detect(self, emotion_curve: List[dict], top_k: int = 5) -> List[HighlightSegment]:
        """从情绪曲线找峰值"""
        if not emotion_curve:
            return []

        # 找情绪强度最高的区间
        intensities = [p.get("intensity", 0.5) for p in emotion_curve]
        if not intensities:
            return []

        threshold = sorted(intensities)[int(len(intensities) * 0.8)]

        highlights = []
        i = 0
        while i < len(intensities):
            if intensities[i] >= threshold:
                start = i
                while i < len(intensities) and intensities[i] >= threshold:
                    i += 1
                end = i
                avg_intensity = sum(intensities[start:end]) / (end - start)
                highlights.append(HighlightSegment(
                    start_sec=start,
                    end_sec=end,
                    duration_sec=end - start,
                    score=avg_intensity,
                    reason=f"情绪高点 (强度 {avg_intensity:.2f})",
                    peak_type="emotion",
                ))
            else:
                i += 1

        highlights.sort(key=lambda x: x.score, reverse=True)
        return highlights[:top_k]


class HighlightExtractor:
    """综合高光提取器 — 融合多种检测方法"""

    def __init__(self):
        self.audio_detector = AudioEnergyDetector()
        self.scene_detector = SceneChangeDetector()
        self.emotion_detector = EmotionPeakDetector()

    async def extract(
        self,
        video_path: str,
        emotion_curve: Optional[List[dict]] = None,
        top_k: int = 5,
        min_duration_sec: float = 3.0,
        max_duration_sec: float = 60.0,
    ) -> List[HighlightSegment]:
        """多维度融合提取高光时刻"""
        tasks = [
            self.audio_detector.detect(video_path, top_k=top_k * 2),
            self.scene_detector.detect(video_path, top_k=top_k * 2),
        ]
        if emotion_curve:
            tasks.append(self.emotion_detector.detect(emotion_curve, top_k=top_k * 2))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 合并去重
        all_segments: List[HighlightSegment] = []
        for r in results:
            if isinstance(r, list):
                all_segments.extend(r)

        # 融合评分（多检测器共识加权）
        merged = {}
        for seg in all_segments:
            key = (round(seg.start_sec, 1), round(seg.end_sec, 1))
            if key in merged:
                merged[key].score = min(1.0, merged[key].score + seg.score * 0.3)
                merged[key].peak_type = "combined"
                merged[key].confidence += 0.3
            else:
                if min_duration_sec <= seg.duration_sec <= max_duration_sec:
                    merged[key] = seg
                    merged[key].confidence = 0.5

        highlights = sorted(merged.values(), key=lambda x: x.score, reverse=True)
        return highlights[:top_k]

    async def extract_and_export(
        self,
        video_path: str,
        output_dir: str,
        top_k: int = 3,
    ) -> List[dict]:
        """提取高光并导出为独立视频片段"""
        highlights = await self.extract(video_path, top_k=top_k)

        os.makedirs(output_dir, exist_ok=True)
        exports = []

        for i, hl in enumerate(highlights):
            output_path = os.path.join(output_dir, f"highlight_{i+1}_{hl.peak_type}.mp4")
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(max(0, hl.start_sec - 0.5)),
                "-i", video_path,
                "-t", str(hl.duration_sec + 1.0),
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
                output_path,
            ]
            proc = await asyncio.create_subprocess_exec(*cmd)
            await proc.communicate()

            exports.append({
                "index": i + 1,
                "path": output_path,
                "start_sec": hl.start_sec,
                "end_sec": hl.end_sec,
                "score": round(hl.score, 2),
                "reason": hl.reason,
            })

        return exports
