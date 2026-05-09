"""
测试容器 + 任务管理器
"""
import os, sys, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestContainer:
    """core.container 测试"""

    def test_container_singleton(self):
        from core.container import Container
        c1 = Container()
        c2 = Container()
        assert isinstance(c1, Container)
        assert isinstance(c2, Container)

    def test_project_repo_creation(self):
        from core.container import Container
        from unittest.mock import MagicMock
        c = Container()
        mock_session = MagicMock()
        repo = c.project_repo(mock_session)
        assert repo is not None

    def test_artifact_repo_creation(self):
        from core.container import Container
        from unittest.mock import MagicMock
        c = Container()
        mock_session = MagicMock()
        repo = c.artifact_repo(mock_session)
        assert repo is not None


class TestTaskManager:
    """core.task_manager 测试"""

    async def _dummy_task(self, value=42):
        await asyncio.sleep(0.01)
        return value

    async def _failing_task(self):
        await asyncio.sleep(0.01)
        raise ValueError("模拟失败")

    @pytest.mark.asyncio
    async def test_submit_and_complete(self):
        from core.task_manager import task_manager, TaskStatus
        task = await task_manager.submit("test_task", self._dummy_task, 100)
        await asyncio.sleep(0.3)
        assert task.status == TaskStatus.COMPLETED
        assert task.result == 100
        assert task.progress == 1.0

    @pytest.mark.asyncio
    async def test_submit_and_fail(self):
        from core.task_manager import task_manager, TaskStatus
        task = await task_manager.submit("fail_task", self._failing_task)
        await asyncio.sleep(0.3)
        assert task.status == TaskStatus.FAILED
        assert "模拟失败" in task.error

    @pytest.mark.asyncio
    async def test_list_all(self):
        from core.task_manager import task_manager
        await task_manager.submit("t1", self._dummy_task, 1)
        await task_manager.submit("t2", self._dummy_task, 2)
        await asyncio.sleep(0.3)
        tasks = await task_manager.list_all()
        assert len(tasks) >= 2

    @pytest.mark.asyncio
    async def test_cancel(self):
        from core.task_manager import task_manager, TaskStatus
        task = await task_manager.submit("cancel_me", self._dummy_task, 99)
        result = await task_manager.cancel(task.id)
        assert result is True
        assert task.status == TaskStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_to_dict(self):
        from core.task_manager import task_manager, TaskStatus
        task = await task_manager.submit("dict_test", self._dummy_task, 7)
        await asyncio.sleep(0.3)
        d = task.to_dict()
        assert d["status"] == "completed"
        assert d["name"] == "dict_test"

    @pytest.mark.asyncio
    async def test_cleanup(self):
        from core.task_manager import task_manager
        await task_manager.submit("clean_me", self._dummy_task, 1)
        await asyncio.sleep(0.3)
        count = await task_manager.cleanup_completed()
        assert count >= 1
