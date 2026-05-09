"""
数据分析引擎 (Analytics Engine)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
功能：
- 多维度事件追踪（项目、渲染、LLM、错误等）
- Dashboard 摘要指标
- 24小时时间序列数据
- 按供应商的成本估算
- 内存存储 + 每 5 分钟自动持久化到 JSON

使用示例：
    engine = AnalyticsEngine()
    engine.record("project_created", {"project_id": "p1", "duration_sec": 180})
    metrics = engine.get_dashboard_metrics()
    ts = engine.get_time_series(hours=24)
"""

import os
import json
import time
import threading
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("quanquan.analytics_engine")

# ═══════════ 常量 ═══════════

PERSIST_PATH = "/data/quanquan/data/analytics.json"
AUTO_SAVE_INTERVAL_SEC = 300  # 5 分钟
MAX_TIME_SERIES_POINTS = 288   # 24小时 * 12个5分钟窗口

# LLM 成本单价（每 1K tokens，美元）
LLM_COST_PER_1K: Dict[str, Dict[str, float]] = {
    "deepseek":   {"input": 0.00014, "output": 0.00028},
    "openai":     {"input": 0.00250, "output": 0.01000},
    "anthropic":  {"input": 0.00300, "output": 0.01500},
    "local":      {"input": 0.0,     "output": 0.0},
}


@dataclass
class TimeSeriesPoint:
    """时间序列数据点（5分钟粒度）"""
    timestamp: float = field(default_factory=time.time)
    projects_created: int = 0
    projects_completed: int = 0
    total_video_seconds: float = 0.0
    avg_render_time: float = 0.0
    render_count: int = 0
    llm_calls: int = 0
    llm_tokens: int = 0
    errors: int = 0
    tts_chars: int = 0


