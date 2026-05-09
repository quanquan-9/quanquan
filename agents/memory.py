"""
记忆引擎 — 分层记忆 + 冷启动 + 时间衰减 + 反馈演化
贯穿全流程的个性化引擎
"""
import math
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class MemoryEntry:
    key: str
    weight: float = 0.5
    category: str = "general"
    last_used: float = field(default_factory=time.time)
    total_uses: int = 0
    tags: List[str] = field(default_factory=list)


class MemoryEngine:
    """分层记忆引擎 — 短期/长期记忆 + 向量检索"""

    COLD_START_TEMPLATES = {
        "科技": {"voice_id": "neutral_male_01", "filter": "cyberpunk_purple",
                  "transition": "smooth_cut", "bgm_genre": "synthwave", "bpm": 120},
        "温暖": {"voice_id": "warm_female_01", "filter": "warm_sunset",
                  "transition": "fade", "bgm_genre": "acoustic", "bpm": 90},
        "激昂": {"voice_id": "deep_male_03", "filter": "cinematic_epic",
                  "transition": "glitch_dissolve", "bgm_genre": "epic_orchestral", "bpm": 140},
        "轻松": {"voice_id": "bright_female_01", "filter": "pastel_light",
                  "transition": "smooth_cut", "bgm_genre": "lofi_chill", "bpm": 85},
        "专业": {"voice_id": "neutral_male_02", "filter": "standard",
                  "transition": "smooth_cut", "bgm_genre": "corporate", "bpm": 110},
    }

    def __init__(self, decay_lambda: float = 0.0077):
        """
        decay_lambda: 衰减系数，默认使90天后权重降至50%
        e^(-0.0077*90) ≈ 0.5
        """
        self.decay_lambda = decay_lambda
        self.short_term: Dict[str, MemoryEntry] = {}   # 短期记忆（当前项目）
        self.long_term: Dict[str, MemoryEntry] = {}     # 长期记忆（跨项目）
        self.suppressed: set = set()                     # 被抑制的偏好

    # ═══════════ 对外接口 ═══════════

    def get_profile(self, user_id: str, intent_tags: List[str] = None) -> dict:
        """拉取用户画像，冷启动时用模板兜底"""
        profile = {"cold_start": True, "preferences": {}, "evolution_history": []}

        if not self.long_term:
            # 冷启动：关键词匹配默认模板
            for tag in (intent_tags or []):
                if tag in self.COLD_START_TEMPLATES:
                    profile["preferences"] = self.COLD_START_TEMPLATES[tag].copy()
                    profile["cold_start"] = True
                    return profile
            # 无匹配关键词 → 通用模板
            profile["preferences"] = self.COLD_START_TEMPLATES["专业"].copy()
            return profile

        profile["cold_start"] = False
        profile["preferences"] = self._build_preference_map()
        profile["evolution_history"] = [
            {"key": e.key, "weight": e.weight, "last_used": e.last_used}
            for e in sorted(self.long_term.values(), key=lambda x: -x.weight)[:10]
        ]
        return profile

    def ingest_project_signals(self, user_id: str, project_id: str,
                                adopted_configs: dict, user_feedback: list = None):
        """项目完成后写入记忆"""
        for category, key in adopted_configs.items():
            self._upsert(key, category=category, weight_boost=0.1)

        if user_feedback:
            for signal in user_feedback:
                self.on_user_feedback(signal)

    def on_user_feedback(self, signal: dict):
        """处理用户反馈信号，更新长期记忆"""
        signal_type = signal.get("type", "")
        strength = signal.get("strength", 0)

        if strength >= 0.3:  # 强正向 → 提升权重 + 重置衰减
            new_pref = signal.get("new_preference", {})
            if new_pref:
                key = new_pref.get("key", new_pref.get("voice_id", ""))
                if key:
                    self._boost(key, category=signal_type, boost=0.8)

        elif strength <= -0.4:  # 强负向 → 抑制
            old_key = signal.get("from", "")
            if old_key:
                self._suppress(old_key)

        elif -0.3 <= strength < 0:  # 弱负向 → 降低权重
            old_key = signal.get("from", "")
            if old_key:
                self._decay(old_key, factor=0.7)

        else:  # 弱正向 → 微升
            new_pref = signal.get("new_preference", {})
            if new_pref:
                key = new_pref.get("key", new_pref.get("voice_id", ""))
                if key:
                    self._boost(key, boost=0.15)

    # ═══════════ 内部方法 ═══════════

    def _upsert(self, key: str, category: str = "general", weight_boost: float = 0.05):
        """插入或更新记忆条目"""
        if key in self.suppressed:
            return
        entry = self.long_term.get(key)
        if not entry:
            entry = MemoryEntry(key=key, category=category, weight=0.5)
            self.long_term[key] = entry
        entry.weight = min(1.0, entry.weight + weight_boost)
        entry.last_used = time.time()
        entry.total_uses += 1

    def _boost(self, key: str, category: str = "general", boost: float = 0.2):
        """提升偏好权重并重置衰减时钟"""
        if key in self.suppressed:
            self.suppressed.discard(key)
        entry = self.long_term.get(key)
        if not entry:
            entry = MemoryEntry(key=key, category=category, weight=0.5)
            self.long_term[key] = entry
        entry.weight = min(1.0, entry.weight + boost)
        entry.last_used = time.time()
        entry.total_uses += 1

    def _suppress(self, key: str):
        """抑制：权重接近0但不删除，避免冷启动"""
        if key in self.long_term:
            self.long_term[key].weight = 0.01
        self.suppressed.add(key)

    def _decay(self, key: str, factor: float = 0.7):
        """衰减权重"""
        if key in self.long_term:
            self.long_term[key].weight *= factor

    def _build_preference_map(self) -> dict:
        """构建偏好推荐映射 — 应用时间衰减"""
        now = time.time()
        prefs = {}
        for entry in self.long_term.values():
            if entry.key in self.suppressed:
                continue
            # 时间衰减: weight *= e^(-λ * Δt)
            days_elapsed = (now - entry.last_used) / 86400
            decayed_weight = entry.weight * math.exp(-self.decay_lambda * days_elapsed)
            if decayed_weight < 0.05:
                continue

            prefs[entry.key] = {
                "weight": round(decayed_weight, 3),
                "category": entry.category,
                "last_used_days_ago": round(days_elapsed, 1),
            }
        return prefs

    def get_top(self, category: str = None, limit: int = 3) -> List[dict]:
        """获取指定类别的 Top-N 偏好"""
        candidates = []
        for key, data in self._build_preference_map().items():
            if category and data.get("category") != category:
                continue
            candidates.append({"key": key, **data})
        candidates.sort(key=lambda x: -x["weight"])
        return candidates[:limit]


memory_engine = MemoryEngine()
