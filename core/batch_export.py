"""
批量导出模块 — 多格式并行导出 (MP4/GIF/WebM/ProRes) + 进度追踪
=================================================================
基于 ffmpeg 的项目批量导出，支持:
  - 单项目多格式导出
  - 批量项目并行导出 (asyncio 并发)
  - 全部已完成项目一键导出
  - 实时进度回调（集成 WebSocket 推送）
  - 导出任务状态持久化

用法:
  exporter = BatchExporter(output_dir="/data/quanquan/exports")
  result = await exporter.export_project("quan_20240101_xxx", "mp4")
  results = await exporter.export_batch(["pid1", "pid2", "pid3"], "gif")
"""
import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any

logger = logging.getLogger("quanquan.batch_export")


class ExportFormat(str, Enum):
    """支持的导出格式"""
    MP4 = "mp4"
    GIF = "gif"
    WEBM = "webm"
    PRORES = "prores"
    MOV = "mov"
    AVI = "avi"
    MKV = "mkv"


class ExportStatus(str, Enum):
    """导出任务状态"""
    PENDING = "pending"       # 等待中
    RUNNING = "running"       # 导出中
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"   # 已取消


# ══════════════════════════════════════════════════════════════════════════════
# FFmpeg 导出预设配置
# ══════════════════════════════════════════════════════════════════════════════

EXPORT_PRESETS: Dict[str, dict] = {
    "mp4": {
        "ext": ".mp4",
        "vf_flags": "",
        "codec_video": "libx264",
        "codec_audio": "aac",
        "pix_fmt": "yuv420p",
        "extra": "-preset medium -crf 20 -movflags +faststart",
    },
    "gif": {
        "ext": ".gif",
        "vf_flags": "fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5",
        "codec_video": "",
        "codec_audio": "",
        "pix_fmt": "",
        "extra": "-loop 0",
    },
    "webm": {
        "ext": ".webm",
        "vf_flags": "",
        "codec_video": "libvpx-vp9",
        "codec_audio": "libopus",
        "pix_fmt": "yuv420p",
        "extra": "-crf 30 -b:v 0 -deadline good -cpu-used 2",
    },
    "prores": {
        "ext": ".mov",
        "vf_flags": "",
        "codec_video": "prores_ks",
        "codec_audio": "pcm_s16le",
        "pix_fmt": "yuv422p10le",
        "extra": "-profile:v 3",  # ProRes 422 HQ
    },
    "mov": {
        "ext": ".mov",
        "vf_flags": "",
        "codec_video": "libx264",
        "codec_audio": "aac",
        "pix_fmt": "yuv420p",
        "extra": "-preset medium -crf 18",
    },
    "avi": {
        "ext": ".avi",
        "vf_flags": "",
        "codec_video": "libxvid",
        "codec_audio": "mp3",
        "pix_fmt": "yuv420p",
        "extra": "-qscale:v 3",
    },
    "mkv": {
        "ext": ".mkv",
        "vf_flags": "",
        "codec_video": "libx264",
        "codec_audio": "flac",
        "pix_fmt": "yuv420p",
        "extra": "-preset medium -crf 20",
    },
}


@dataclass
class ExportTask:
    """导出任务记录"""
    task_id: str            # 任务唯一ID
    project_id: str         # 项目ID
    format: str             # 导出格式
    input_path: str         # 源视频路径
    output_path: str        # 输出路径
    status: ExportStatus = ExportStatus.PENDING
    progress: float = 0.0   # 0.0 ~ 1.0
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_sec: float = 0.0  # 源视频时长(秒)
    error_message: str = ""
    file_size_bytes: int = 0
    process: Any = None     # asyncio subprocess


