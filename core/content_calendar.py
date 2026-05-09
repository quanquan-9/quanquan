"""
内容日历与排期系统 (Content Calendar & Scheduler)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
统一管理多平台视频发布排期，支持日/周/月视图、冲突检测、
最佳发布时间建议和 iCal 导出。

功能：
- schedule_publish: 按日期/平台/项目排期发布
- get_week_plan: 获取7天发布计划
- get_month_overview: 月度发布日历网格
- check_conflicts: 检测排期冲突（同日同平台多发布）
- get_best_time: 基于平台数据的黄金发布时间建议
- iCal 导出: 导出为标准 iCalendar 格式文件
- JSON 文件持久化存储

使用示例：
    calendar = ContentCalendar()
    
    # 排期发布
    calendar.schedule_publish(
        date="2025-06-15",
        platform="bilibili",
        project_id="proj_001",
        time="18:00",
    )
    
    # 获取周计划
    week = calendar.get_week_plan(start_date="2025-06-09")
    # → {"周一": [event, ...], "周二": [...], ...}
    
    # 检查冲突
    conflicts = calendar.check_conflicts("2025-06-15")
    # → [{"platform": "bilibili", "existing": [...], "severity": "warning"}, ...]
    
    # 最佳时间
    best = calendar.get_best_time("bilibili")
    # → {"hour": 18, "day_of_week": 5, "reason": "周五晚18点 B站用户活跃高峰"}

平台黄金时间数据：
- B站: 周五/周六 18:00-21:00，工作日 12:00-13:00 / 18:00-20:00
- 抖音: 每天 12:00-13:00 / 18:00-19:00 / 21:00-22:00
- YouTube: 周四/周五 15:00-18:00 EST (对应北京时间周五/周六凌晨)
- 小红书: 每天 12:00-13:00 / 20:00-22:00，周末早10:00
"""

import os
import json
import logging
import time
import uuid
import threading
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger("quanquan.content_calendar")


# ═══════════ 数据模型 ═══════════

class CalendarPlatform(Enum):
    """支持的平台枚举"""
    BILIBILI = "bilibili"
    DOUYIN = "douyin"
    YOUTUBE = "youtube"
    XIAOHONGSHU = "xiaohongshu"
    KUAISHOU = "kuaishou"
    WEIBO = "weibo"
    WECHAT = "wechat"


PLATFORM_DISPLAY = {
    "bilibili": "B站",
    "douyin": "抖音",
    "youtube": "YouTube",
    "xiaohongshu": "小红书",
    "kuaishou": "快手",
    "weibo": "微博",
    "wechat": "视频号",
}


class EventStatus(Enum):
    """排期事件状态"""
    DRAFT = "draft"               # 草稿
    SCHEDULED = "scheduled"       # 已排期
    PUBLISHING = "publishing"     # 发布中
    PUBLISHED = "published"       # 已发布
    CANCELLED = "cancelled"       # 已取消
    RESCHEDULED = "rescheduled"   # 已改期


class ConflictSeverity(Enum):
    """冲突严重程度"""
    INFO = "info"           # 建议性提示
    WARNING = "warning"     # 轻度冲突（同日多平台）
    CRITICAL = "critical"   # 严重冲突（同日同平台多发布）


@dataclass
class CalendarEvent:
    """日历排期事件"""
    event_id: str                               # 唯一事件ID
    project_id: str                             # 关联项目ID
    platform: str                               # 目标平台
    date: str                                   # 发布日期 "YYYY-MM-DD"
    time: str = "18:00"                         # 发布时间 "HH:MM"
    title: str = ""                             # 视频标题
    status: str = "scheduled"                   # 事件状态
    notes: str = ""                             # 备注
    tags: List[str] = field(default_factory=list)  # 标签
    created_at: str = ""                        # 创建时间 ISO
    updated_at: str = ""                        # 更新时间 ISO
    recurrence: Optional[str] = None            # 重复规则 (daily/weekly/monthly)


