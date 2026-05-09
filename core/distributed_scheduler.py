"""
分布式任务调度器 (Distributed Task Scheduler)

功能：
- 多 Worker 负载均衡
- 任务优先级队列
- 失败重试（指数退避）
- GPU 资源感知调度
- 任务依赖编排
"""

import asyncio
import heapq
import time
import uuid
import logging
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 5
    HIGH = 8
    URGENT = 10


class TaskStatus(Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


@dataclass(order=True)
class Task:
    """任务定义"""
    priority: int
    task_id: str = field(compare=False)
    name: str = ""
    payload: Dict[str, Any] = field(default_factory=dict, compare=False)
    status: TaskStatus = field(default=TaskStatus.PENDING, compare=False)
    created_at: float = field(default_factory=time.time, compare=False)
    started_at: Optional[float] = field(default=None, compare=False)
    max_retries: int = field(default=3, compare=False)
    retry_count: int = field(default=0, compare=False)
    retry_delay_sec: float = field(default=5.0, compare=False)
    timeout_sec: float = field(default=600, compare=False)
    requires_gpu: bool = field(default=False, compare=False)
    depends_on: List[str] = field(default_factory=list, compare=False)
    result: Any = field(default=None, compare=False)
    error: Optional[str] = field(default=None, compare=False)
    tags: List[str] = field(default_factory=list, compare=False)
    worker_id: Optional[str] = field(default=None, compare=False)


@dataclass
class WorkerInfo:
    """Worker 信息"""
    worker_id: str
    hostname: str
    status: str = "idle"          # idle / busy / offline
    gpu_available: bool = False
    gpu_count: int = 0
    gpu_utilization: float = 0.0
    cpu_count: int = 1
    memory_mb: int = 0
    current_task: Optional[str] = None
    total_completed: int = 0
    total_failed: int = 0
    last_heartbeat: float = field(default_factory=time.time)


class DistributedScheduler:
    """分布式任务调度器"""

    def __init__(self, max_concurrent: int = 4):
        self.max_concurrent = max_concurrent
        self._tasks: Dict[str, Task] = {}
        self._queue: List[Task] = []        # 优先队列
        self._workers: Dict[str, WorkerInfo] = {}
        self._running: Dict[str, Task] = {}  # task_id → Task
        self._handlers: Dict[str, Callable] = {}  # task_type → handler
        self._lock = asyncio.Lock()
        self._stats = defaultdict(int)

    # ---- Worker 管理 ----

    def register_worker(self, worker: WorkerInfo):
        self._workers[worker.worker_id] = worker
        logger.info(f"Worker registered: {worker.worker_id} ({worker.hostname})")

    def unregister_worker(self, worker_id: str):
        self._workers.pop(worker_id, None)
        logger.info(f"Worker unregistered: {worker_id}")

    def heartbeat(self, worker_id: str):
        """Worker 心跳"""
        w = self._workers.get(worker_id)
        if w:
            w.last_heartbeat = time.time()

    def get_available_workers(self) -> List[WorkerInfo]:
        """获取可用 Worker"""
        now = time.time()
        return [
            w for w in self._workers.values()
            if w.status == "idle" and (now - w.last_heartbeat) < 30
        ]

    # ---- 任务管理 ----

    async def submit(
        self,
        name: str,
        payload: dict,
        priority: TaskPriority = TaskPriority.NORMAL,
        requires_gpu: bool = False,
        depends_on: List[str] = None,
        max_retries: int = 3,
        timeout_sec: float = 600,
        tags: List[str] = None,
    ) -> str:
        """提交任务"""
        task = Task(
            priority=priority.value,
            task_id=f"task_{uuid.uuid4().hex[:12]}",
            name=name,
            payload=payload,
            requires_gpu=requires_gpu,
            depends_on=depends_on or [],
            max_retries=max_retries,
            timeout_sec=timeout_sec,
            tags=tags or [],
        )

        async with self._lock:
            self._tasks[task.task_id] = task

            # 检查依赖
            if task.depends_on:
                all_done = all(
                    self._tasks.get(d) and self._tasks[d].status == TaskStatus.COMPLETED
                    for d in task.depends_on
                )
                if not all_done:
                    task.status = TaskStatus.PENDING
                    return task.task_id

            heapq.heappush(self._queue, task)
            task.status = TaskStatus.QUEUED

        self._stats["submitted"] += 1
        logger.info(f"Task submitted: {task.task_id} ({name}) priority={priority.name}")
        return task.task_id

    async def get_next_task(self, worker_id: str) -> Optional[Task]:
        """获取下一个待执行任务"""
        async with self._lock:
            worker = self._workers.get(worker_id)

            while self._queue:
                task = heapq.heappop(self._queue)

                # 检查依赖
                deps_met = all(
                    self._tasks.get(d) and self._tasks[d].status == TaskStatus.COMPLETED
                    for d in task.depends_on
                )
                if not deps_met:
                    heapq.heappush(self._queue, task)
                    continue

                # GPU 任务需要 GPU Worker
                if task.requires_gpu and (not worker or not worker.gpu_available):
                    heapq.heappush(self._queue, task)
                    continue

                # 分配
                task.status = TaskStatus.RUNNING
                task.started_at = time.time()
                task.worker_id = worker_id
                self._running[task.task_id] = task
                if worker:
                    worker.status = "busy"
                    worker.current_task = task.task_id

                logger.info(f"Task dispatched: {task.task_id} → {worker_id}")
                return task

        return None

    async def complete_task(self, task_id: str, result: Any = None):
        """标记任务完成"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = TaskStatus.COMPLETED
                task.result = result
                self._running.pop(task_id, None)
                self._stats["completed"] += 1

                # 释放 Worker
                if task.worker_id:
                    worker = self._workers.get(task.worker_id)
                    if worker:
                        worker.status = "idle"
                        worker.current_task = None
                        worker.total_completed += 1

                # 解锁依赖任务
                await self._unblock_dependents(task_id)

                logger.info(f"Task completed: {task_id} ({task.name})")

    async def fail_task(self, task_id: str, error: str):
        """标记任务失败"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.error = error
                self._stats["failed"] += 1

                # 释放 Worker
                if task.worker_id:
                    worker = self._workers.get(task.worker_id)
                    if worker:
                        worker.status = "idle"
                        worker.current_task = None
                        worker.total_failed += 1

                # 重试
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    task.status = TaskStatus.RETRYING
                    delay = task.retry_delay_sec * (2 ** (task.retry_count - 1))  # 指数退避
                    logger.info(f"Task retrying: {task_id} (attempt {task.retry_count}/{task.max_retries}, delay={delay}s)")
                    asyncio.create_task(self._retry_after(task, delay))
                else:
                    task.status = TaskStatus.FAILED
                    self._running.pop(task_id, None)
                    logger.error(f"Task failed permanently: {task_id} - {error}")

    async def _retry_after(self, task: Task, delay: float):
        """延迟重试"""
        await asyncio.sleep(delay)
        async with self._lock:
            task.status = TaskStatus.QUEUED
            heapq.heappush(self._queue, task)

    async def _unblock_dependents(self, completed_task_id: str):
        """解锁依赖已完成任务的后续任务"""
        for task in self._tasks.values():
            if (task.status == TaskStatus.PENDING and
                completed_task_id in task.depends_on):
                deps_met = all(
                    self._tasks.get(d) and self._tasks[d].status == TaskStatus.COMPLETED
                    for d in task.depends_on
                )
                if deps_met:
                    task.status = TaskStatus.QUEUED
                    heapq.heappush(self._queue, task)

    def cancel_task(self, task_id: str):
        """取消任务"""
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.QUEUED):
            task.status = TaskStatus.CANCELLED
            logger.info(f"Task cancelled: {task_id}")

    # ---- 查询 ----

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def get_queue_depth(self) -> int:
        return len(self._queue)

    def get_active_count(self) -> int:
        return len(self._running)

    def get_stats(self) -> dict:
        return {
            "submitted": self._stats["submitted"],
            "completed": self._stats["completed"],
            "failed": self._stats["failed"],
            "queue_depth": self.get_queue_depth(),
            "active": self.get_active_count(),
            "workers": len(self._workers),
            "available_workers": len(self.get_available_workers()),
        }

    def list_tasks(self, status: Optional[TaskStatus] = None) -> List[Task]:
        if status:
            return [t for t in self._tasks.values() if t.status == status]
        return list(self._tasks.values())


# 全局调度器
scheduler = DistributedScheduler(max_concurrent=4)
