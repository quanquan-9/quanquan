"""
用量统计与配额管理 (Usage & Quota)

功能：
- 用户用量追踪
- 配额限制
- 用量报表
- 成本估算
"""

import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)


class QuotaType(Enum):
    PROJECTS_PER_DAY = "projects_per_day"
    VIDEO_DURATION_PER_DAY = "video_duration_per_day"  # seconds
    STORAGE_MB = "storage_mb"
    EXPORTS_PER_DAY = "exports_per_day"
    GPU_MINUTES_PER_DAY = "gpu_minutes_per_day"
    LLM_TOKENS_PER_DAY = "llm_tokens_per_day"
    TTS_CHARS_PER_DAY = "tts_chars_per_day"


QUOTA_TIERS = {
    "free": {
        QuotaType.PROJECTS_PER_DAY: 3,
        QuotaType.VIDEO_DURATION_PER_DAY: 600,      # 10 min
        QuotaType.STORAGE_MB: 500,
        QuotaType.EXPORTS_PER_DAY: 2,
        QuotaType.GPU_MINUTES_PER_DAY: 0,
        QuotaType.LLM_TOKENS_PER_DAY: 10000,
        QuotaType.TTS_CHARS_PER_DAY: 5000,
    },
    "premium": {
        QuotaType.PROJECTS_PER_DAY: 20,
        QuotaType.VIDEO_DURATION_PER_DAY: 7200,     # 2 hours
        QuotaType.STORAGE_MB: 5000,
        QuotaType.EXPORTS_PER_DAY: 10,
        QuotaType.GPU_MINUTES_PER_DAY: 60,
        QuotaType.LLM_TOKENS_PER_DAY: 100000,
        QuotaType.TTS_CHARS_PER_DAY: 50000,
    },
    "enterprise": {
        QuotaType.PROJECTS_PER_DAY: 100,
        QuotaType.VIDEO_DURATION_PER_DAY: 86400,    # 24 hours
        QuotaType.STORAGE_MB: 50000,
        QuotaType.EXPORTS_PER_DAY: 50,
        QuotaType.GPU_MINUTES_PER_DAY: 600,
        QuotaType.LLM_TOKENS_PER_DAY: 1000000,
        QuotaType.TTS_CHARS_PER_DAY: 500000,
    },
}


@dataclass
class UsageRecord:
    """用量记录"""
    user_id: str
    quota_type: QuotaType
    amount: float
    timestamp: float = field(default_factory=time.time)
    project_id: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class UsageTracker:
    """用量追踪器"""

    def __init__(self):
        self._records: Dict[str, Dict[QuotaType, List[float]]] = defaultdict(
            lambda: defaultdict(list))
        self._totals: Dict[str, Dict[QuotaType, float]] = defaultdict(
            lambda: defaultdict(float))

    def record(self, user_id: str, quota_type: QuotaType, amount: float,
               project_id: str = "", details: Dict = None):
        """记录用量"""
        now = time.time()
        self._records[user_id][quota_type].append(now)
        self._totals[user_id][quota_type] += amount

        record = UsageRecord(
            user_id=user_id, quota_type=quota_type, amount=amount,
            timestamp=now, project_id=project_id, details=details or {},
        )

        logger.debug(f"Usage: {user_id} {quota_type.value}={amount}")

    def get_daily_usage(
        self, user_id: str, quota_type: QuotaType
    ) -> float:
        """获取今日用量"""
        now = time.time()
        cutoff = now - 86400
        timestamps = self._records.get(user_id, {}).get(quota_type, [])
        return len([t for t in timestamps if t > cutoff])

    def check_quota(
        self, user_id: str, quota_type: QuotaType, tier: str = "free"
    ) -> bool:
        """检查配额是否充足"""
        limit = QUOTA_TIERS.get(tier, QUOTA_TIERS["free"]).get(quota_type, 0)
        if limit == 0:
            return False if quota_type == QuotaType.GPU_MINUTES_PER_DAY else True

        used = self.get_daily_usage(user_id, quota_type)
        return used < limit

    def remaining(self, user_id: str, tier: str = "free") -> Dict[str, float]:
        """获取所有剩余配额"""
        limits = QUOTA_TIERS.get(tier, QUOTA_TIERS["free"])
        return {
            qt.value: max(0, limits[qt] - self.get_daily_usage(user_id, qt))
            for qt in QuotaType
        }

    def get_stats(self, user_id: str) -> dict:
        """获取用量统计"""
        return {
            "daily": {
                qt.value: self.get_daily_usage(user_id, qt)
                for qt in QuotaType
            },
            "total": {
                qt.value: self._totals.get(user_id, {}).get(qt, 0)
                for qt in QuotaType
            },
        }

    def estimate_cost(
        self, user_id: str,
        rate_llm_per_1k_tokens: float = 0.002,
        rate_tts_per_1k_chars: float = 0.015,
        rate_gpu_per_minute: float = 0.05,
    ) -> float:
        """估算成本"""
        totals = self._totals.get(user_id, {})
        cost = 0
        cost += totals.get(QuotaType.LLM_TOKENS_PER_DAY, 0) / 1000 * rate_llm_per_1k_tokens
        cost += totals.get(QuotaType.TTS_CHARS_PER_DAY, 0) / 1000 * rate_tts_per_1k_chars
        cost += totals.get(QuotaType.GPU_MINUTES_PER_DAY, 0) * rate_gpu_per_minute
        return round(cost, 4)


# 全局实例
usage_tracker = UsageTracker()