@dataclass
class BestTimeResult:
    """最佳发布时间建议"""
    platform: str                               # 平台
    hour: int                                   # 建议小时 (0-23)
    day_of_week: int = 0                        # 建议星期几 (0=周一, 6=周日)
    score: float = 0.0                          # 推荐度 0~1
    reason: str = ""                            # 推荐理由
    alternative_hours: List[int] = field(default_factory=list)  # 备选时间


@dataclass
class ConflictResult:
    """冲突检测结果"""
    date: str                                   # 检测日期
    platform: str                               # 冲突平台
    severity: str                               # info / warning / critical
    existing_events: List[CalendarEvent] = field(default_factory=list)
    message: str = ""                           # 冲突说明


@dataclass
class MonthGrid:
    """月度日历网格"""
    year: int
    month: int
    days: List[dict] = field(default_factory=list)  # 每天的事件列表
    total_events: int = 0
    platform_breakdown: Dict[str, int] = field(default_factory=dict)
    busiest_day: Optional[str] = None
    busiest_count: int = 0


# ═══════════ 平台黄金时间数据 ═══════════

# 基于公开研究和经验总结的平台最佳发布时间
# 格式: (day_of_week_bitmask, [(hour, score), ...], reason)
# day_of_week_bitmask: bit0=周一 ... bit6=周日
PLATFORM_BEST_TIMES = {
    "bilibili": {
        "primary": {"day": 4, "hour": 18},  # 周五18点 — B站用户最活跃时段
        "weekday_hours": [
            (12, 0.75), (13, 0.60), (18, 0.90), (19, 0.85), (20, 0.80),
        ],
        "weekend_hours": [
            (10, 0.70), (12, 0.75), (14, 0.70), (18, 0.95), (19, 0.90), (20, 0.88), (21, 0.80),
        ],
        "best_days": [4, 5],  # 周五、周六
        "reason": "B站用户活跃高峰在周五/周六晚间18:00-21:00，工作日午休12:00也有小高峰",
    },
    "douyin": {
        "primary": {"day": 4, "hour": 19},
        "weekday_hours": [
            (12, 0.80), (13, 0.70), (18, 0.85), (19, 0.90), (21, 0.85), (22, 0.70),
        ],
        "weekend_hours": [
            (10, 0.75), (12, 0.85), (18, 0.88), (19, 0.92), (20, 0.85), (21, 0.90), (22, 0.80),
        ],
        "best_days": [4, 5, 6],  # 周五/六/日
        "reason": "抖音用户活跃时段分散，黄金窗口：午休12:00、下班18:00-19:00、睡前21:00-22:00",
    },
    "youtube": {
        "primary": {"day": 3, "hour": 15},  # 周四15:00 EST ≈ 北京时间周五04:00
        "weekday_hours": [
            (12, 0.65), (14, 0.70), (15, 0.80), (16, 0.78), (17, 0.75), (18, 0.72),
        ],
        "weekend_hours": [
            (9, 0.70), (10, 0.78), (11, 0.82), (12, 0.80), (13, 0.75), (14, 0.70),
        ],
        "best_days": [3, 4],  # 周四、周五 (EST)
        "reason": "YouTube 北美用户为主，最佳发布为当地时间周四/周五 15:00-18:00 EST。"
                  "国内创作者建议周五/周六上午发布以覆盖周末流量",
    },
    "xiaohongshu": {
        "primary": {"day": 4, "hour": 20},
        "weekday_hours": [
            (12, 0.80), (13, 0.70), (20, 0.90), (21, 0.88), (22, 0.75),
        ],
        "weekend_hours": [
            (10, 0.80), (12, 0.78), (14, 0.72), (20, 0.92), (21, 0.90), (22, 0.82),
        ],
        "best_days": [4, 5, 6],
        "reason": "小红书女性用户为主，晚间20:00-22:00是最高活跃时段，周末早10:00也有浏览高峰",
    },
    "kuaishou": {
        "primary": {"day": 5, "hour": 19},
        "weekday_hours": [
            (12, 0.70), (18, 0.78), (19, 0.85), (20, 0.82), (21, 0.75),
        ],
        "weekend_hours": [
            (10, 0.72), (12, 0.75), (18, 0.85), (19, 0.90), (20, 0.88), (21, 0.82),
        ],
        "best_days": [5, 6],
        "reason": "快手用户下沉明显，晚间19:00-21:00为黄金时段，周末全天活跃度较高",
    },
    "weibo": {
        "primary": {"day": 3, "hour": 20},
        "weekday_hours": [
            (12, 0.72), (18, 0.78), (20, 0.85), (21, 0.88), (22, 0.80),
        ],
        "weekend_hours": [
            (10, 0.75), (12, 0.78), (20, 0.82), (21, 0.85), (22, 0.80),
        ],
        "best_days": [3, 4, 5],
        "reason": "微博用户活跃在周三至周五晚间，话题热度最高的时段为20:00-22:00",
    },
    "wechat": {
        "primary": {"day": 4, "hour": 19},
        "weekday_hours": [
            (12, 0.70), (18, 0.75), (19, 0.82), (20, 0.80), (21, 0.72),
        ],
        "weekend_hours": [
            (10, 0.72), (12, 0.70), (19, 0.78), (20, 0.80), (21, 0.75),
        ],
        "best_days": [4, 5],
        "reason": "视频号用户群与微信生态重合，周五晚19:00-20:00为最佳发布窗口",
    },
}