class BatchExporter:
    """
    批量导出器
    
    支持的格式: mp4, gif, webm, prores, mov, avi, mkv
    
    用法:
      exporter = BatchExporter()
      result = await exporter.export_project("quan_xxx", "mp4")
      results = await exporter.export_batch(["pid1", "pid2"], "gif")
    """

    # 默认导出格式（常用4种）
    export_formats = {"mp4", "gif", "webm", "prores"}

    def __init__(self, output_dir: str = "/data/quanquan/exports",
                 source_dir: str = "/data/quanquan/output",
                 projects_store: dict = None,
                 ws_broadcaster=None,
                 max_concurrency: int = 4):
        """
        Args:
            output_dir: 导出文件输出目录
            source_dir: 源视频文件目录
            projects_store: 项目存储字典（用于 export_all_completed）
            ws_broadcaster: WSBroadcaster 实例（用于进度推送）
            max_concurrency: 最大并发导出数
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.source_dir = Path(source_dir)
        self._projects_store = projects_store or {}
        self._ws_broadcaster = ws_broadcaster
        self._max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._tasks: Dict[str, ExportTask] = {}  # task_id → ExportTask
        self._ffmpeg_path = self._find_ffmpeg()

    @staticmethod
    def _find_ffmpeg() -> str:
        """查找 ffmpeg 可执行文件路径"""
        for p in ["ffmpeg", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
            if shutil.which(p):
                return p
        return "ffmpeg"

    # ── 核心导出方法 ──

    async def export_project(self, project_id: str, format: str,
                              progress_callback: Callable = None) -> ExportTask:
        """
        导出单个项目到指定格式
        
        Args:
            project_id: 项目ID
            format: 目标格式 (mp4/gif/webm/prores/mov/avi/mkv)
            progress_callback: 进度回调 async def cb(task_id, progress, status)
        
        Returns:
            ExportTask 导出结果
        """
        # 校验格式
        fmt = format.lower()
        if fmt not in EXPORT_PRESETS:
            raise ValueError(f"不支持的导出格式: {format}。支持: {list(EXPORT_PRESETS.keys())}")

        # 创建任务
        task_id = f"export_{project_id}_{fmt}_{int(time.time())}"
        input_path = self._find_source_video(project_id)
        if input_path is None:
            raise FileNotFoundError(f"找不到项目 {project_id} 的源视频文件")

        preset = EXPORT_PRESETS[fmt]
        output_path = self.output_dir / f"{project_id}{preset['ext']}"

        task = ExportTask(
            task_id=task_id,
            project_id=project_id,
            format=fmt,
            input_path=input_path,
            output_path=str(output_path),
            started_at=time.time(),
            status=ExportStatus.RUNNING,
        )

        # 获取源视频时长(用于进度估算)
        task.duration_sec = await self._probe_duration(input_path)

        self._tasks[task_id] = task
        logger.info(f"[BatchExporter] 开始导出: {project_id} → {fmt} (任务: {task_id})")

        try:
            # 构建 ffmpeg 命令
            cmd = self._build_ffmpeg_cmd(input_path, str(output_path), fmt, preset)

            # 执行 ffmpeg
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            task.process = process

            # 异步读取 stderr 以追踪进度
            asyncio.create_task(self._track_progress(task, process, progress_callback))

            # 等待导出完成
            _, stderr = await process.communicate()

            if process.returncode == 0:
                task.status = ExportStatus.COMPLETED
                task.progress = 1.0
                task.completed_at = time.time()
                if os.path.exists(task.output_path):
                    task.file_size_bytes = os.path.getsize(task.output_path)
                logger.info(f"[BatchExporter] ✅ 导出完成: {project_id} → {fmt} "
                           f"({task.file_size_bytes / 1e6:.1f}MB)")
            else:
                err_text = stderr.decode("utf-8", errors="replace")[-500:]
                task.status = ExportStatus.FAILED
                task.error_message = err_text
                task.completed_at = time.time()
                logger.error(f"[BatchExporter] ❌ 导出失败: {project_id} → {fmt}: {err_text[:200]}")

        except Exception as e:
            task.status = ExportStatus.FAILED
            task.error_message = str(e)
            task.completed_at = time.time()
            logger.error(f"[BatchExporter] ❌ 导出异常: {project_id} → {fmt}: {e}")

        # WebSocket 推送
        if self._ws_broadcaster:
            await self._ws_broadcaster.on_export_progress(
                project_id, fmt,
                percent=100.0 if task.status == ExportStatus.COMPLETED else 0.0,
                stage=task.status.value,
            )

        return task

    async def export_batch(self, project_ids: List[str], format: str,
                            progress_callback: Callable = None) -> List[ExportTask]:
        """
        批量并行导出多个项目到同一格式
        
        Args:
            project_ids: 项目ID列表
            format: 目标格式
            progress_callback: 进度回调
        
        Returns:
            ExportTask 列表
        """
        logger.info(f"[BatchExporter] 批量导出: {len(project_ids)} 个项目 → {format}")

        async def _export_with_semaphore(pid: str):
            async with self._semaphore:
                return await self.export_project(pid, format, progress_callback)

        tasks = [asyncio.create_task(_export_with_semaphore(pid)) for pid in project_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_results = []
        for pid, result in zip(project_ids, results):
            if isinstance(result, Exception):
                logger.error(f"[BatchExporter] 批量导出中 {pid} 失败: {result}")
                # 创建一个失败的 ExportTask
                fake_task = ExportTask(
                    task_id=f"export_{pid}_failed",
                    project_id=pid,
                    format=format,
                    input_path="",
                    output_path="",
                    status=ExportStatus.FAILED,
                    error_message=str(result),
                )
                final_results.append(fake_task)
            else:
                final_results.append(result)

        succeeded = sum(1 for r in final_results if r.status == ExportStatus.COMPLETED)
        logger.info(f"[BatchExporter] 批量导出完成: {succeeded}/{len(project_ids)} 成功 → {format}")
        return final_results

    async def export_all_completed(self, format: str,
                                    progress_callback: Callable = None) -> List[ExportTask]:
        """
        一键导出所有已完成的项目
        
        Args:
            format: 目标格式
            progress_callback: 进度回调
        
        Returns:
            ExportTask 列表
        """
        completed_ids = [
            pid for pid, p in self._projects_store.items()
            if p.get("status") == "completed"
        ]
        logger.info(f"[BatchExporter] 导出全部已完成项目: {len(completed_ids)} 个 → {format}")
        return await self.export_batch(completed_ids, format, progress_callback)

    async def export_project_multi_format(self, project_id: str,
                                           formats: List[str] = None) -> Dict[str, ExportTask]:
        """
        将单个项目同时导出为多种格式
        
        Args:
            project_id: 项目ID
            formats: 格式列表，默认全部4种基础格式
        
        Returns:
            {format: ExportTask} 字典
        """
        if formats is None:
            formats = list(self.export_formats)

        logger.info(f"[BatchExporter] 多格式导出: {project_id} → {formats}")

        async def _export(fmt: str):
            return fmt, await self.export_project(project_id, fmt)

        tasks = [asyncio.create_task(_export(fmt)) for fmt in formats]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for i, result in enumerate(results):
            fmt = formats[i]
            if isinstance(result, Exception):
                logger.error(f"[BatchExporter] 多格式导出 {fmt} 失败: {result}")
                fake_task = ExportTask(
                    task_id=f"export_{project_id}_{fmt}_failed",
                    project_id=project_id,
                    format=fmt,
                    input_path="",
                    output_path="",
                    status=ExportStatus.FAILED,
                    error_message=str(result),
                )
                output[fmt] = fake_task
            else:
                output[result[0]] = result[1]

        return output

    # ── 任务管理 ──

    def get_task(self, task_id: str) -> Optional[dict]:
        """查询导出任务状态"""
        task = self._tasks.get(task_id)
        if not task:
            return None
        return self._task_to_dict(task)

    def get_project_tasks(self, project_id: str) -> List[dict]:
        """获取某项目的所有导出任务"""
        return [
            self._task_to_dict(t)
            for t in self._tasks.values()
            if t.project_id == project_id
        ]

    def list_tasks(self, status: str = "") -> List[dict]:
        """列出所有导出任务（可按状态筛选）"""
        tasks = self._tasks.values()
        if status:
            tasks = [t for t in tasks if t.status.value == status]
        return [self._task_to_dict(t) for t in tasks]

    def cancel_task(self, task_id: str) -> bool:
        """取消导出任务"""
        task = self._tasks.get(task_id)
        if not task or task.status != ExportStatus.RUNNING:
            return False
        if task.process:
            try:
                task.process.kill()
            except Exception:
                pass
        task.status = ExportStatus.CANCELLED
        task.completed_at = time.time()
        logger.info(f"[BatchExporter] 已取消任务: {task_id}")
        return True

    def cancel_project_exports(self, project_id: str) -> int:
        """取消某项目的所有导出任务"""
        cancelled = 0
        for task in list(self._tasks.values()):
            if task.project_id == project_id and task.status == ExportStatus.RUNNING:
                if self.cancel_task(task.task_id):
                    cancelled += 1
        return cancelled

    # ── 统计 ──

    def get_stats(self) -> dict:
        """获取导出器统计信息"""
        tasks = list(self._tasks.values())
        return {
            "total_tasks": len(tasks),
            "running": sum(1 for t in tasks if t.status == ExportStatus.RUNNING),
            "completed": sum(1 for t in tasks if t.status == ExportStatus.COMPLETED),
            "failed": sum(1 for t in tasks if t.status == ExportStatus.FAILED),
            "pending": sum(1 for t in tasks if t.status == ExportStatus.PENDING),
            "cancelled": sum(1 for t in tasks if t.status == ExportStatus.CANCELLED),
            "total_size_bytes": sum(t.file_size_bytes for t in tasks if t.status == ExportStatus.COMPLETED),
            "max_concurrency": self._max_concurrency,
        }

    def get_supported_formats(self) -> List[dict]:
        """获取所有支持的导出格式及说明"""
        return [
            {"format": "mp4", "description": "H.264 编码, 通用兼容, 文件小", "ext": ".mp4"},
            {"format": "gif", "description": "动图, 无声, 适合社交媒体", "ext": ".gif"},
            {"format": "webm", "description": "VP9 编码, 网页最佳, 透明支持", "ext": ".webm"},
            {"format": "prores", "description": "Apple ProRes 422 HQ, 专业后期", "ext": ".mov"},
            {"format": "mov", "description": "QuickTime 容器, H.264 无损", "ext": ".mov"},
            {"format": "avi", "description": "Xvid 编码, 传统兼容", "ext": ".avi"},
            {"format": "mkv", "description": "H.264 + FLAC 无损音频", "ext": ".mkv"},
        ]

    # ── 内部方法 ──

    def _find_source_video(self, project_id: str) -> Optional[str]:
        """查找项目的源视频文件"""
        # 1. 直接查找 output 目录
        for ext in [".mp4", ".mov", ".webm", ".mkv", ".avi"]:
            candidate = self.source_dir / f"{project_id}{ext}"
            if candidate.exists():
                return str(candidate)

        # 2. 模糊匹配（处理前缀变体）
        if self.source_dir.exists():
            for f in self.source_dir.iterdir():
                if f.is_file() and project_id.replace("quan_", "")[:8] in f.name:
                    return str(f)

        # 3. 查找 artifacts 目录
        artifacts_dir = Path("/data/quanquan/artifacts")
        if artifacts_dir.exists():
            for d in artifacts_dir.iterdir():
                if d.is_dir() and project_id.replace("quan_", "")[:8] in d.name:
                    for f in d.glob("**/*.mp4"):
                        return str(f)

        return None

    async def _probe_duration(self, video_path: str) -> float:
        """用 ffprobe 获取视频时长"""
        try:
            cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_path,
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return float(stdout.decode().strip())
        except Exception:
            return 0.0

    def _build_ffmpeg_cmd(self, input_path: str, output_path: str,
                          fmt: str, preset: dict) -> List[str]:
        """构建 ffmpeg 命令行"""
        cmd = [self._ffmpeg_path, "-y", "-i", input_path]

        # 视频滤镜
        if preset.get("vf_flags"):
            cmd += ["-vf", preset["vf_flags"]]

        # 视频编码
        if preset.get("codec_video"):
            cmd += ["-c:v", preset["codec_video"]]

        # 音频编码
        if preset.get("codec_audio"):
            cmd += ["-c:a", preset["codec_audio"]]

        # 像素格式
        if preset.get("pix_fmt"):
            cmd += ["-pix_fmt", preset["pix_fmt"]]

        # 额外参数
        if preset.get("extra"):
            cmd += preset["extra"].split()

        # GIF 特殊处理
        if fmt == "gif":
            cmd += ["-f", "gif"]

        cmd.append(output_path)
        return cmd

    async def _track_progress(self, task: ExportTask, process, callback: Callable = None):
        """
        追踪 ffmpeg 导出进度（通过解析 stderr 的 time= 行）
        
        FFmpeg stderr 格式: frame=  123 fps= 30 time=00:00:05.00 ...
        """
        if process.stderr is None:
            return

        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    break

                text = line.decode("utf-8", errors="replace")
                if "time=" in text and task.duration_sec > 0:
                    # 解析 time=HH:MM:SS.ms
                    try:
                        time_str = text.split("time=")[1].split()[0]
                        parts = time_str.split(":")
                        if len(parts) == 3:
                            elapsed = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                            task.progress = min(elapsed / task.duration_sec, 0.99)

                            # 进度回调
                            if callback:
                                await callback(task.task_id, task.progress * 100, "running")

                            # WebSocket 推送（每完成10%推一次，避免过于频繁）
                            if self._ws_broadcaster and int(task.progress * 100) % 10 == 0:
                                await self._ws_broadcaster.on_export_progress(
                                    task.project_id,
                                    task.format,
                                    percent=round(task.progress * 100, 1),
                                    stage="exporting",
                                )
                    except (ValueError, IndexError):
                        pass
        except Exception as e:
            logger.debug(f"[BatchExporter] 进度追踪异常: {e}")

    @staticmethod
    def _task_to_dict(task: ExportTask) -> dict:
        """ExportTask 转字典"""
        return {
            "task_id": task.task_id,
            "project_id": task.project_id,
            "format": task.format,
            "input_path": task.input_path,
            "output_path": task.output_path,
            "status": task.status.value,
            "progress": round(task.progress, 3),
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "duration_sec": task.duration_sec,
            "error_message": task.error_message[:200] if task.error_message else "",
            "file_size_mb": round(task.file_size_bytes / 1e6, 2),
        }


# ── 全局单例 ──
batch_exporter: Optional[BatchExporter] = None
