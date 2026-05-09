"""
quanquan ORM 模型 — SQLAlchemy 2.0 声明式映射

定义项目(Project)和制品(Artifact)两个核心实体。
与现有 artifacts/ 目录的文件存储配合使用。
"""
import enum
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


# ── 枚举 ──
class ProjectStatus(str, enum.Enum):
    """项目生命周期状态"""
    CREATED = "created"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ── 模型 ──
class Project(Base):
    """视频生产项目"""

    __tablename__ = "projects"

    # ── 主键 ──
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: f"proj_{uuid.uuid4().hex[:12]}",
    )

    # ── 用户关联 ──
    user_id: Mapped[str] = mapped_column(String(128), index=True, default="anonymous")

    # ── 内容 ──
    title: Mapped[str] = mapped_column(String(256), default="未命名项目")
    text: Mapped[str] = mapped_column(Text, default="")
    style: Mapped[str] = mapped_column(String(64), default="auto")
    duration_sec: Mapped[int] = mapped_column(Integer, default=180)

    # ── 状态 ──
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus),
        default=ProjectStatus.CREATED,
        index=True,
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    # ── 元数据 ──
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    # ── 时间戳 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── 关系 ──
    artifacts: Mapped[List["Artifact"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, title='{self.title}', status={self.status})>"


class Artifact(Base):
    """项目制品（脚本、配音、BGM、QC报告等）"""

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )

    # ── 制品标识 ──
    key: Mapped[str] = mapped_column(String(256))  # 如 "script_v1", "voiceover_v1"
    stage: Mapped[str] = mapped_column(String(64))  # 如 "script_gen", "voiceover", "bgm"

    # ── 内容 ──
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # ── 时间戳 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # ── 关系 ──
    project: Mapped["Project"] = relationship(back_populates="artifacts")

    def __repr__(self) -> str:
        return f"<Artifact(id={self.id}, key='{self.key}', stage='{self.stage}')>"


# ═══════════════════════════════════════════════════════════
# v7.0: 偏好锚点 → 持久化 PreferenceDecayEngine
# ═══════════════════════════════════════════════════════════

class PreferenceAnchorOrm(Base):
    """用户偏好锚点（对应 PreferenceDecayEngine.PreferenceAnchor）"""

    __tablename__ = "preference_anchors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String(32), default="explicit")
    total_likes: Mapped[int] = mapped_column(Integer, default=0)
    total_corrections: Mapped[int] = mapped_column(Integer, default=0)
    decay_clock: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<Anchor(user={self.user_id}, cat={self.category}, key={self.key}, w={self.weight:.2f})>"


class PreferenceEvolutionOrm(Base):
    """偏好演化事件"""

    __tablename__ = "preference_evolutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    old_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    new_key: Mapped[str] = mapped_column(String(128), nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    old_weight: Mapped[float] = mapped_column(Float, default=0.0)
    new_weight: Mapped[float] = mapped_column(Float, default=0.0)
    project_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f"<Evolution(user={self.user_id}, {self.trigger}: {self.old_key}→{self.new_key})>"


# ═══════════════════════════════════════════════════════════
# v7.0: 社媒排期 → 持久化 SocialScheduler
# ═══════════════════════════════════════════════════════════

class ScheduledPostOrm(Base):
    """社媒排期帖子"""

    __tablename__ = "scheduled_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), index=True, default="anonymous")
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    scheduled_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<ScheduledPost(id={self.post_id}, platform={self.platform}, status={self.status})>"


# ═══════════════════════════════════════════════════════════
# v7.0: 审计日志 — 所有关键操作用
# ═══════════════════════════════════════════════════════════

class AuditLog(Base):
    """不可篡改审计日志"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), index=True, default="system")
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    def __repr__(self):
        return f"<AuditLog(action={self.action}, resource={self.resource_type}/{self.resource_id})>"