# ═══════════ ContentCalendar ═══════════

class ContentCalendar:
    """内容日历与排期管理器

    支持多平台排期管理、冲突检测、最佳时间建议和 iCal 导出。
    数据存于内存，自动 JSON 持久化到磁盘。

    工作流程：
    1. 初始化时从存储文件加载历史数据
    2. 所有增删改操作同时更新内存和磁盘
    3. 查询操作（周/月视图）从内存即时计算
    """

    def __init__(self, storage_path: Optional[str] = None):
        """初始化内容日历

        Args:
            storage_path: JSON 存储文件路径，不传则默认保存到 core/ 同级 data/ 目录
        """
        if storage_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            data_dir = os.path.join(os.path.dirname(base_dir), "data")
            os.makedirs(data_dir, exist_ok=True)
            storage_path = os.path.join(data_dir, "content_calendar.json")

        self._storage_path = storage_path
        self._events: Dict[str, CalendarEvent] = {}  # event_id -> CalendarEvent
        self._lock = threading.RLock()

        # 加载已有数据
        self._load()
        logger.info(f"[ContentCalendar] 初始化完成，已加载 {len(self._events)} 个排期事件")

    # ── 公共 API ──────────────────────────────────────────────

    def schedule_publish(
        self,
        date: str,
        platform: str,
        project_id: str,
        time: str = "18:00",
        title: str = "",
        notes: str = "",
        tags: Optional[List[str]] = None,
        recurrence: Optional[str] = None,
    ) -> CalendarEvent:
        """排期一个发布事件

        Args:
            date: 发布日期，格式 "YYYY-MM-DD"
            platform: 目标平台 (bilibili/douyin/youtube/xiaohongshu/...)
            project_id: 关联项目ID
            time: 发布时间，格式 "HH:MM"，默认 18:00
            title: 视频标题（可选）
            notes: 备注（可选）
            tags: 标签列表（可选）
            recurrence: 重复规则，如 'weekly'/'monthly'（可选）

        Returns:
            创建的 CalendarEvent 对象

        Raises:
            ValueError: 参数格式错误
        """
        # 参数校验
        self._validate_date(date)
        self._validate_time(time)
        if platform not in PLATFORM_DISPLAY:
            logger.warning(f"[ContentCalendar] 未知平台: {platform}，允许但建议使用已知平台")

        event_id = f"cal_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        event = CalendarEvent(
            event_id=event_id,
            project_id=project_id,
            platform=platform,
            date=date,
            time=time,
            title=title,
            status=EventStatus.SCHEDULED.value,
            notes=notes,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            recurrence=recurrence,
        )

        with self._lock:
            self._events[event_id] = event
            self._save()

        # 自动冲突检测
        conflicts = self.check_conflicts(date)
        if conflicts:
            conflict_msgs = "; ".join(
                f"{c.platform}: {c.message}" for c in conflicts
            )
            logger.warning(f"[ContentCalendar] 排期冲突检测: {conflict_msgs}")

        logger.info(
            f"[ContentCalendar] 已排期: {platform} @ {date} {time} "
            f"(event={event_id}, project={project_id})"
        )
        return event

    def get_week_plan(self, start_date: Optional[str] = None) -> Dict[str, List[CalendarEvent]]:
        """获取7天发布计划

        Args:
            start_date: 起始日期 "YYYY-MM-DD"，不传则从今天开始

        Returns:
            {"周一": [event, ...], "周二": [...], ...} 包含7天的排期
        """
        if start_date is None:
            start = date.today()
        else:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()

        weekdays_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        plan: Dict[str, List[CalendarEvent]] = {d: [] for d in weekdays_cn}

        with self._lock:
            for event in self._events.values():
                if event.status in (EventStatus.CANCELLED.value,):
                    continue
                try:
                    evt_date = datetime.strptime(event.date, "%Y-%m-%d").date()
                except ValueError:
                    continue

                delta = (evt_date - start).days
                if 0 <= delta < 7:
                    day_name = weekdays_cn[evt_date.weekday()]
                    plan[day_name].append(event)

        # 每天内部按时间排序
        for day_events in plan.values():
            day_events.sort(key=lambda e: e.time)

        logger.info(
            f"[ContentCalendar] 周计划 ({start} ~ {start + timedelta(days=6)})："
            f"{sum(len(v) for v in plan.values())} 个排期"
        )
        return plan

    def get_month_overview(self, year: Optional[int] = None, month: Optional[int] = None) -> MonthGrid:
        """获取月度发布日历概览

        Args:
            year: 年份，不传则用当前年
            month: 月份 (1-12)，不传则用当前月

        Returns:
            MonthGrid: 包含每天事件列表、平台分布、最忙日期等
        """
        today = date.today()
        year = year or today.year
        month = month or today.month

        # 计算当月天数
        import calendar as cal_mod
        days_in_month = cal_mod.monthrange(year, month)[1]

        month_start = date(year, month, 1)
        month_end = date(year, month, days_in_month)

        # 初始化每天的空列表
        days: List[dict] = []
        for d in range(1, days_in_month + 1):
            days.append({
                "date": f"{year}-{month:02d}-{d:02d}",
                "day_of_week": date(year, month, d).weekday(),
                "events": [],
                "count": 0,
            })

        platform_counts: Dict[str, int] = {}
        busiest_day = None
        busiest_count = 0
        total_events = 0

        with self._lock:
            for event in self._events.values():
                if event.status in (EventStatus.CANCELLED.value,):
                    continue
                try:
                    evt_date = datetime.strptime(event.date, "%Y-%m-%d").date()
                except ValueError:
                    continue

                if month_start <= evt_date <= month_end:
                    day_idx = evt_date.day - 1
                    days[day_idx]["events"].append(event)
                    days[day_idx]["count"] += 1

                    # 平台计数
                    platform_counts[event.platform] = platform_counts.get(event.platform, 0) + 1
                    total_events += 1

                    if days[day_idx]["count"] > busiest_count:
                        busiest_count = days[day_idx]["count"]
                        busiest_day = days[day_idx]["date"]

        # 每天按时间排序
        for day_data in days:
            day_data["events"].sort(key=lambda e: e.time)

        grid = MonthGrid(
            year=year,
            month=month,
            days=days,
            total_events=total_events,
            platform_breakdown=platform_counts,
            busiest_day=busiest_day,
            busiest_count=busiest_count,
        )

        logger.info(
            f"[ContentCalendar] 月概览 {year}/{month:02d}："
            f"{total_events} 个排期，最忙日 {busiest_day} ({busiest_count}个)"
        )
        return grid

    def check_conflicts(self, date: str) -> List[ConflictResult]:
        """检测指定日期的排期冲突

        规则：
        - 同日同平台 >= 2个发布 → CRITICAL 严重冲突
        - 同日 >= 3个不同平台发布 → WARNING 轻度冲突
        - 同日 >= 2个不同平台发布 → INFO 建议性提示

        Args:
            date: 日期 "YYYY-MM-DD"

        Returns:
            ConflictResult 列表，按严重程度排序
        """
        try:
            check_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"日期格式错误: {date}，需要 YYYY-MM-DD")

        conflicts: List[ConflictResult] = []
        day_events: List[CalendarEvent] = []

        with self._lock:
            for event in self._events.values():
                if event.status in (EventStatus.CANCELLED.value,):
                    continue
                if event.date == date:
                    day_events.append(event)

        if not day_events:
            logger.debug(f"[ContentCalendar] {date} 无排期冲突")
            return []

        # 按平台分组
        platform_groups: Dict[str, List[CalendarEvent]] = {}
        for evt in day_events:
            platform_groups.setdefault(evt.platform, []).append(evt)

        # 检查同平台多发布 → CRITICAL
        for plat, evts in platform_groups.items():
            if len(evts) >= 2:
                conflicts.append(ConflictResult(
                    date=date,
                    platform=plat,
                    severity=ConflictSeverity.CRITICAL.value,
                    existing_events=evts,
                    message=(
                        f"⚠️ 严重冲突：同日同平台({PLATFORM_DISPLAY.get(plat, plat)}) "
                        f"有 {len(evts)} 个发布 ({', '.join(e.time for e in evts)})"
                    ),
                ))

        # 检查同日多平台发布
        unique_platforms = len(platform_groups)
        if unique_platforms >= 3:
            conflicts.append(ConflictResult(
                date=date,
                platform="*",
                severity=ConflictSeverity.WARNING.value,
                existing_events=day_events,
                message=f"⚡ 轻度冲突：同日发布至 {unique_platforms} 个不同平台，建议分散发布",
            ))
        elif unique_platforms >= 2:
            conflicts.append(ConflictResult(
                date=date,
                platform="*",
                severity=ConflictSeverity.INFO.value,
                existing_events=day_events,
                message=f"📌 同日发布至 {unique_platforms} 个平台",
            ))

        # 按严重度排序
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        conflicts.sort(key=lambda c: severity_order.get(c.severity, 99))

        if conflicts:
            logger.info(f"[ContentCalendar] {date} 检测到 {len(conflicts)} 个冲突")
        return conflicts

    def get_best_time(self, platform: str) -> BestTimeResult:
        """获取平台最佳发布时间建议

        Args:
            platform: 目标平台 (bilibili/douyin/youtube/...)

        Returns:
            BestTimeResult: 包含建议小时、最佳星期、理由等
        """
        pt_data = PLATFORM_BEST_TIMES.get(platform)
        if not pt_data:
            # 通用建议
            logger.warning(f"[ContentCalendar] 未知平台 {platform}，使用通用建议")
            return BestTimeResult(
                platform=platform,
                hour=19,
                day_of_week=4,
                score=0.5,
                reason="通用建议：傍晚19:00是多数平台活跃时段，周五发布可获得周末流量",
                alternative_hours=[12, 18, 20, 21],
            )

        primary = pt_data["primary"]
        best_hours = pt_data["weekday_hours"]
        # 取评分最高的3个备选
        all_hours = sorted(best_hours, key=lambda x: x[1], reverse=True)
        alternatives = [h for h, _ in all_hours[:4] if h != primary["hour"]]

        result = BestTimeResult(
            platform=platform,
            hour=primary["hour"],
            day_of_week=primary["day"],
            score=0.95,
            reason=pt_data["reason"],
            alternative_hours=alternatives[:3],
        )

        day_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        logger.info(
            f"[ContentCalendar] {PLATFORM_DISPLAY.get(platform, platform)} 最佳时间: "
            f"{day_cn[primary['day']]} {primary['hour']}:00"
        )
        return result

    def get_event(self, event_id: str) -> Optional[CalendarEvent]:
        """获取单个排期事件

        Args:
            event_id: 事件ID

        Returns:
            CalendarEvent 或 None
        """
        with self._lock:
            return self._events.get(event_id)

    def cancel_event(self, event_id: str) -> bool:
        """取消排期事件

        Args:
            event_id: 事件ID

        Returns:
            是否成功取消
        """
        with self._lock:
            event = self._events.get(event_id)
            if not event:
                logger.warning(f"[ContentCalendar] 事件不存在: {event_id}")
                return False

            event.status = EventStatus.CANCELLED.value
            event.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()

        logger.info(f"[ContentCalendar] 已取消: {event_id}")
        return True

    def update_event(
        self,
        event_id: str,
        date: Optional[str] = None,
        time: Optional[str] = None,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Optional[CalendarEvent]:
        """更新排期事件

        Args:
            event_id: 事件ID
            date: 新日期 (可选)
            time: 新时间 (可选)
            title: 新标题 (可选)
            notes: 新备注 (可选)
            status: 新状态 (可选)

        Returns:
            更新后的 CalendarEvent 或 None
        """
        with self._lock:
            event = self._events.get(event_id)
            if not event:
                logger.warning(f"[ContentCalendar] 事件不存在: {event_id}")
                return None

            if date is not None:
                self._validate_date(date)
                event.date = date
            if time is not None:
                self._validate_time(time)
                event.time = time
            if title is not None:
                event.title = title
            if notes is not None:
                event.notes = notes
            if status is not None:
                event.status = status

            event.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()

        logger.info(f"[ContentCalendar] 已更新事件: {event_id}")
        return event

    def get_all_events(
        self,
        platform: Optional[str] = None,
        status: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[CalendarEvent]:
        """获取所有排期事件（支持筛选）

        Args:
            platform: 按平台筛选 (可选)
            status: 按状态筛选 (可选)
            date_from: 起始日期 "YYYY-MM-DD" (可选)
            date_to: 截止日期 "YYYY-MM-DD" (可选)

        Returns:
            符合条件的 CalendarEvent 列表
        """
        from_dt = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else None
        to_dt = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else None

        results = []
        with self._lock:
            for event in self._events.values():
                if platform and event.platform != platform:
                    continue
                if status and event.status != status:
                    continue
                if from_dt or to_dt:
                    try:
                        evt_date = datetime.strptime(event.date, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if from_dt and evt_date < from_dt:
                        continue
                    if to_dt and evt_date > to_dt:
                        continue
                results.append(event)

        results.sort(key=lambda e: (e.date, e.time))
        return results

    def clear_all(self):
        """清空所有排期（危险操作）"""
        with self._lock:
            count = len(self._events)
            self._events.clear()
            self._save()
        logger.warning(f"[ContentCalendar] 已清空 {count} 个排期事件")

    # ── iCal 导出 ─────────────────────────────────────────────

    def export_ical(
        self,
        output_path: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> str:
        """导出为 iCalendar (.ics) 格式文件

        Args:
            output_path: 输出文件路径，不传则返回字符串
            date_from: 筛选起始日期 (可选)
            date_to: 筛选截止日期 (可选)

        Returns:
            若 output_path 为 None，返回 iCal 字符串；否则返回文件路径
        """
        events = self.get_all_events(date_from=date_from, date_to=date_to)

        # 构建 iCal 内容
        dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//quanquan//Content Calendar//CN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:圈圈内容日历",
            f"X-WR-CALDESC:圈圈多平台视频发布排期",
            f"X-WR-TIMEZONE:Asia/Shanghai",
        ]

        for evt in events:
            if evt.status == EventStatus.CANCELLED.value:
                continue

            # 转为 iCal 日期格式
            date_str = evt.date.replace("-", "")
            time_str = evt.time.replace(":", "") + "00"
            dt_start = f"{date_str}T{time_str}"

            # 转义特殊字符
            summary = self._ical_escape(evt.title or f"{PLATFORM_DISPLAY.get(evt.platform, evt.platform)} 发布")
            description = self._ical_escape(
                f"平台: {PLATFORM_DISPLAY.get(evt.platform, evt.platform)}\\n"
                f"项目: {evt.project_id}\\n"
                f"状态: {evt.status}\\n"
                + (f"备注: {evt.notes}" if evt.notes else "")
            )

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{evt.event_id}@quanquan",
                f"DTSTART;TZID=Asia/Shanghai:{dt_start}",
                f"DTSTAMP:{dtstamp}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{description}",
                f"LOCATION:{PLATFORM_DISPLAY.get(evt.platform, evt.platform)}",
                f"CATEGORIES:{evt.platform}",
                "END:VEVENT",
            ])

        lines.append("END:VCALENDAR")
        ical_content = "\r\n".join(lines) + "\r\n"

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(ical_content)
            logger.info(f"[ContentCalendar] iCal 导出: {output_path} ({len(events)} 事件)")
            return output_path

        logger.info(f"[ContentCalendar] iCal 生成: {len(events)} 事件 (字符串)")
        return ical_content

    # ── 持久化 ──────────────────────────────────────────────

    def _save(self):
        """保存到 JSON 文件"""
        try:
            data = {
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "events": [
                    {
                        "event_id": e.event_id,
                        "project_id": e.project_id,
                        "platform": e.platform,
                        "date": e.date,
                        "time": e.time,
                        "title": e.title,
                        "status": e.status,
                        "notes": e.notes,
                        "tags": e.tags,
                        "created_at": e.created_at,
                        "updated_at": e.updated_at,
                        "recurrence": e.recurrence,
                    }
                    for e in self._events.values()
                ],
            }
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[ContentCalendar] 保存失败: {e}")

    def _load(self):
        """从 JSON 文件加载"""
        if not os.path.exists(self._storage_path):
            return

        try:
            with open(self._storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for evt_data in data.get("events", []):
                event = CalendarEvent(
                    event_id=evt_data.get("event_id", ""),
                    project_id=evt_data.get("project_id", ""),
                    platform=evt_data.get("platform", ""),
                    date=evt_data.get("date", ""),
                    time=evt_data.get("time", "18:00"),
                    title=evt_data.get("title", ""),
                    status=evt_data.get("status", "scheduled"),
                    notes=evt_data.get("notes", ""),
                    tags=evt_data.get("tags", []),
                    created_at=evt_data.get("created_at", ""),
                    updated_at=evt_data.get("updated_at", ""),
                    recurrence=evt_data.get("recurrence"),
                )
                if event.event_id:
                    self._events[event.event_id] = event

            logger.debug(f"[ContentCalendar] 从文件加载 {len(self._events)} 个事件")
        except Exception as e:
            logger.error(f"[ContentCalendar] 加载失败: {e}")

    # ── 验证方法 ──────────────────────────────────────────────

    @staticmethod
    def _validate_date(date_str: str):
        """验证日期格式"""
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"日期格式错误: {date_str}，需要 YYYY-MM-DD 格式")

    @staticmethod
    def _validate_time(time_str: str):
        """验证时间格式"""
        if not re.match(r'^\d{1,2}:\d{2}$', time_str):
            raise ValueError(f"时间格式错误: {time_str}，需要 HH:MM 格式")
        try:
            hour, minute = map(int, time_str.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError(f"时间范围错误: {time_str}")
        except ValueError as e:
            raise ValueError(f"时间格式错误: {time_str}，需要 HH:MM 格式") from e

    @staticmethod
    def _ical_escape(text: str) -> str:
        """转义 iCal 特殊字符"""
        return (text
                .replace("\\", "\\\\")
                .replace(";", "\\;")
                .replace(",", "\\,")
                .replace("\n", "\\n"))


# ── 便捷函数 ──────────────────────────────────────────────────

def get_week_plan_quick(start_date: Optional[str] = None) -> Dict[str, List[CalendarEvent]]:
    """快捷获取周计划（使用默认日历实例）"""
    calendar = ContentCalendar()
    return calendar.get_week_plan(start_date)


def get_best_time_quick(platform: str) -> BestTimeResult:
    """快捷获取最佳发布时间"""
    calendar = ContentCalendar()
    return calendar.get_best_time(platform)
