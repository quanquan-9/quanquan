"""
quanquan Repository 层 — 数据访问抽象

封装所有数据库 CRUD 操作，通过依赖注入提供给 Director、API 等上层使用。
遵循 Repository 模式：上层不直接操作 ORM，通过 Repository 接口访问数据。
"""
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import Artifact, Project, ProjectStatus


class ProjectRepository:
    """项目数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── 创建 ──
    async def create(self, project: Project) -> Project:
        """创建新项目并提交到数据库。"""
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    # ── 读取 ──
    async def get(self, project_id: str) -> Optional[Project]:
        """根据 ID 获取项目（含关联 artifacts）。"""
        result = await self.session.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.artifacts))
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        status: Optional[ProjectStatus] = None,
    ) -> List[Project]:
        """分页查询用户的项目列表，可选按状态过滤。"""
        stmt = (
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        if status is not None:
            stmt = stmt.where(Project.status == status)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[ProjectStatus] = None,
    ) -> List[Project]:
        """分页查询所有项目（管理用）。"""
        stmt = select(Project).order_by(Project.created_at.desc())
        if status is not None:
            stmt = stmt.where(Project.status == status)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── 更新 ──
    async def update_status(
        self,
        project_id: str,
        status: ProjectStatus,
        progress: Optional[float] = None,
    ) -> Optional[Project]:
        """更新项目状态和进度（原子操作）。"""
        project = await self.get(project_id)
        if project is None:
            return None
        project.status = status
        if progress is not None:
            project.progress = progress
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def update(self, project_id: str, **kwargs) -> Optional[Project]:
        """通用更新方法（更新 title、style 等字段）。"""
        project = await self.get(project_id)
        if project is None:
            return None
        for key, value in kwargs.items():
            if hasattr(project, key):
                setattr(project, key, value)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    # ── 删除 ──
    async def delete(self, project_id: str) -> bool:
        """软删除（取消项目，保留数据）。"""
        project = await self.get(project_id)
        if project is None:
            return False
        project.status = ProjectStatus.CANCELLED
        await self.session.commit()
        return True

    async def delete_hard(self, project_id: str) -> bool:
        """硬删除（彻底删除项目及关联制品）。"""
        project = await self.get(project_id)
        if project is None:
            return False
        await self.session.delete(project)
        await self.session.commit()
        return True

    # ── 统计 ──
    async def count_by_status(self, user_id: Optional[str] = None) -> dict:
        """按状态统计项目数量。"""
        stmt = select(Project.status, func.count(Project.id)).group_by(Project.status)
        if user_id:
            stmt = stmt.where(Project.user_id == user_id)
        result = await self.session.execute(stmt)
        return {row[0].value: row[1] for row in result}

    async def total_count(self, user_id: Optional[str] = None) -> int:
        """项目总数。"""
        stmt = select(func.count(Project.id))
        if user_id:
            stmt = stmt.where(Project.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar() or 0


class ArtifactRepository:
    """制品数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, artifact: Artifact) -> Artifact:
        """创建制品记录。"""
        self.session.add(artifact)
        await self.session.commit()
        await self.session.refresh(artifact)
        return artifact

    async def get_by_key(self, project_id: str, key: str) -> Optional[Artifact]:
        """按项目和键获取制品。"""
        result = await self.session.execute(
            select(Artifact).where(
                Artifact.project_id == project_id,
                Artifact.key == key,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: str) -> List[Artifact]:
        """获取项目的所有制品。"""
        result = await self.session.execute(
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(Artifact.created_at)
        )
        return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════
# v7.0: PreferenceRepository — 偏好锚点持久化
# ═══════════════════════════════════════════════════════════

class PreferenceRepository:
    """偏好数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_anchor(
        self,
        user_id: str,
        category: str,
        key: str,
        weight: float,
        source: str = "explicit",
        decay_clock: float = 0.0,
        total_likes: int = 0,
        total_corrections: int = 0,
        metadata_json: dict = None,
    ) -> "PreferenceAnchorOrm":
        """插入或更新偏好锚点"""
        from core.models import PreferenceAnchorOrm
        import time as _time

        result = await self.session.execute(
            select(PreferenceAnchorOrm).where(
                PreferenceAnchorOrm.user_id == user_id,
                PreferenceAnchorOrm.category == category,
                PreferenceAnchorOrm.key == key,
            )
        )
        anchor = result.scalar_one_or_none()

        if anchor:
            anchor.weight = weight
            anchor.source = source
            anchor.decay_clock = decay_clock or _time.time()
            anchor.total_likes = total_likes
            anchor.total_corrections = total_corrections
            if metadata_json:
                anchor.metadata_json = {**anchor.metadata_json, **metadata_json}
        else:
            anchor = PreferenceAnchorOrm(
                user_id=user_id, category=category, key=key,
                weight=weight, source=source,
                decay_clock=decay_clock or _time.time(),
                total_likes=total_likes, total_corrections=total_corrections,
                metadata_json=metadata_json or {},
            )
            self.session.add(anchor)
        await self.session.commit()
        return anchor

    async def get_all_for_user(self, user_id: str) -> List["PreferenceAnchorOrm"]:
        """获取用户全部偏好锚点"""
        from core.models import PreferenceAnchorOrm
        result = await self.session.execute(
            select(PreferenceAnchorOrm)
            .where(PreferenceAnchorOrm.user_id == user_id)
            .order_by(PreferenceAnchorOrm.weight.desc())
        )
        return list(result.scalars().all())

    async def delete_anchor(self, user_id: str, category: str, key: str) -> bool:
        """删除偏好锚点"""
        from core.models import PreferenceAnchorOrm
        result = await self.session.execute(
            select(PreferenceAnchorOrm).where(
                PreferenceAnchorOrm.user_id == user_id,
                PreferenceAnchorOrm.category == category,
                PreferenceAnchorOrm.key == key,
            )
        )
        anchor = result.scalar_one_or_none()
        if anchor:
            await self.session.delete(anchor)
            await self.session.commit()
            return True
        return False

    async def record_evolution(
        self, user_id: str, category: str,
        old_key: Optional[str], new_key: str, trigger: str,
        old_weight: float = 0.0, new_weight: float = 0.0,
        project_id: Optional[str] = None,
    ) -> "PreferenceEvolutionOrm":
        """记录偏好演化事件"""
        from core.models import PreferenceEvolutionOrm
        event = PreferenceEvolutionOrm(
            user_id=user_id, category=category,
            old_key=old_key, new_key=new_key, trigger=trigger,
            old_weight=old_weight, new_weight=new_weight,
            project_id=project_id,
        )
        self.session.add(event)
        await self.session.commit()
        return event

    async def get_evolution_history(
        self, user_id: str, days: int = 30
    ) -> List["PreferenceEvolutionOrm"]:
        """获取演化历史"""
        from core.models import PreferenceEvolutionOrm
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(PreferenceEvolutionOrm)
            .where(
                PreferenceEvolutionOrm.user_id == user_id,
                PreferenceEvolutionOrm.created_at >= cutoff,
            )
            .order_by(PreferenceEvolutionOrm.created_at.desc())
        )
        return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════
# v7.0: SocialRepository + AuditRepository
# ═══════════════════════════════════════════════════════════

class SocialRepository:
    """社媒排期数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_post(
        self, post_id: str, user_id: str, platform: str,
        content: dict, scheduled_time: Optional[datetime] = None,
    ) -> "ScheduledPostOrm":
        from core.models import ScheduledPostOrm
        post = ScheduledPostOrm(
            post_id=post_id, user_id=user_id, platform=platform,
            content_json=content, scheduled_time=scheduled_time,
            status="pending",
        )
        self.session.add(post)
        await self.session.commit()
        return post

    async def get_pending(self) -> List["ScheduledPostOrm"]:
        from core.models import ScheduledPostOrm
        result = await self.session.execute(
            select(ScheduledPostOrm)
            .where(ScheduledPostOrm.status == "pending")
            .order_by(ScheduledPostOrm.created_at)
        )
        return list(result.scalars().all())

    async def update_status(
        self, post_id: str, status: str, result_json: dict = None
    ) -> bool:
        from core.models import ScheduledPostOrm
        result = await self.session.execute(
            select(ScheduledPostOrm).where(ScheduledPostOrm.post_id == post_id)
        )
        post = result.scalar_one_or_none()
        if post:
            post.status = status
            if result_json:
                post.result_json = result_json
            if status == "published":
                post.published_at = datetime.now(timezone.utc)
            await self.session.commit()
            return True
        return False

    async def get_history(
        self, user_id: Optional[str] = None, limit: int = 50
    ) -> List["ScheduledPostOrm"]:
        from core.models import ScheduledPostOrm
        stmt = (
            select(ScheduledPostOrm)
            .order_by(ScheduledPostOrm.created_at.desc())
            .limit(limit)
        )
        if user_id:
            stmt = stmt.where(ScheduledPostOrm.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def cancel_post(self, post_id: str) -> bool:
        return await self.update_status(post_id, "cancelled")


class AuditRepository:
    """审计日志数据访问层"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def log(
        self, action: str, resource_type: str,
        resource_id: Optional[str] = None, user_id: str = "system",
        detail: dict = None, trace_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> "AuditLog":
        from core.models import AuditLog
        import uuid as _uuid
        entry = AuditLog(
            trace_id=trace_id or str(_uuid.uuid4()),
            user_id=user_id, action=action,
            resource_type=resource_type, resource_id=resource_id,
            detail=detail or {}, ip_address=ip_address,
        )
        self.session.add(entry)
        await self.session.commit()
        return entry

    async def query(
        self, user_id: Optional[str] = None,
        action: Optional[str] = None, limit: int = 100,
    ) -> List["AuditLog"]:
        from core.models import AuditLog
        stmt = (
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        if user_id:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
