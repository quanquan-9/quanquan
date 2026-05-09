"""
批量项目处理器 (Batch Processor)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
- 并发提交多个视频制作项目
- asyncio.Semaphore 控制最大并发数
- 批量状态查询
- 批量取消
- 与 director 和 server 无缝集成

使用示例：
    bp = BatchProcessor(director, max_concurrency=3)
    batch_id = await bp.submit_batch([{...}, {...}])
    status = await bp.get_batch_status(batch_id)
"""

import asyncio
import time
import uuid
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import OrderedDict

logger = logging.getLogger("quanquan.batch_processor")

# 每个批次的内部状态追踪上限（LRU 淘汰）
MAX_BATCH_HISTORY = 500


class BatchProjectStatus(str, Enum):
    """单个项目在批次中的状态"""
    QUEUED = "queued"         # 排队等待
    PROCESSING = "processing"  # 正在处理
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"          # 失败
    CANCELLED = "cancelled"    # 已取消


@dataclass
class BatchRecord:
    """批次记录"""
    batch_id: str
    project_ids: List[str] = field(default_factory=list)
    project_statuses: Dict[str, BatchProjectStatus] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    cancelled: bool = False
    # 每个项目的提交数据（用于重试）
    requests: List[dict] = field(default_factory=list)


class BatchProcessor:
    """批量项目处理器 — 管理多项目并发提交与生命周期

    使用 asyncio.Semaphore 控制最大并发，保证不会压垮 LLM / TTS / 渲染服务。
    每个批次下的项目按 FIFO 顺序提交给 director。
    """

    def __init__(self, director=None, max_concurrency: int = 3):
        """
        Args:
            director: DirectorAgent 实例（用于 submit_project）
            max_concurrency: 同时处理的最大项目数（默认 3）
        """
        self._director = director
        self._max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

        # 批次存储：batch_id → BatchRecord
        self._batches: Dict[str, BatchRecord] = OrderedDict()
        # 正在运行的后台任务：project_id → asyncio.Task
        self._running_tasks: Dict[str, asyncio.Task] = {}
        # 锁，保护共享状态
        self._lock = asyncio.Lock()

        logger.info(
            f"[BatchProcessor] 初始化完成，最大并发={max_concurrency}"
        )

    # ── 公共 API ──────────────────────────────────────────────

    async def submit_batch(self, requests: list) -> str:
        """提交一批项目，返回 batch_id

        Args:
            requests: 项目请求列表，每个元素是 dict，格式与 director.submit_project 兼容。
                      必须字段: text (视频描述)
                      可选字段: duration, style, tags, priority 等

        Returns:
            batch_id: 批次唯一标识符

        Example:
            batch_id = await bp.submit_batch([
                {"text": "赛博朋克夜景", "duration": 60, "style": "cyberpunk"},
                {"text": "春日花海延时", "duration": 120, "style": "nature"},
            ])
        """
        if not requests:
            raise ValueError("submit_batch: requests 列表不能为空")

        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        project_ids: List[str] = []

        # 先分配 project_id
        for req in requests:
            pid = req.get("project_id", f"proj_{uuid.uuid4().hex[:12]}")
            req["project_id"] = pid
            project_ids.append(pid)

        # 创建批次记录
        record = BatchRecord(
            batch_id=batch_id,
            project_ids=project_ids,
            requests=requests,
        )
        for pid in project_ids:
            record.project_statuses[pid] = BatchProjectStatus.QUEUED

        async with self._lock:
            self._batches[batch_id] = record
            self._evict_if_needed()

        logger.info(
            f"[BatchProcessor] 批次 {batch_id} 提交成功，"
            f"共 {len(requests)} 个项目: {project_ids}"
        )

        # 启动后台处理（不阻塞调用者）
        asyncio.create_task(self._process_batch(batch_id))

        return batch_id

    async def get_batch_status(self, batch_id: str) -> dict:
        """获取批次内所有项目的状态

        Args:
            batch_id: 批次 ID

        Returns:
            {
                "batch_id": "...",
                "total": 5,
                "queued": 1,
                "processing": 2,
                "completed": 1,
                "failed": 1,
                "cancelled": 0,
                "projects": [{"project_id": "...", "status": "..."}, ...],
                "created_at": 1715000000.0,
                "elapsed_sec": 30.5,
            }
        """
        async with self._lock:
            record = self._batches.get(batch_id)
        if record is None:
            raise KeyError(f"批次不存在: {batch_id}")

        counts = {s.value: 0 for s in BatchProjectStatus}
        project_list = []
        for pid in record.project_ids:
            st = record.project_statuses.get(pid, BatchProjectStatus.QUEUED)
            counts[st.value] += 1
            project_list.append({"project_id": pid, "status": st.value})

        elapsed = time.time() - record.created_at

        return {
            "batch_id": batch_id,
            "total": len(record.project_ids),
            **counts,
            "projects": project_list,
            "created_at": record.created_at,
            "elapsed_sec": round(elapsed, 2),
        }

    async def cancel_batch(self, batch_id: str) -> dict:
        """取消批次中所有尚未开始的项目

        Args:
            batch_id: 批次 ID

        Returns:
            {"batch_id": "...", "cancelled_count": 3, "already_running": 2}
        """
        async with self._lock:
            record = self._batches.get(batch_id)
        if record is None:
            raise KeyError(f"批次不存在: {batch_id}")

        cancelled_count = 0
        already_running = 0

        for pid in record.project_ids:
            current = record.project_statuses.get(pid, BatchProjectStatus.QUEUED)
            if current in (BatchProjectStatus.QUEUED,):
                record.project_statuses[pid] = BatchProjectStatus.CANCELLED
                cancelled_count += 1
            elif current == BatchProjectStatus.PROCESSING:
                already_running += 1

        record.cancelled = True

        logger.info(
            f"[BatchProcessor] 批次 {batch_id} 取消："
            f"已取消 {cancelled_count} 个，已在运行 {already_running} 个"
        )

        return {
            "batch_id": batch_id,
            "cancelled_count": cancelled_count,
            "already_running": already_running,
        }

    def get_active_batches(self) -> List[str]:
        """获取当前活跃（未全部完成）的批次 ID 列表"""
        active = []
        for bid, record in self._batches.items():
            if any(
                s in (BatchProjectStatus.QUEUED, BatchProjectStatus.PROCESSING)
                for s in record.project_statuses.values()
            ):
                active.append(bid)
        return active

    # ── 内部逻辑 ──────────────────────────────────────────────

    async def _process_batch(self, batch_id: str):
        """后台协程：逐项处理批次中的项目（受信号量控制）"""
        async with self._lock:
            record = self._batches.get(batch_id)
        if record is None:
            return

        # 创建每个项目的处理任务
        tasks = []
        for i, req in enumerate(record.requests):
            pid = record.project_ids[i]
            # 如果批次已被取消，跳过还在排队的项目
            if record.cancelled:
                continue
            task = asyncio.create_task(
                self._process_single(pid, req, batch_id)
            )
            tasks.append(task)

        # 等待所有项目完成
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    logger.error(
                        f"[BatchProcessor] 批次 {batch_id} 项目 {record.project_ids[i]} "
                        f"异常: {r}"
                    )

        logger.info(f"[BatchProcessor] 批次 {batch_id} 全部处理完成")

    async def _process_single(
        self, project_id: str, request: dict, batch_id: str
    ):
        """处理单个项目：获取信号量 → 提交 → 等待完成 → 释放"""
        async with self._semaphore:
            # 再次检查是否已取消
            async with self._lock:
                record = self._batches.get(batch_id)
            if record is None or record.cancelled:
                if record:
                    record.project_statuses[project_id] = BatchProjectStatus.CANCELLED
                return

            # 标记为 processing
            async with self._lock:
                if record := self._batches.get(batch_id):
                    record.project_statuses[project_id] = BatchProjectStatus.PROCESSING

            logger.info(
                f"[BatchProcessor] 开始处理 {project_id} (批次 {batch_id})"
            )

            try:
                # 提交给 director（如果没有 director，则模拟完成）
                if self._director is not None:
                    pid = await self._director.submit_project(
                        {**request, "project_id": project_id}
                    )
                    # 等待 director 完成该项目
                    # 这里通过轮询 director 的 _projects_store 判断完成
                    await self._wait_for_project_completion(pid, timeout=600)
                else:
                    # 无 director 时模拟处理（测试/独立模式）
                    await asyncio.sleep(0.5)
                    pid = project_id

                # 标记为 completed
                async with self._lock:
                    if record := self._batches.get(batch_id):
                        record.project_statuses[pid] = BatchProjectStatus.COMPLETED

                logger.info(
                    f"[BatchProcessor] {pid} 处理完成 (批次 {batch_id})"
                )

            except asyncio.CancelledError:
                async with self._lock:
                    if record := self._batches.get(batch_id):
                        record.project_statuses[project_id] = BatchProjectStatus.CANCELLED
                raise
            except Exception as e:
                async with self._lock:
                    if record := self._batches.get(batch_id):
                        record.project_statuses[project_id] = BatchProjectStatus.FAILED
                logger.error(
                    f"[BatchProcessor] {project_id} 处理失败: {e}"
                )

    async def _wait_for_project_completion(
        self, project_id: str, timeout: float = 600
    ) -> None:
        """轮询等待 director 完成项目（最多 timeout 秒）"""
        if self._director is None:
            return

        deadline = time.time() + timeout
        while time.time() < deadline:
            store = getattr(self._director, "_projects_store", {})
            proj = store.get(project_id, {})
            status = proj.get("status", proj.get("state", ""))

            if status == "completed":
                return
            if status in ("failed", "error"):
                raise RuntimeError(
                    f"项目 {project_id} 失败: {proj.get('error', '未知错误')}"
                )

            await asyncio.sleep(1.0)

        raise TimeoutError(f"项目 {project_id} 等待超时 ({timeout}s)")

    def _evict_if_needed(self):
        """LRU 淘汰：批次记录超过上限时移除最旧的已完成批次"""
        while len(self._batches) > MAX_BATCH_HISTORY:
            oldest_bid, oldest_record = next(iter(self._batches.items()))
            # 只淘汰已全部结束的批次
            all_done = all(
                s not in (BatchProjectStatus.QUEUED, BatchProjectStatus.PROCESSING)
                for s in oldest_record.project_statuses.values()
            )
            if all_done:
                del self._batches[oldest_bid]
                logger.debug(f"[BatchProcessor] LRU 淘汰批次 {oldest_bid}")
            else:
                break  # 最旧的还在跑，跳过淘汰


# ── 便捷工厂 ──────────────────────────────────────────────────

# 模块级单例（由 server 在启动时注入 director）
batch_processor: Optional[BatchProcessor] = None


def get_batch_processor(director=None, max_concurrency: int = 3) -> BatchProcessor:
    """获取或创建全局 BatchProcessor 实例"""
    global batch_processor
    if batch_processor is None:
        batch_processor = BatchProcessor(
            director=director, max_concurrency=max_concurrency
        )
    return batch_processor
