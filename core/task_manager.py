"""
quanquan 异步任务管理器 — 后台任务调度与追踪

管理视频渲染、导出等长时间运行的后台任务。
"""
import asyncio
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackgroundTask:
    """单个后台任务"""

    def __init__(self, name: str, coro_func: Callable, args: tuple = (), kwargs: dict = None):
        self.id = f"task_{uuid.uuid4().hex[:8]}"
        self.name = name
        self.status = TaskStatus.PENDING
        self.coro_func = coro_func
        self.args = args
        self.kwargs = kwargs or {}
        self.result: Any = None
        self.error: Optional[str] = None
        self.created_at = datetime.now(timezone.utc)
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.progress: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "progress": self.progress,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class TaskManager:
    """后台任务管理器 — 单例"""

    def __init__(self):
        self._tasks: Dict[str, BackgroundTask] = {}
        self._lock = asyncio.Lock()

    async def submit(self, name: str, coro_func: Callable, *args, **kwargs) -> BackgroundTask:
        """提交后台任务，立即返回任务对象。"""
        task = BackgroundTask(name, coro_func, args, kwargs)
        async with self._lock:
            self._tasks[task.id] = task
        asyncio.create_task(self._run(task))
        return task

    async def _run(self, task: BackgroundTask):
        """执行任务（内部）"""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        try:
            if asyncio.iscoroutinefunction(task.coro_func):
                task.result = await task.coro_func(*task.args, **task.kwargs)
            else:
                task.result = task.coro_func(*task.args, **task.kwargs)
            task.status = TaskStatus.COMPLETED
            task.progress = 1.0
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
        finally:
            task.completed_at = datetime.now(timezone.utc)

    async def get(self, task_id: str) -> Optional[BackgroundTask]:
        return self._tasks.get(task_id)

    async def list_all(self) -> list:
        return [t.to_dict() for t in self._tasks.values()]

    async def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.now(timezone.utc)
            return True
        return False

    async def cleanup_completed(self) -> int:
        """清理已完成/失败/取消的任务。"""
        async with self._lock:
            to_remove = [
                tid for tid, t in self._tasks.items()
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            ]
            for tid in to_remove:
                del self._tasks[tid]
            return len(to_remove)


# 全局单例
task_manager = TaskManager()
