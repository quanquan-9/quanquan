"""
自动化验片工具 (PostExportInspector)

功能：
- 对最终成片进行全面的质量检查
- 黑场检测、爆音检测、音画同步检测
- 与审核 Agent 共享同一套检测器类
- 导出后可独立调用
"""

import asyncio
import json
import re
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class InspectionReport:
    """验片报告"""
    file: str
    timestamp: str
    duration_sec: float = 0
    resolution: str = ""
    codec: str = ""
    bitrate_kbps: int = 0
    black_frames: List[dict] = field(default_factory=list)
    silence_segments: List[dict] = field(default_factory=list)
    audio_peaks: List[dict] = field(default_factory=list)
    av_sync_offset_ms: float = 0
    overall_verdict: str = "PASS"  # PASS / WARN / FAIL
    issues_summary: str = ""


class PostExportInspector:
    """导出后验片工具"""

    QC_THRESHOLDS = {
        "black_frame": {
            "min_dur": 0.5,
            "pix_th": 0.05,
            "severity": {
                "fatal": 2.0,
                "major": 1.0,
                "minor": 0.5,
            }
        },
        "silence": {
            "noise_threshold_dB": -50,
            "min_dur": 1.0,
            "severity": {
                "fatal": 3.0,
                "major": 1.5,
                "minor": 1.0,
            }
        },
        "audio_peak": {
            "clipping_threshold_dbfs": -0.1,
            "near_clipping_dbfs": -0.5,
        },
        "av_sync": {
            "fatal_ms": 200,
            "major_ms": 100,
            "minor_ms": 50,
        }
    }

    async def full_inspection(self, video_path: str,
                               config: Optional[dict] = None) -> InspectionReport:
        """对最终成片进行全面检查"""
        thresholds = config or self.QC_THRESHOLDS
        report = InspectionReport(
            file=video_path,
            timestamp=datetime.utcnow().isoformat(),
        )

        # 获取视频信息
        try:
            info = await self._get_video_info(video_path)
            report.duration_sec = info.get('duration', 0)
            report.resolution = f"{info.get('width', 0)}x{info.get('height', 0)}"
            report.codec = info.get('codec', 'unknown')
            report.bitrate_kbps = info.get('bitrate', 0) // 1000
        except Exception as e:
            logger.error(f"Failed to get video info: {e}")
            report.overall_verdict = "FAIL"
            report.issues_summary = f"无法读取视频信息: {e}"
            return report

        # 并行检测
        tasks = [
            self._detect_black_frames(video_path, thresholds),
            self._detect_silence(video_path, thresholds),
            self._detect_audio_peaks(video_path, thresholds),
            self._detect_av_sync(video_path),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Inspector {i} failed: {result}")

        # 汇总
        issues = []
        if not isinstance(results[0], Exception) and results[0]:
            report.black_frames = results[0]
            for bf in results[0]:
                if bf.get('severity') in ('fatal', 'major'):
                    issues.append(f"黑场 {bf.get('duration_sec', 0):.1f}s at {bf.get('start_sec', 0):.1f}s")

        if not isinstance(results[1], Exception) and results[1]:
            report.silence_segments = results[1]
            for s in results[1]:
                if s.get('severity') in ('fatal', 'major'):
                    issues.append(f"静音 {s.get('duration_sec', 0):.1f}s")

        if not isinstance(results[2], Exception) and results[2]:
            report.audio_peaks = results[2]
            if results[2]:
                issues.append(f"爆音 {len(results[2])}处")

        report.av_sync_offset_ms = results[3] if not isinstance(results[3], Exception) else 0
        if report.av_sync_offset_ms > thresholds["av_sync"]["major_ms"]:
            issues.append(f"音画不同步 {report.av_sync_offset_ms:.0f}ms")

        # 判定
        fatal_count = sum(1 for i in issues if 'fatal' in str(i).lower())
        if not issues:
            report.overall_verdict = "PASS"
            report.issues_summary = "✅ 全部通过"
        elif fatal_count > 0:
            report.overall_verdict = "FAIL"
            report.issues_summary = "; ".join(issues)
        else:
            report.overall_verdict = "WARN"
            report.issues_summary = "; ".join(issues)

        logger.info(f"Inspection complete: {report.overall_verdict} — {report.issues_summary}")
        return report

    async def _get_video_info(self, path: str) -> dict:
        """获取视频基本信息"""
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout)

        for stream in data.get('streams', []):
            if stream['codec_type'] == 'video':
                fmt = data.get('format', {})
                return {
                    'width': stream.get('width', 0),
                    'height': stream.get('height', 0),
                    'codec': stream.get('codec_name', ''),
                    'duration': float(fmt.get('duration', 0)),
                    'bitrate': int(fmt.get('bit_rate', 0)),
                }
        return {}

    async def _detect_black_frames(self, path: str, thresholds: dict) -> List[dict]:
        """黑场检测"""
        cfg = thresholds["black_frame"]
        cmd = [
            "ffmpeg", "-i", path,
            "-vf", f"blackdetect=d={cfg['min_dur']}:pix_th={cfg['pix_th']}",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        stderr_text = stderr.decode(errors='ignore')

        black_segments = []
        for match in re.finditer(
            r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)",
            stderr_text
        ):
            start = float(match.group(1))
            end = float(match.group(2))
            dur = float(match.group(3))

            severity = "pass"
            for sev, threshold in cfg["severity"].items():
                if dur >= threshold:
                    severity = sev
                    break

            black_segments.append({
                "start_sec": start,
                "end_sec": end,
                "duration_sec": dur,
                "severity": severity,
            })

        return black_segments

    async def _detect_silence(self, path: str, thresholds: dict) -> List[dict]:
        """静音检测"""
        cfg = thresholds["silence"]
        cmd = [
            "ffmpeg", "-i", path,
            "-af", f"silencedetect=n={cfg['noise_threshold_dB']}dB:d={cfg['min_dur']}",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        stderr_text = stderr.decode(errors='ignore')

        segments = []
        pattern = r"silence_start: ([\d.]+)\s+silence_end: ([\d.]+)\s+silence_duration: ([\d.]+)"
        for match in re.finditer(pattern, stderr_text):
            start = float(match.group(1))
            end = float(match.group(2))
            dur = float(match.group(3))

            severity = "pass"
            for sev, threshold in cfg["severity"].items():
                if dur >= threshold:
                    severity = sev
                    break

            segments.append({
                "start_sec": start,
                "end_sec": end,
                "duration_sec": dur,
                "severity": severity,
            })

        return segments

    async def _detect_audio_peaks(self, path: str, thresholds: dict) -> List[dict]:
        """爆音检测"""
        cfg = thresholds["audio_peak"]
        cmd = [
            "ffmpeg", "-i", path,
            "-af", "volumedetect",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        stderr_text = stderr.decode(errors='ignore')

        max_volume = 0
        match = re.search(r"max_volume: ([-.\d]+) dB", stderr_text)
        if match:
            max_volume = float(match.group(1))

        peaks = []
        if max_volume >= cfg["clipping_threshold_dbfs"]:
            peaks.append({
                "type": "clipping",
                "max_volume_dB": max_volume,
                "severity": "fatal",
                "suggestion": "降低主音量或应用限幅器",
            })
        elif max_volume >= cfg["near_clipping_dbfs"]:
            peaks.append({
                "type": "near_clipping",
                "max_volume_dB": max_volume,
                "severity": "minor",
            })

        return peaks

    async def _detect_av_sync(self, path: str) -> float:
        """音画同步检测 → 返回偏移量(ms)"""
        try:
            # 获取视频流起始时间
            cmd_v = ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                     "-show_entries", "stream=start_time", "-of", "json", path]
            proc = await asyncio.create_subprocess_exec(
                *cmd_v, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            v_data = json.loads(stdout)
            v_start = float(v_data['streams'][0].get('start_time', 0))

            # 获取音频流
            cmd_a = ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
                     "-show_entries", "stream=start_time", "-of", "json", path]
            proc = await asyncio.create_subprocess_exec(
                *cmd_a, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            a_data = json.loads(stdout)
            a_start = float(a_data['streams'][0].get('start_time', 0))

            return abs(v_start - a_start) * 1000
        except Exception:
            return 0
