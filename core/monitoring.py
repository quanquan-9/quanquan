"""
Prometheus 监控 — 全量指标 + 结构化日志
"""
import time
import json
import logging
from datetime import datetime, timezone


# ═══════════ 模拟 Prometheus 指标（生产环境替换为 prometheus_client） ═══════════

class _Histogram:
    def __init__(self, name, desc, labels=None, buckets=None):
        self.name = name
        self.desc = desc
        self._labels = labels or []
        self.buckets = buckets or []
        self._values = []

    def observe(self, value, **labels):
        self._values.append({"value": value, "labels": labels, "ts": time.time()})


class _Counter:
    def __init__(self, name, desc, labels=None):
        self.name = name
        self.desc = desc
        self._labels = labels or []
        self._count = 0

    def inc(self, amount=1, **labels):
        self._count += amount

class _Gauge:
    def __init__(self, name, desc, labels=None):
        self.name = name
        self.desc = desc
        self._labels = labels or []
        self._value = 0

    def set(self, value, **labels):
        self._value = value

    def value(self):
        return self._value


# ═══════════ 指标定义 ═══════════

task_duration_seconds = _Histogram(
    "quanquan_task_duration_seconds",
    "DAG节点执行时长",
    ["agent", "task_type"],
    buckets=[10, 30, 60, 120, 300, 600],
)

qc_issues_total = _Counter(
    "quanquan_qc_issues_total",
    "QC检测到的缺陷总数",
    ["severity", "check_type"],
)

replan_total = _Counter(
    "quanquan_replan_total",
    "导演触发的重规划次数",
    ["trigger_reason"],
)

agent_heartbeat = _Gauge(
    "quanquan_agent_heartbeat",
    "各Agent最后心跳时间戳",
    ["agent_id"],
)

dag_status = _Gauge(
    "quanquan_dag_status",
    "当前DAG执行状态",
    ["dag_id", "status"],
)

first_pass_yield = _Gauge(
    "quanquan_first_pass_yield",
    "无需修正的DAG占比",
)

active_projects = _Gauge(
    "quanquan_active_projects",
    "当前活跃项目数",
)

queue_depth = _Gauge(
    "quanquan_queue_depth",
    "任务队列深度",
    ["queue_name"],
)


# ═══════════ 结构化日志 ═══════════

class StructuredLogger:
    """JSON 格式结构化日志"""

    def __init__(self, name: str = "quanquan"):
        self.logger = logging.getLogger(name)

    def log_event(self, event: str, agent: str = "system",
                  project_id: str = None, node_id: str = None,
                  level: str = "INFO", **kwargs):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event,
            "agent": agent,
        }
        if project_id: entry["project_id"] = project_id
        if node_id: entry["node_id"] = node_id
        entry.update(kwargs)

        log_fn = getattr(self.logger, level.lower(), self.logger.info)
        log_fn(json.dumps(entry, ensure_ascii=False))


slog = StructuredLogger()
