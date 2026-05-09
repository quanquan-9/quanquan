"""
团队协作系统 (Team Collaboration)

功能：
- 多用户协作
- 角色权限管理
- 项目共享
- 评论与审阅
- 活动日志
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class TeamRole(Enum):
    OWNER = "owner"         # 所有者 — 完全控制
    ADMIN = "admin"         # 管理员 — 管理团队
    EDITOR = "editor"       # 编辑 — 编辑项目
    REVIEWER = "reviewer"   # 审阅者 — 查看+评论
    VIEWER = "viewer"       # 查看者 — 只读


ROLE_PERMISSIONS = {
    TeamRole.OWNER: ["*"],
    TeamRole.ADMIN: ["manage_team", "create_project", "edit_project",
                      "delete_project", "review", "view", "export", "invite"],
    TeamRole.EDITOR: ["create_project", "edit_project", "review", "view", "export"],
    TeamRole.REVIEWER: ["review", "view"],
    TeamRole.VIEWER: ["view"],
}


@dataclass
class TeamMember:
    """团队成员"""
    user_id: str
    username: str
    role: TeamRole
    joined_at: str = ""
    invited_by: str = ""


@dataclass
class Team:
    """团队"""
    team_id: str
    name: str
    description: str = ""
    members: List[TeamMember] = field(default_factory=list)
    created_at: str = ""
    owner_id: str = ""
    settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Comment:
    """评论"""
    comment_id: str
    project_id: str
    user_id: str
    username: str
    text: str
    timestamp_sec: float = 0        # 视频时间点
    resolved: bool = False
    resolved_by: str = ""
    created_at: str = ""


@dataclass
class ActivityLog:
    """活动日志"""
    log_id: str
    user_id: str
    username: str
    action: str                     # create / edit / delete / comment / export / share
    target_type: str                # project / team / comment
    target_id: str
    details: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


class TeamManager:
    """团队管理器"""

    def __init__(self):
        self._teams: Dict[str, Team] = {}
        self._invitations: Dict[str, dict] = {}

    def create_team(
        self, name: str, owner_id: str, owner_name: str,
        description: str = "",
    ) -> Team:
        """创建团队"""
        team_id = f"team_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{owner_id[:8]}"
        team = Team(
            team_id=team_id,
            name=name,
            description=description,
            owner_id=owner_id,
            created_at=datetime.utcnow().isoformat(),
            members=[
                TeamMember(
                    user_id=owner_id,
                    username=owner_name,
                    role=TeamRole.OWNER,
                    joined_at=datetime.utcnow().isoformat(),
                )
            ],
        )
        self._teams[team_id] = team
        logger.info(f"Team created: {team_id} ({name})")
        return team

    def add_member(
        self, team_id: str, user_id: str, username: str,
        role: TeamRole = TeamRole.EDITOR, invited_by: str = "",
    ) -> TeamMember:
        """添加成员"""
        team = self._teams.get(team_id)
        if not team:
            raise ValueError(f"Team not found: {team_id}")

        member = TeamMember(
            user_id=user_id,
            username=username,
            role=role,
            joined_at=datetime.utcnow().isoformat(),
            invited_by=invited_by,
        )

        # 替换已有成员
        existing = next((m for m in team.members if m.user_id == user_id), None)
        if existing:
            existing.role = role
            return existing

        team.members.append(member)
        return member

    def remove_member(self, team_id: str, user_id: str):
        team = self._teams.get(team_id)
        if team:
            team.members = [m for m in team.members if m.user_id != user_id]

    def check_permission(
        self, team_id: str, user_id: str, action: str
    ) -> bool:
        """检查权限"""
        team = self._teams.get(team_id)
        if not team:
            return False

        member = next((m for m in team.members if m.user_id == user_id), None)
        if not member:
            return False

        permissions = ROLE_PERMISSIONS.get(member.role, [])
        return "*" in permissions or action in permissions

    def get_team(self, team_id: str) -> Optional[Team]:
        return self._teams.get(team_id)

    def list_user_teams(self, user_id: str) -> List[Team]:
        return [
            t for t in self._teams.values()
            if any(m.user_id == user_id for m in t.members)
        ]


class CommentSystem:
    """评论与审阅系统"""

    def __init__(self):
        self._comments: Dict[str, List[Comment]] = {}  # project_id → comments

    def add_comment(
        self, project_id: str, user_id: str, username: str,
        text: str, timestamp_sec: float = 0,
    ) -> Comment:
        """添加评论"""
        comment = Comment(
            comment_id=f"cmt_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
            project_id=project_id,
            user_id=user_id,
            username=username,
            text=text,
            timestamp_sec=timestamp_sec,
            created_at=datetime.utcnow().isoformat(),
        )
        self._comments.setdefault(project_id, []).append(comment)
        return comment

    def resolve_comment(
        self, project_id: str, comment_id: str, resolved_by: str
    ):
        comments = self._comments.get(project_id, [])
        for c in comments:
            if c.comment_id == comment_id:
                c.resolved = True
                c.resolved_by = resolved_by
                return

    def get_comments(
        self, project_id: str, unresolved_only: bool = False
    ) -> List[Comment]:
        comments = self._comments.get(project_id, [])
        if unresolved_only:
            return [c for c in comments if not c.resolved]
        return comments

    def get_comments_at_time(
        self, project_id: str, timestamp_sec: float
    ) -> List[Comment]:
        return [
            c for c in self._comments.get(project_id, [])
            if abs(c.timestamp_sec - timestamp_sec) < 1.0
        ]


class ActivityTracker:
    """活动追踪器"""

    def __init__(self):
        self._logs: List[ActivityLog] = []

    def log(
        self, user_id: str, username: str,
        action: str, target_type: str, target_id: str,
        details: Dict[str, Any] = None,
    ):
        entry = ActivityLog(
            log_id=f"log_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
            user_id=user_id,
            username=username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            created_at=datetime.utcnow().isoformat(),
        )
        self._logs.append(entry)

        # 保持最近 1000 条
        if len(self._logs) > 1000:
            self._logs = self._logs[-1000:]

    def get_user_activity(self, user_id: str, limit: int = 50) -> List[ActivityLog]:
        return [l for l in self._logs if l.user_id == user_id][-limit:]

    def get_project_activity(self, project_id: str, limit: int = 50) -> List[ActivityLog]:
        return [
            l for l in self._logs
            if l.target_id == project_id or l.details.get("project_id") == project_id
        ][-limit:]

    def get_recent_activity(self, limit: int = 50) -> List[ActivityLog]:
        return self._logs[-limit:]


# 全局实例
team_manager = TeamManager()
comment_system = CommentSystem()
activity_tracker = ActivityTracker()