class AnalyticsEngine:
    """用量分析与指标追踪引擎

    追踪所有关键业务指标，提供 Dashboard 摘要、时间序列和成本估算。
    数据存储：内存 (主) + 每 5 分钟自动持久化到 JSON（重启恢复）。
    """

    def __init__(self, persist_path: str = PERSIST_PATH):
        self._persist_path = persist_path
        os.makedirs(os.path.dirname(persist_path), exist_ok=True)

        # ── 累计指标（自启动以来）──
        self._lock = threading.RLock()

        # 计数器
        self._projects_created: int = 0
        self._projects_completed: int = 0
        self._total_video_seconds: float = 0.0
        self._render_times: List[float] = []       # 每次渲染耗时
        self._llm_calls: int = 0
        self._llm_tokens: int = 0
        self._tts_chars: int = 0
        self._errors: int = 0
        self._error_details: List[dict] = []        # 最近100条错误详情

        # LLM 用量按供应商细分
        self._llm_by_provider: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"calls": 0, "tokens": 0}
        )

        # 项目时长分布（直方图桶）
        self._duration_buckets: Dict[str, int] = defaultdict(int)
        self._duration_bucket_edges = [30, 60, 120, 180, 300, 600, 1800, 3600]

        # 时间序列（5分钟粒度，最近24小时）
        self._time_series: deque = deque(maxlen=MAX_TIME_SERIES_POINTS)
        self._current_window = TimeSeriesPoint()

        # 上次持久化时间
        self._last_save_time = 0.0

        # 启动后台自动保存线程
        self._save_thread: Optional[threading.Thread] = None
        self._stop_save = threading.Event()
        self._start_auto_save()

        # 尝试从磁盘恢复
        loaded = self._load_from_disk()
        logger.info(
            f"[AnalyticsEngine] 初始化完成 — "
            f"{'从磁盘恢复' if loaded else '全新启动'}，"
            f"持久化路径={persist_path}"
        )

    # ── 公共 API：记录事件 ────────────────────────────────────

    def record(self, event_type: str, data: Optional[dict] = None):
        """记录一个事件

        Args:
            event_type: 事件类型，支持:
                - project_created      项目创建
                - project_completed    项目完成
                - video_rendered       视频渲染完成
                - llm_call             LLM 调用
                - tts_generated        TTS 生成
                - error                错误事件
            data: 事件附带的上下文字典。
                  例如 project_created 需要 {"project_id": "...", "duration_sec": 180}
                  llm_call 需要 {"provider": "deepseek", "tokens": 1500, "type": "output"}
        """
        data = data or {}

        with self._lock:
            handler = {
                "project_created": self._on_project_created,
                "project_completed": self._on_project_completed,
                "video_rendered": self._on_video_rendered,
                "llm_call": self._on_llm_call,
                "tts_generated": self._on_tts_generated,
                "error": self._on_error,
            }.get(event_type)

            if handler:
                handler(data)
            else:
                logger.debug(f"[AnalyticsEngine] 未知事件类型: {event_type}")

    def _on_project_created(self, data: dict):
        self._projects_created += 1
        self._current_window.projects_created += 1

    def _on_project_completed(self, data: dict):
        self._projects_completed += 1
        self._current_window.projects_completed += 1

        # 视频时长
        duration = float(data.get("duration_sec", 0) or 0)
        if duration > 0:
            self._total_video_seconds += duration
            self._current_window.total_video_seconds += duration
            # 更新时长分布
            bucket_label = self._find_duration_bucket(duration)
            self._duration_buckets[bucket_label] += 1

    def _on_video_rendered(self, data: dict):
        render_time = float(data.get("render_time_sec", 0) or 0)
        if render_time > 0:
            self._render_times.append(render_time)
            # 保留最近1000条防止内存膨胀
            if len(self._render_times) > 1000:
                self._render_times = self._render_times[-1000:]

            self._current_window.render_count += 1

    def _on_llm_call(self, data: dict):
        provider = data.get("provider", "unknown")
        tokens = int(data.get("tokens", 0) or 0)

        self._llm_calls += 1
        self._llm_tokens += tokens
        self._current_window.llm_calls += 1
        self._current_window.llm_tokens += tokens

        prov = self._llm_by_provider[provider]
        prov["calls"] += 1
        prov["tokens"] += tokens

    def _on_tts_generated(self, data: dict):
        chars = int(data.get("chars", 0) or 0)
        self._tts_chars += chars
        self._current_window.tts_chars += chars

    def _on_error(self, data: dict):
        self._errors += 1
        self._current_window.errors += 1
        # 保留最近100条错误详情
        self._error_details.append({
            "timestamp": time.time(),
            "error_type": data.get("error_type", "unknown"),
            "message": str(data.get("message", ""))[:200],
            "project_id": data.get("project_id", ""),
        })
        if len(self._error_details) > 100:
            self._error_details = self._error_details[-100:]

    # ── 公共 API：查询指标 ────────────────────────────────────

    def get_dashboard_metrics(self) -> dict:
        """获取 Dashboard 摘要指标

        Returns:
            {
                "projects": {"created": 100, "completed": 85, "completion_rate": 0.85},
                "video": {"total_seconds": 5000, "avg_render_time_sec": 12.3},
                "llm": {"total_calls": 500, "total_tokens": 200000, "by_provider": {...}},
                "tts": {"total_chars": 50000},
                "errors": {"total": 3, "error_rate": 0.006, "recent": [...]},
                "duration_distribution": {"0-30s": 10, "30-60s": 20, ...},
                "updated_at": 1715000000.0,
            }
        """
        with self._lock:
            completion_rate = (
                self._projects_completed / max(self._projects_created, 1)
            )

            avg_render = (
                sum(self._render_times) / len(self._render_times)
                if self._render_times else 0.0
            )

            error_rate = self._errors / max(
                self._projects_created + self._llm_calls, 1
            )

            return {
                "projects": {
                    "created": self._projects_created,
                    "completed": self._projects_completed,
                    "completion_rate": round(completion_rate, 4),
                },
                "video": {
                    "total_seconds": round(self._total_video_seconds, 1),
                    "total_renders": len(self._render_times),
                    "avg_render_time_sec": round(avg_render, 2),
                },
                "llm": {
                    "total_calls": self._llm_calls,
                    "total_tokens": self._llm_tokens,
                    "by_provider": {
                        p: dict(stats)
                        for p, stats in self._llm_by_provider.items()
                    },
                },
                "tts": {
                    "total_chars": self._tts_chars,
                },
                "errors": {
                    "total": self._errors,
                    "error_rate": round(error_rate, 6),
                    "recent": self._error_details[-10:],
                },
                "duration_distribution": dict(self._duration_buckets),
                "updated_at": time.time(),
            }

    def get_time_series(self, hours: int = 24) -> list:
        """获取时间序列数据

        Args:
            hours: 往回追溯的小时数（默认 24，范围 1-72）

        Returns:
            [
                {"timestamp": 1715000000.0, "projects_created": 5, "errors": 1, ...},
                ...
            ]
        """
        hours = max(1, min(hours, 72))
        cutoff = time.time() - hours * 3600

        with self._lock:
            # 把当前未完成的窗口也纳入
            all_points = list(self._time_series) + [self._current_window]
            # 过滤 + 汇总
            filtered = []
            for p in all_points:
                if p.timestamp >= cutoff:
                    filtered.append({
                        "timestamp": p.timestamp,
                        "projects_created": p.projects_created,
                        "projects_completed": p.projects_completed,
                        "total_video_seconds": p.total_video_seconds,
                        "avg_render_time": p.avg_render_time,
                        "render_count": p.render_count,
                        "llm_calls": p.llm_calls,
                        "llm_tokens": p.llm_tokens,
                        "errors": p.errors,
                        "tts_chars": p.tts_chars,
                    })

        return filtered

    def get_cost_estimate(self) -> dict:
        """按供应商估算成本

        Returns:
            {
                "total_usd": 0.05,
                "by_provider": {
                    "deepseek": {"calls": 100, "tokens": 50000, "cost_usd": 0.01},
                    ...
                },
                "exchange_rate_note": "以美元计价，汇率为估算值"
            }
        """
        with self._lock:
            by_provider = {}
            total_cost = 0.0

            for provider, stats in self._llm_by_provider.items():
                pricing = LLM_COST_PER_1K.get(provider)
                if pricing is None:
                    # 未知供应商，使用 openai 定价作为估算
                    pricing = LLM_COST_PER_1K.get("openai", {"input": 0.0025, "output": 0.01})

                # 简化估算：假设 50% input, 50% output
                tokens = stats["tokens"]
                input_tokens = tokens // 2
                output_tokens = tokens - input_tokens

                input_cost = (input_tokens / 1000) * pricing["input"]
                output_cost = (output_tokens / 1000) * pricing["output"]
                cost = round(input_cost + output_cost, 6)

                by_provider[provider] = {
                    "calls": stats["calls"],
                    "tokens": tokens,
                    "cost_usd": cost,
                }
                total_cost += cost

            return {
                "total_usd": round(total_cost, 6),
                "by_provider": by_provider,
                "exchange_rate_note": "以美元计价，仅供参考",
                "estimated_at": time.time(),
            }

    # ── 持久化 ─────────────────────────────────────────────────

    def save_to_disk(self) -> bool:
        """手动触发持久化到磁盘"""
        with self._lock:
            data = self._serialize()
        try:
            tmp_path = self._persist_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._persist_path)
            self._last_save_time = time.time()
            logger.debug(f"[AnalyticsEngine] 数据已保存到 {self._persist_path}")
            return True
        except Exception as e:
            logger.error(f"[AnalyticsEngine] 保存失败: {e}")
            return False

    def _load_from_disk(self) -> bool:
        """启动时从磁盘恢复数据"""
        if not os.path.exists(self._persist_path):
            return False
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._deserialize(data)
            logger.info(f"[AnalyticsEngine] 从磁盘恢复: {self._persist_path}")
            return True
        except Exception as e:
            logger.warning(f"[AnalyticsEngine] 恢复失败: {e}")
            return False

    def _serialize(self) -> dict:
        """序列化当前状态"""
        return {
            "version": 1,
            "saved_at": time.time(),
            "counters": {
                "projects_created": self._projects_created,
                "projects_completed": self._projects_completed,
                "total_video_seconds": self._total_video_seconds,
                "llm_calls": self._llm_calls,
                "llm_tokens": self._llm_tokens,
                "tts_chars": self._tts_chars,
                "errors": self._errors,
            },
            "render_times": self._render_times[-200:],  # 只保留最近200条
            "llm_by_provider": {
                p: dict(stats)
                for p, stats in self._llm_by_provider.items()
            },
            "duration_buckets": dict(self._duration_buckets),
            "time_series": [
                {
                    "timestamp": p.timestamp,
                    "projects_created": p.projects_created,
                    "projects_completed": p.projects_completed,
                    "total_video_seconds": p.total_video_seconds,
                    "avg_render_time": p.avg_render_time,
                    "render_count": p.render_count,
                    "llm_calls": p.llm_calls,
                    "llm_tokens": p.llm_tokens,
                    "errors": p.errors,
                    "tts_chars": p.tts_chars,
                }
                for p in self._time_series
            ],
            "error_details": self._error_details[-50:],
        }

    def _deserialize(self, data: dict):
        """从序列化数据恢复"""
        counters = data.get("counters", {})
        self._projects_created = counters.get("projects_created", 0)
        self._projects_completed = counters.get("projects_completed", 0)
        self._total_video_seconds = counters.get("total_video_seconds", 0.0)
        self._llm_calls = counters.get("llm_calls", 0)
        self._llm_tokens = counters.get("llm_tokens", 0)
        self._tts_chars = counters.get("tts_chars", 0)
        self._errors = counters.get("errors", 0)

        self._render_times = data.get("render_times", [])

        prov_data = data.get("llm_by_provider", {})
        self._llm_by_provider = defaultdict(
            lambda: {"calls": 0, "tokens": 0},
            {p: {"calls": s.get("calls", 0), "tokens": s.get("tokens", 0)}
             for p, s in prov_data.items()}
        )

        bucket_data = data.get("duration_buckets", {})
        self._duration_buckets = defaultdict(int, bucket_data)

        # 恢复时间序列
        self._time_series.clear()
        for item in data.get("time_series", []):
            p = TimeSeriesPoint(
                timestamp=item.get("timestamp", 0),
                projects_created=item.get("projects_created", 0),
                projects_completed=item.get("projects_completed", 0),
                total_video_seconds=item.get("total_video_seconds", 0.0),
                avg_render_time=item.get("avg_render_time", 0.0),
                render_count=item.get("render_count", 0),
                llm_calls=item.get("llm_calls", 0),
                llm_tokens=item.get("llm_tokens", 0),
                errors=item.get("errors", 0),
                tts_chars=item.get("tts_chars", 0),
            )
            self._time_series.append(p)

        self._error_details = data.get("error_details", [])

    # ── 后台自动保存 ───────────────────────────────────────────

    def _start_auto_save(self):
        """启动后台自动保存线程"""
        if self._save_thread is not None:
            return

        def _auto_save_loop():
            logger.debug("[AnalyticsEngine] 自动保存线程启动")
            while not self._stop_save.wait(AUTO_SAVE_INTERVAL_SEC):
                # 每 5 分钟检查一次是否需要保存
                if time.time() - self._last_save_time >= AUTO_SAVE_INTERVAL_SEC:
                    self.save_to_disk()
            logger.debug("[AnalyticsEngine] 自动保存线程退出")

        self._save_thread = threading.Thread(
            target=_auto_save_loop, daemon=True, name="analytics-autosave"
        )
        self._save_thread.start()

    def shutdown(self):
        """优雅关闭：停止自动保存 + 最终持久化"""
        logger.info("[AnalyticsEngine] 正在关闭...")
        self._stop_save.set()
        if self._save_thread is not None:
            self._save_thread.join(timeout=5)
        self.save_to_disk()
        logger.info("[AnalyticsEngine] 已关闭")

    # ── 内部工具 ──────────────────────────────────────────────

    def _find_duration_bucket(self, duration_sec: float) -> str:
        """将时长归入对应桶"""
        for edge in self._duration_bucket_edges:
            if duration_sec <= edge:
                return f"0-{edge}s"
        return f"{self._duration_bucket_edges[-1]}+s"

    def _rotate_time_window(self):
        """轮换时间窗口（由外部定时调用，约每5分钟一次）"""
        with self._lock:
            if self._current_window.projects_created > 0 or self._current_window.errors > 0:
                # 计算 avg_render_time
                self._current_window.timestamp = time.time()
                self._time_series.append(self._current_window)
            self._current_window = TimeSeriesPoint()


# ═══════════ 便捷工厂 ═══════════

# 模块级全局实例
analytics_engine = AnalyticsEngine()


def get_analytics_engine() -> AnalyticsEngine:
    """获取全局 AnalyticsEngine 实例"""
    return analytics_engine
