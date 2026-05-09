"""
Context Bus — 异步事件驱动的 Agent 通信总线
============================================
所有 Agent 不直接点对点通信，通过 ContextBus 发布/订阅事件。
- 后端：内存 (asyncio.Queue) · 生产可切 Redis Streams
"""

import asyncio
import uuid
import time
import logging
from typing import Dict, List, Optional, Callable, Awaitable, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("quanquan.context_bus")


class EventType(str, Enum):
    TASK_DISPATCH    = "TASK_DISPATCH"
    RESULT_PUBLISH   = "RESULT_PUBLISH"
    QC_FAILED        = "QC_FAILED"
    REPLAN_REQUEST   = "REPLAN_REQUEST"
    USER_FEEDBACK    = "USER_FEEDBACK"
    HEARTBEAT        = "HEARTBEAT"
    NODE_COMPLETE    = "NODE_COMPLETE"
    PIPELINE_COMPLETE = "PIPELINE_COMPLETE"
    NODE_FAILED      = "NODE_FAILED"


@dataclass
class Event:
    event_id: str
    timestamp: float
    event_type: EventType
    agent_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    context_version: str = "v1"

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else self.event_type,
            "agent_id": self.agent_id,
            "payload": self.payload,
            "context_version": self.context_version,
        }


Subscriber = Callable[[Event], Awaitable[None]]


class ContextBus:
    HEARTBEAT_TIMEOUT = 30.0

    def __init__(self, backend: str = "memory"):
        self.backend = backend
        self._connected = False
        self._subscriptions: Dict[EventType, List[Subscriber]] = {et: [] for et in EventType}
        self._heartbeats: Dict[str, float] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._consumer_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self.event_count: int = 0

    async def connect(self) -> None:
        self._connected = True
        self._consumer_task = asyncio.create_task(self._consume_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_monitor())
        logger.info("ContextBus connected: %s", self.backend)

    async def disconnect(self) -> None:
        self._connected = False
        for task in (self._consumer_task, self._heartbeat_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("ContextBus disconnected: events=%s", self.event_count)

    async def publish(self, event_type: EventType, payload: Dict[str, Any],
                      agent_id: str = "unknown", context_version: str = "v1") -> Event:
        event = Event(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            timestamp=time.time(),
            event_type=event_type,
            agent_id=agent_id,
            payload=payload,
            context_version=context_version,
        )
        await self._queue.put(event)
        self.event_count += 1
        return event

    async def subscribe(self, event_type: EventType, callback: Subscriber) -> None:
        if callback not in self._subscriptions[event_type]:
            self._subscriptions[event_type].append(callback)

    async def unsubscribe(self, event_type: EventType, callback: Subscriber) -> None:
        subs = self._subscriptions[event_type]
        if callback in subs:
            subs.remove(callback)

    async def heartbeat(self, agent_id: str) -> None:
        self._heartbeats[agent_id] = time.time()

    def get_stale_agents(self) -> List[str]:
        now = time.time()
        return [aid for aid, ts in self._heartbeats.items() if now - ts > self.HEARTBEAT_TIMEOUT]

    async def _consume_loop(self) -> None:
        while self._connected:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            for callback in self._subscriptions.get(event.event_type, []):
                try:
                    await callback(event)
                except Exception:
                    logger.exception("Subscriber error: %s %s", event.event_type, event.event_id)

    async def _heartbeat_monitor(self) -> None:
        while self._connected:
            try:
                await asyncio.sleep(15.0)
                stale = self.get_stale_agents()
                if stale:
                    logger.warning("Stale agents: %s", stale)
            except asyncio.CancelledError:
                break


# ── 全局单例 ──
context_bus = ContextBus()
