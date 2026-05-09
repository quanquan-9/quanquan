"""
WebSocket 实时推送 — 项目进度/Agent状态/QC问题 实时推送到前端
"""
import json
import asyncio
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect


class ConnectionManager:
    """WebSocket 连接管理器 — project_id → WebSocket 映射"""

    def __init__(self):
        self.project_connections: Dict[str, Set[WebSocket]] = {}
        self.agent_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, ws: WebSocket, project_id: str):
        await ws.accept()
        self.project_connections.setdefault(project_id, set()).add(ws)

    def disconnect(self, ws: WebSocket, project_id: str):
        if project_id in self.project_connections:
            self.project_connections[project_id].discard(ws)
            if not self.project_connections[project_id]:
                del self.project_connections[project_id]

    async def broadcast_to_project(self, project_id: str, message: dict):
        if project_id not in self.project_connections:
            return
        dead = set()
        for ws in list(self.project_connections[project_id]):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws, project_id)

    async def broadcast_all(self, message: dict):
        """广播给所有连接"""
        for pid in list(self.project_connections.keys()):
            await self.broadcast_to_project(pid, message)


manager = ConnectionManager()


def format_event_for_frontend(event: dict) -> dict:
    """将 Context Bus 事件转为前端可消费的状态消息"""
    base = {
        "project_id": event.get("project_id", ""),
        "timestamp": event.get("timestamp", ""),
    }

    event_type = event.get("event_type", event.get("type", ""))
    payload = event.get("payload", event)

    if event_type == "TASK_DISPATCH":
        return {**base, "event": "agent_started",
                "agent": payload.get("agent", ""), "node_id": payload.get("node_id", "")}
    elif event_type == "RESULT_PUBLISH":
        return {**base, "event": "agent_completed",
                "agent": payload.get("agent", ""), "output_key": payload.get("output_key", "")}
    elif event_type == "QC_ISSUE":
        return {**base, "event": "qc_issue",
                "severity": payload.get("severity", ""), "node": payload.get("node_id", "")}
    elif event_type == "QC_WARNING":
        return {**base, "event": "qc_warning",
                "detail": payload.get("detail", "")}
    elif event_type == "PIPELINE_COMPLETE":
        return {**base, "event": "completed",
                "summary": payload.get("summary", {}),
                "duration_sec": payload.get("total_duration_sec", 0)}
    elif event_type == "HEARTBEAT":
        return {**base, "event": "heartbeat",
                "agent": payload.get("agent", "")}
    elif event_type == "REPLAN_REQUEST":
        return {**base, "event": "replanning",
                "failed_node": payload.get("failed_node", "")}
    else:
        return {**base, "event": "unknown", "raw": event}
