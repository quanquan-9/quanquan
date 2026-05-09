"""
quanquan 依赖注入容器 — 集中管理所有服务的生命周期

用法:
    from core.container import container
    repo = container.project_repo()
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import async_session
from core.repository import ProjectRepository, ArtifactRepository


class Container:
    """轻量级 IoC 容器，管理所有服务实例及其依赖关系。"""

    def __init__(self):
        self._session: Optional[AsyncSession] = None

    async def get_session(self) -> AsyncSession:
        """获取数据库会话（自动创建，调用方负责关闭）。"""
        return async_session()

    def project_repo(self, session: AsyncSession) -> ProjectRepository:
        """创建 ProjectRepository 实例。"""
        return ProjectRepository(session)

    def artifact_repo(self, session: AsyncSession) -> ArtifactRepository:
        """创建 ArtifactRepository 实例。"""
        return ArtifactRepository(session)


# 全局容器单例
container = Container()
