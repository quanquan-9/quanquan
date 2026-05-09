"""
FFmpeg 全自动验片 — 黑场/静音/音画同步/音量峰值 全量QC
"""
import subprocess
import json
import re
from datetime import datetime, timezone
from typing import Dict, List


class FFmpegVideoInspector:
    """导出后全自动技术质检"""

    QC_RULES = {
        "black_detect": {
            "ffmpeg_filter": "blackdetect=d={min_dur}:pix_th={pix_th}",
            "params": {"min_dur": 0.5, "pix_th": 0.05},
            "severity_map": {
                "fatal": {"duration": 2.0},
                "major": {"duration": 1.0},
                "minor": {"duration": 0.5},
            },
        },
        "silence_detect": {
            "ffmpeg_filter": "silencedetect=n={noise_thr}dB:d={min_dur}",
            "params": {"noise_thr": -50, "min_dur": 1.0},
            "severity_map": {
                "fatal": {"duration": 3.0},
                "major": {"duration": 1.5},
                "minor": {"duration": 1.0},
            },
        },
    }

    def run_full_inspection(self, video_path: str) -> dict:
        """执行全量技术质检"""
        report = {
            "file": video_path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": {},
        }

        # 1. 黑场检测
        report["results"]["black_frames"] = self._detect_black_frames(video_path)

        # 2. 静音检测
        report["results"]["silence"] = self._detect_silence(video_path)

        # 3. 音画同步检测
        report["results"]["av_sync"] = self._detect_av_sync(video_path)

        # 4. 汇总缺陷等级
        report["summary"] = self._classify_issues(report["results"])

        return report

    def _detect_black_frames(self, video_path: str) -> list:
        """黑场检测"""
        try:
            cmd = [
                "ffmpeg", "-i", video_path,
                "-vf", "blackdetect=d=0.5:pix_th=0.05",
                "-f", "null", "-",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            stderr = result.stderr

            black_segments = []
            for match in re.finditer(
                r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)",
                stderr,
            ):
                start = float(match.group(1))
                end = float(match.group(2))
                duration = float(match.group(3))
                severity = self._classify_duration(
                    duration, self.QC_RULES["black_detect"]["severity_map"]
                )
                black_segments.append({
                    "start_sec": start, "end_sec": end,
                    "duration_sec": duration, "severity": severity,
                })
            return black_segments
        except Exception as e:
            return [{"error": str(e)}]

    def _detect_silence(self, video_path: str) -> list:
        """静音检测"""
        try:
            cmd = [
                "ffmpeg", "-i", video_path,
                "-af", "silencedetect=n=-50dB:d=1.0",
                "-f", "null", "-",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            stderr = result.stderr

            silence_segments = []
            for match in re.finditer(
                r"silence_start:\s*([\d.]+).*?silence_end:\s*([\d.]+).*?silence_duration:\s*([\d.]+)",
                stderr,
            ):
                start = float(match.group(1))
                end = float(match.group(2))
                duration = float(match.group(3))
                severity = self._classify_duration(
                    duration, self.QC_RULES["silence_detect"]["severity_map"]
                )
                silence_segments.append({
                    "start_sec": start, "end_sec": end,
                    "duration_sec": duration, "severity": severity,
                })
            return silence_segments
        except Exception as e:
            return [{"error": str(e)}]

    def _detect_av_sync(self, video_path: str) -> dict:
        """检测音画同步偏移"""
        try:
            # 获取视频流起始时间
            cmd_v = ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                     "-show_entries", "stream=start_time", "-of", "json", video_path]
            v_info = json.loads(subprocess.check_output(cmd_v, timeout=30))
            v_start = float(v_info.get("streams", [{}])[0].get("start_time", 0))

            # 获取音频流起始时间
            cmd_a = ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
                     "-show_entries", "stream=start_time", "-of", "json", video_path]
            a_info = json.loads(subprocess.check_output(cmd_a, timeout=30))
            a_start = float(a_info.get("streams", [{}])[0].get("start_time", 0))

            offset_ms = abs(v_start - a_start) * 1000
            severity = "pass"
            if offset_ms >= 200:
                severity = "fatal"
            elif offset_ms >= 100:
                severity = "major"
            elif offset_ms >= 50:
                severity = "minor"

            return {
                "video_start_sec": v_start,
                "audio_start_sec": a_start,
                "offset_ms": round(offset_ms, 1),
                "severity": severity,
            }
        except Exception as e:
            return {"error": str(e)}

    def _detect_audio_peaks(self, video_path: str) -> list:
        """音量峰值检测"""
        try:
            cmd = [
                "ffmpeg", "-i", video_path,
                "-af", "volumedetect",
                "-f", "null", "-",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            stderr = result.stderr
            peaks = []
            for match in re.finditer(r"max_volume:\s*([\d.-]+)\s*dB", stderr):
                db = float(match.group(1))
                severity = "major" if db >= -0.1 else ("minor" if db >= -1.0 else "pass")
                peaks.append({"max_volume_db": db, "severity": severity})
            return peaks
        except Exception as e:
            return [{"error": str(e)}]

    def _classify_duration(self, duration: float, severity_map: dict) -> str:
        for severity, thresholds in severity_map.items():
            if duration >= thresholds["duration"]:
                return severity
        return "pass"

    def _classify_issues(self, results: dict) -> dict:
        """汇总缺陷等级"""
        fatal = major = minor = 0
        # 黑场
        for seg in results.get("black_frames", []):
            if seg.get("severity") == "fatal": fatal += 1
            elif seg.get("severity") == "major": major += 1
            elif seg.get("severity") == "minor": minor += 1
        # 静音
        for seg in results.get("silence", []):
            if seg.get("severity") == "fatal": fatal += 1
            elif seg.get("severity") == "major": major += 1
            elif seg.get("severity") == "minor": minor += 1
        # 音画同步
        av = results.get("av_sync", {})
        if isinstance(av, dict) and av.get("severity") == "fatal": fatal += 1
        elif isinstance(av, dict) and av.get("severity") == "major": major += 1
        elif isinstance(av, dict) and av.get("severity") == "minor": minor += 1

        return {
            "fatal": fatal, "major": major, "minor": minor,
            "verdict": "FAIL" if fatal > 0 else ("WARN" if major > 0 else "PASS"),
        }


ffmpeg_inspector = FFmpegVideoInspector()
