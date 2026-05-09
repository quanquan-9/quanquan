"""
WebSocket 实时广播器 — 推送导演状态变更、Agent进度、项目状态到所有WebSocket客户端
==================================================================================
集成 api/websocket.py ConnectionManager，提供高级广播能力：
  - 导演状态转换实时推送
  - Agent 执行状态推送
  - 活跃项目进度每2秒自动推送
  - 全局事件广播
"""
import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field

logger = logging.getLogger("quanquan.ws_broadcaster")


@dataclass
class BroadcastEvent:
    """广播事件结构"""
    event_type: str          # 事件类型: director_state, agent_status, project_progress, system_alert
    data: dict              # 事件负载
    timestamp: float = field(default_factory=time.time)
    project_id: str = ""    # 关联项目ID（可选）


class WSBroadcaster:
    """
    WebSocket 实时广播器
    
    功能:
      - 单播/组播/广播事件到连接的 WebSocket 客户端
      - 自动追踪活跃项目并推送进度
      - 导演状态机状态变更时立即广播
      - Agent 执行状态实时推送
    
    用法:
      broadcaster = WSBroadcaster(ws_manager, projects_store)
      await broadcaster.broadcast("director_state", {"state": "planning"})
      await broadcaster.start_auto_progress()  # 启动自动进度推送
    """

    # 事件类型常量
    EVENT_DIRECTOR_STATE = "director_state"
    EVENT_AGENT_STATUS = "agent_status"
    EVENT_PROJECT_PROGRESS = "project_progress"
    EVENT_PROJECT_CREATED = "project_created"
    EVENT_PROJECT_COMPLETED = "project_completed"
    EVENT_PROJECT_CANCELLED = "project_cancelled"
    EVENT_SYSTEM_ALERT = "system_alert"
    EVENT_RENDER_PROGRESS = "render_progress"
    EVENT_EXPORT_PROGRESS = "export_progress"
    EVENT_TEMPLATE_APPLIED = "template_applied"

    # 导演状态到中文描述的映射
    STATE_LABELS: Dict[str, str] = {
        "idle": "空闲",
        "analyzing": "分析中",
        "retrieving": "检索中",
        "planning": "规划中",
        "dispatching": "调度中",
        "monitoring": "监控中",
        "reflecting": "反思中",
        "replanning": "重新规划",
        "reworking": "重做中",
        "finalizing": "收尾中",
        "reporting": "生成报告",
    }

    # Agent名称到中文描述的映射
    AGENT_LABELS: Dict[str, str] = {
        "Scriptwriter": "编剧",
        "Storyboard": "分镜师",
        "BGM": "配乐师",
        "Voiceover": "配音师",
        "Styling": "调色师",
        "QC": "质检",
        "Delivery": "交付",
        "VideoRender": "渲染师",
    }

    def __init__(self, ws_manager, projects_store: dict = None):
        """
        初始化广播器
        
        Args:
            ws_manager: api.websocket.ConnectionManager 实例
            projects_store: 项目存储字典（用于自动进度追踪）
        """
        self.ws_manager = ws_manager
        self._projects_store = projects_store or {}
        self._auto_progress_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_director_state: str = "idle"
        self._sent_events_count: int = 0
        self._event_history: List[BroadcastEvent] = []  # 最近100个事件

    # ── 核心广播方法 ──

    async def broadcast(self, event_type: str, data: dict, project_id: str = "") -> int:
        """
        广播事件到所有连接的客户端
        
        Args:
            event_type: 事件类型 (使用 EVENT_* 常量)
            data: 事件数据
            project_id: 关联项目ID（可选）
        
        Returns:
            发送成功的事件数 (int)
        """
        event = BroadcastEvent(
            event_type=event_type,
            data=data,
            project_id=project_id or data.get("project_id", ""),
        )
        message = {
            "event": event_type,
            "data": data,
            "timestamp": event.timestamp,
        }
        if event.project_id:
            message["project_id"] = event.project_id

        # 记录事件
        self._event_history.append(event)
        if len(self._event_history) > 100:
            self._event_history = self._event_history[-100:]

        # 广播到所有连接的客户端
        try:
            await self.ws_manager.broadcast_all(message)
            self._sent_events_count += 1
            return 1
        except Exception as e:
            logger.warning(f"[WSBroadcaster] 广播失败: {e}")
            return 0

    async def broadcast_to_project(self, event_type: str, data: dict, project_id: str) -> int:
        """
        向特定项目房间广播
        
        Args:
            event_type: 事件类型
            data: 事件数据
            project_id: 目标项目ID
        
        Returns:
            发送成功的事件数
        """
        message = {
            "event": event_type,
            "data": data,
            "project_id": project_id,
            "timestamp": time.time(),
        }
        try:
            await self.ws_manager.broadcast_to_project(project_id, message)
            self._sent_events_count += 1
            return 1
        except Exception as e:
            logger.warning(f"[WSBroadcaster] 项目广播失败 [{project_id}]: {e}")
            return 0

    # ── 导演状态广播 ──

    async def on_director_state_change(self, new_state: str, metadata: dict = None):
        """
        导演状态变更时调用，自动广播
        
        Args:
            new_state: 新状态值 (如 "planning", "dispatching")
            metadata: 附加元数据
        """
        old_state = self._last_director_state
        self._last_director_state = new_state
        data = {
            "from_state": old_state,
            "to_state": new_state,
            "state_label": self.STATE_LABELS.get(new_state, new_state),
            "previous_label": self.STATE_LABELS.get(old_state, old_state),
        }
        if metadata:
            data.update(metadata)
        await self.broadcast(self.EVENT_DIRECTOR_STATE, data)

    # ── Agent 状态广播 ──

    async def on_agent_status(self, agent_name: str, status: str, project_id: str = "",
                              detail: dict = None):
        """
        Agent 状态变更时广播
        
        Args:
            agent_name: Agent名称 (如 "Scriptwriter")
            status: 状态 (started, running, completed, failed)
            project_id: 项目ID
            detail: 附加详情
        """
        data = {
            "agent": agent_name,
            "agent_label": self.AGENT_LABELS.get(agent_name, agent_name),
            "status": status,
            "project_id": project_id,
        }
        if detail:
            data["detail"] = detail
        await self.broadcast(self.EVENT_AGENT_STATUS, data, project_id)

    # ── 项目进度广播 ──

    async def on_project_progress(self, project_id: str, progress: float, status: str = "",
                                   state: str = ""):
        """
        项目进度更新时广播
        
        Args:
            project_id: 项目ID
            progress: 进度值 0.0 ~ 1.0
            status: 项目状态 (active, completed, queued 等)
            state: 导演内部状态
        """
        data = {
            "project_id": project_id,
            "progress": round(progress, 3),
            "percent": round(progress * 100, 1),
            "status": status,
            "state": state,
        }
        await self.broadcast_to_project(self.EVENT_PROJECT_PROGRESS, data, project_id)
        # 也广播到全局频道
        await self.ws_manager.broadcast_to_project("global", {
            "event": self.EVENT_PROJECT_PROGRESS,
            "data": data,
            "timestamp": time.time(),
        })

    async def on_project_completed(self, project_id: str, output_info: dict = None):
        """项目完成时广播"""
        data = {
            "project_id": project_id,
            "output": output_info or {},
            "message": "视频生产完成 🎉",
        }
        await self.broadcast(self.EVENT_PROJECT_COMPLETED, data, project_id)

    async def on_project_cancelled(self, project_id: str, reason: str = ""):
        """项目取消时广播"""
        data = {
            "project_id": project_id,
            "reason": reason or "用户主动取消",
        }
        await self.broadcast(self.EVENT_PROJECT_CANCELLED, data, project_id)

    # ── 自动进度推送 ──

    async def _auto_progress_loop(self):
        """后台任务：每2秒推送活跃项目的进度"""
        while self._running:
            try:
                for pid, proj in list(self._projects_store.items()):
                    if proj.get("status") in ("active", "queued"):
                        progress = proj.get("progress", 0)
                        await self.on_project_progress(
                            project_id=pid,
                            progress=progress,
                            status=proj.get("status", "active"),
                            state=proj.get("state", ""),
                        )
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"[WSBroadcaster] 自动进度推送异常: {e}")
                await asyncio.sleep(5)

    async def start_auto_progress(self):
        """启动自动进度推送后台任务"""
        if self._auto_progress_task is not None and not self._auto_progress_task.done():
            logger.info("[WSBroadcaster] 自动进度推送已在运行中")
            return
        self._running = True
        self._auto_progress_task = asyncio.create_task(self._auto_progress_loop())
        logger.info("[WSBroadcaster] ✅ 自动进度推送已启动 (每2秒)")

    async def stop_auto_progress(self):
        """停止自动进度推送"""
        self._running = False
        if self._auto_progress_task:
            self._auto_progress_task.cancel()
            try:
                await self._auto_progress_task
            except asyncio.CancelledError:
                pass
        logger.info("[WSBroadcaster] 自动进度推送已停止")

    # ── 渲染 & 导出进度 ──

    async def on_render_progress(self, project_id: str, frame: int, total_frames: int,
                                  percent: float = None):
        """渲染进度广播"""
        data = {
            "project_id": project_id,
            "frame": frame,
            "total_frames": total_frames,
            "percent": percent if percent is not None else round(frame / max(total_frames, 1) * 100, 1),
        }
        await self.broadcast_to_project(self.EVENT_RENDER_PROGRESS, data, project_id)

    async def on_export_progress(self, project_id: str, format: str, percent: float,
                                  stage: str = ""):
        """导出进度广播"""
        data = {
            "project_id": project_id,
            "format": format,
            "percent": percent,
            "stage": stage or "exporting",
        }
        await self.broadcast_to_project(self.EVENT_EXPORT_PROGRESS, data, project_id)

    # ── 模板应用广播 ──

    async def on_template_applied(self, project_id: str, template_name: str,
                                   template_id: str = ""):
        """模板应用事件广播"""
        data = {
            "project_id": project_id,
            "template_name": template_name,
            "template_id": template_id,
            "message": f"已应用模板: {template_name}",
        }
        await self.broadcast(self.EVENT_TEMPLATE_APPLIED, data, project_id)

    # ── 系统告警 ──

    async def on_system_alert(self, level: str, message: str, detail: dict = None):
        """
        系统告警广播
        
        Args:
            level: 告警级别 (info, warning, error, critical)
            message: 告警消息
            detail: 附加详情
        """
        data = {
            "level": level,
            "message": message,
            "detail": detail or {},
        }
        await self.broadcast(self.EVENT_SYSTEM_ALERT, data)

    # ── 工具方法 ──

    def get_stats(self) -> dict:
        """获取广播器统计信息"""
        return {
            "sent_events": self._sent_events_count,
            "last_director_state": self._last_director_state,
            "auto_progress_running": self._running,
            "event_history_count": len(self._event_history),
            "recent_events": [
                {"type": e.event_type, "ts": e.timestamp, "pid": e.project_id}
                for e in self._event_history[-20:]
            ][::-1],
        }

    def get_active_project_ids(self) -> List[str]:
        """获取所有活跃项目ID"""
        return [
            pid for pid, p in self._projects_store.items()
            if p.get("status") in ("active", "queued")
        ]


# ── 全局单例（由 server.py 初始化） ──
ws_broadcaster: Optional[WSBroadcaster] = None
