"""
偏好衰减引擎 (Preference Decay Engine)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
实现设计文档 §6 的完整规范：

功能：
- 时间衰减：weight *= e^(-λΔt)，λ 可配置（默认 90天后权重降至50%）
- 显式偏好提升：用户 "like" 行为提升权重并重置衰减时钟
- 纠错学习：连续3次手动修正同一偏好 → 自动提升新偏好、降低旧偏好
- 冷启动模板：基于首次输入关键词匹配大众化偏好
- 冲突处理：显式用户指令 > 历史记忆
- 演化历史：追踪偏好变化轨迹，支持 <=30天回滚

使用示例：
    engine = PreferenceDecayEngine()
    
    # 衰减检查（每个项目启动前调用）
    await engine.apply_decay("user_123")
    
    # 记录用户喜欢
    engine.like("user_123", "voice", preferences=["deep_male_03"])
    
    # 记录用户修正
    engine.correct("user_123", "voice", from_pref="neutral_male_01", to_pref="deep_male_03")
    
    # 查询当前有效偏好
    prefs = engine.get_active_preferences("user_123")  
    # → {"voice": [{"key": "deep_male_03", "weight": 0.91, ...}], ...}
    
    # 冷启动
    prefs = engine.cold_start("user_456", keywords=["科技", "专业"])
"""

import asyncio
import logging
import math
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger("quanquan.preference_decay")


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class PreferenceAnchor:
    """用户偏好锚点
    
    Attributes:
        key: 偏好值（如 "deep_male_03"）
        category: 偏好类别（voice / visual / bgm / transition / filter / subtitle / pace）
        weight: 当前权重 0~1
        created_at: 创建时间戳
        last_used_at: 最后使用时间戳
        last_liked_at: 最后点赞时间戳
        total_likes: 累计点赞次数
        total_corrections: 累计被修正次数（被用户替换的次数）
        source: 来源 (cold_start / explicit / inferred / learned)
        decay_clock: 衰减计时起点（Unix timestamp），每次 like 时重置
        metadata: 额外元数据
    """
    key: str
    category: str
    weight: float = 0.5
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    last_liked_at: Optional[float] = None
    total_likes: int = 0
    total_corrections: int = 0
    source: str = "explicit"      # cold_start / explicit / inferred / learned
    decay_clock: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "category": self.category,
            "weight": round(self.weight, 4),
            "created_at": datetime.fromtimestamp(self.created_at, tz=timezone.utc).isoformat(),
            "last_used_at": datetime.fromtimestamp(self.last_used_at, tz=timezone.utc).isoformat(),
            "last_liked_at": (
                datetime.fromtimestamp(self.last_liked_at, tz=timezone.utc).isoformat()
                if self.last_liked_at else None
            ),
            "total_likes": self.total_likes,
            "total_corrections": self.total_corrections,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass
class EvolutionEvent:
    """偏好演化事件
    
    记录偏好随时间的变化，用于可视化和审计。
    """
    timestamp: float
    category: str
    old_key: Optional[str]
    new_key: str
    trigger: str                # like / correct / decay / cold_start / explicit
    old_weight: float = 0.0
    new_weight: float = 0.0
    project_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ts": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "trigger": self.trigger,
            "category": self.category,
            "old": self.old_key or "(none)",
            "new": self.new_key,
            "w_old": round(self.old_weight, 4),
            "w_new": round(self.new_weight, 4),
            "project": self.project_id,
        }


# ═══════════════════════════════════════════════════════════════
# 冷启动模板（设计文档 §6.1）
# ═══════════════════════════════════════════════════════════════

COLD_START_TEMPLATES = {
    "科技": {
        "voice": [{"key": "professional_male_01", "weight": 0.7, "source": "cold_start"},
                   {"key": "neutral_female_01", "weight": 0.5, "source": "cold_start"}],
        "visual": [{"key": "modern_clean", "weight": 0.75, "source": "cold_start"}],
        "bgm": [{"key": "electronic_ambient", "weight": 0.6, "source": "cold_start"},
                 {"key": "synthwave", "weight": 0.5, "source": "cold_start"}],
        "transition": [{"key": "smooth_cut", "weight": 0.6, "source": "cold_start"}],
        "filter": [{"key": "neutral", "weight": 0.6, "source": "cold_start"}],
    },
    "旅行": {
        "voice": [{"key": "warm_female_01", "weight": 0.7, "source": "cold_start"}],
        "visual": [{"key": "bright_nature", "weight": 0.75, "source": "cold_start"}],
        "bgm": [{"key": "acoustic_folk", "weight": 0.65, "source": "cold_start"},
                 {"key": "world_music", "weight": 0.55, "source": "cold_start"}],
        "transition": [{"key": "fade_dissolve", "weight": 0.6, "source": "cold_start"}],
        "filter": [{"key": "warm_sunny", "weight": 0.65, "source": "cold_start"}],
    },
    "美食": {
        "voice": [{"key": "lively_female_01", "weight": 0.7, "source": "cold_start"}],
        "visual": [{"key": "saturated_appetite", "weight": 0.8, "source": "cold_start"}],
        "bgm": [{"key": "upbeat_pop", "weight": 0.6, "source": "cold_start"}],
        "transition": [{"key": "dynamic_wipe", "weight": 0.6, "source": "cold_start"}],
        "filter": [{"key": "warm_food", "weight": 0.7, "source": "cold_start"}],
    },
    "游戏": {
        "voice": [{"key": "energetic_male_01", "weight": 0.7, "source": "cold_start"}],
        "visual": [{"key": "gaming_vivid", "weight": 0.75, "source": "cold_start"}],
        "bgm": [{"key": "electronic_hype", "weight": 0.7, "source": "cold_start"},
                 {"key": "chiptune_retro", "weight": 0.55, "source": "cold_start"}],
        "transition": [{"key": "glitch_dissolve", "weight": 0.6, "source": "cold_start"}],
        "filter": [{"key": "cyberpunk_purple", "weight": 0.65, "source": "cold_start"}],
    },
    "教育": {
        "voice": [{"key": "clear_male_01", "weight": 0.7, "source": "cold_start"}],
        "visual": [{"key": "clean_academic", "weight": 0.7, "source": "cold_start"}],
        "bgm": [{"key": "minimal_piano", "weight": 0.6, "source": "cold_start"}],
        "transition": [{"key": "smooth_cut", "weight": 0.6, "source": "cold_start"}],
        "filter": [{"key": "neutral", "weight": 0.6, "source": "cold_start"}],
    },
    "日常": {
        "voice": [{"key": "natural_female_01", "weight": 0.65, "source": "cold_start"}],
        "visual": [{"key": "soft_natural", "weight": 0.65, "source": "cold_start"}],
        "bgm": [{"key": "lofi_chill", "weight": 0.65, "source": "cold_start"}],
        "transition": [{"key": "fade_dissolve", "weight": 0.6, "source": "cold_start"}],
        "filter": [{"key": "warm_soft", "weight": 0.6, "source": "cold_start"}],
    },
    "音乐": {
        "voice": [{"key": "musical_female_01", "weight": 0.65, "source": "cold_start"}],
        "visual": [{"key": "artistic_mood", "weight": 0.7, "source": "cold_start"}],
        "bgm": [{"key": "classical_piano", "weight": 0.6, "source": "cold_start"}],
        "transition": [{"key": "smooth_fade", "weight": 0.6, "source": "cold_start"}],
        "filter": [{"key": "vintage_warm", "weight": 0.6, "source": "cold_start"}],
    },
}

# 默认回退模板（无匹配关键词时）
DEFAULT_COLD_START = {
    "voice": [{"key": "neutral_male_01", "weight": 0.5, "source": "cold_start"}],
    "visual": [{"key": "standard", "weight": 0.5, "source": "cold_start"}],
    "bgm": [{"key": "generic_pop", "weight": 0.5, "source": "cold_start"}],
    "transition": [{"key": "smooth_cut", "weight": 0.5, "source": "cold_start"}],
    "filter": [{"key": "neutral", "weight": 0.5, "source": "cold_start"}],
}


# ═══════════════════════════════════════════════════════════════
# 偏好衰减引擎
# ═══════════════════════════════════════════════════════════════

class PreferenceDecayEngine:
    """偏好衰减引擎 — 实现设计文档 §6 完整规范

    核心机制：
    ┌──────────────────────────────────────────────────────┐
    │ 1. 时间衰减:  weight *= e^(-λ * Δt)                   │
    │ 2. 显式提升:  like → 权重 +0.15, 重置 decay_clock    │
    │ 3. 纠错学习:  3次修正 → 自动迁移偏好                  │
    │ 4. 冲突处理:  显式指令 > 衰减记忆                      │
    │ 5. 演化追踪:  记录所有变化，支持 <=30天回滚            │
    └──────────────────────────────────────────────────────┘
    """

    # 默认衰减常数 λ：使得 90 天后权重降至原有的 50%
    # weight = w0 * e^(-λ * 90*86400) → 0.5 = e^(-λ*7776000) → λ = ln(2)/7776000
    DEFAULT_LAMBDA = math.log(2) / (90 * 86400)   # ≈ 8.91e-8 per second

    # 半衰期：90 天
    DEFAULT_HALF_LIFE_DAYS = 90

    # 连续修正次数阈值 — 达到后自动迁移偏好
    CORRECTION_MIGRATION_THRESHOLD = 3

    # 权重提升量（每次 like）
    LIKE_BOOST = 0.15

    # 权重上限
    MAX_WEIGHT = 1.0

    # 权重下限（低于此值视为过期，可清理）
    MIN_WEIGHT = 0.05

    # 演化历史最大保留天数
    MAX_HISTORY_DAYS = 30

    SWATCH_CATEGORIES = frozenset({
        "voice", "visual", "bgm", "transition", "filter",
        "subtitle", "pace", "effect", "thumbnail", "platform",
    })

    def __init__(
        self,
        half_life_days: int = 90,
        lambda_value: Optional[float] = None,
    ):
        """
        Args:
            half_life_days: 偏好半衰期（天数），默认 90 天后权重减半
            lambda_value: 自定义衰减常数，不传则基于 half_life_days 自动计算
        """
        self.half_life_days = half_life_days
        self.lambda_value = lambda_value or self._compute_lambda(half_life_days)

        # 主存储：{user_id: {category: [PreferenceAnchor, ...]}}
        self._store: Dict[str, Dict[str, List[PreferenceAnchor]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # 修正追踪：{user_id: {category: {from_key: count}}}
        # 用于检测用户是否在 "纠错" 历史偏好
        self._correction_tracker: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )

        # 演化历史：{user_id: [EvolutionEvent, ...]}
        self._history: Dict[str, List[EvolutionEvent]] = defaultdict(list)

        logger.info(
            "[PreferenceDecay] 初始化完成 λ=%.2e half_life=%dd",
            self.lambda_value,
            self.half_life_days,
        )

    # ═══════════════════════════════════════════════════════════
    # 公共 API
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def _compute_lambda(cls, half_life_days: int) -> float:
        """根据半衰期计算衰减常数"""
        return math.log(2) / (half_life_days * 86400)

    # ── 衰减 ────────────────────────────────────────────────

    def apply_decay(
        self,
        user_id: str,
        now: Optional[float] = None,
        dry_run: bool = False,
    ) -> Dict[str, list]:
        """对所有用户偏好应用时间衰减

        遍历用户所有类别下的所有锚点，按经过时间衰减权重。
        权重低于 MIN_WEIGHT 的锚点被标记为过期（但不清除）。

        Args:
            user_id: 用户ID
            now: 当前时间戳，默认 time.time()
            dry_run: 仅计算不实际修改，返回修改摘要

        Returns:
            修改摘要：{category: [{key, old_weight, new_weight, expired}, ...]}
        """
        if now is None:
            now = time.time()

        if user_id not in self._store:
            return {}

        summary: Dict[str, list] = {}

        for category, anchors in list(self._store[user_id].items()):
            cat_changes = []
            for anchor in anchors:
                elapsed = max(0.0, now - anchor.decay_clock)
                if elapsed <= 0:
                    continue

                old_weight = anchor.weight
                new_weight = old_weight * math.exp(-self.lambda_value * elapsed)
                new_weight = max(0.0, min(self.MAX_WEIGHT, new_weight))

                if abs(new_weight - old_weight) < 0.0001:
                    continue

                expired = new_weight < self.MIN_WEIGHT

                if not dry_run:
                    anchor.weight = new_weight
                    anchor.decay_clock = now  # 重置衰减时钟
                    if expired:
                        anchor.metadata["expired"] = True
                        anchor.metadata["expired_at"] = now

                cat_changes.append({
                    "key": anchor.key,
                    "old_weight": round(old_weight, 4),
                    "new_weight": round(new_weight, 4),
                    "expired": expired,
                    "elapsed_days": round(elapsed / 86400, 1),
                })

            if cat_changes:
                summary[category] = cat_changes

        if summary:
            total_anchors = sum(len(v) for v in summary.values())
            expired_count = sum(
                1 for v in summary.values() for a in v if a["expired"]
            )
            logger.info(
                "[PreferenceDecay] user=%s 衰减 %d 锚点 (过期:%d)",
                user_id, total_anchors, expired_count,
            )

        return summary

    # ── 冷启动 ──────────────────────────────────────────────

    def cold_start(
        self,
        user_id: str,
        keywords: List[str],
        force: bool = False,
    ) -> Dict[str, List[dict]]:
        """为新用户或 ignore_history 模式提供冷启动偏好

        匹配策略：关键词交集最大的模板获胜；无匹配则使用默认模板。

        Args:
            user_id: 用户ID
            keywords: 风格关键词列表（如 ["科技", "专业"]）
            force: 为 True 时强制覆盖已有偏好（用于 ignore_history 模式）

        Returns:
            {category: [{key, weight, source}, ...]}
        """
        # 选择模板
        template = self._match_template(keywords)

        result = {}
        now = time.time()

        for category, entries in template.items():
            anchors = []
            for entry in entries:
                anchor = PreferenceAnchor(
                    key=entry["key"],
                    category=category,
                    weight=min(self.MAX_WEIGHT, entry.get("weight", 0.5)),
                    source="cold_start",
                    decay_clock=now,
                )
                anchors.append(anchor)
            self._store[user_id][category] = anchors
            result[category] = [a.to_dict() for a in anchors]

        self._record_event(user_id, EvolutionEvent(
            timestamp=now,
            category="*",
            old_key=None,
            new_key=f"cold_start({','.join(keywords[:3])})",
            trigger="cold_start",
            old_weight=0,
            new_weight=0.5,
        ))

        logger.info(
            "[PreferenceDecay] user=%s 冷启动 %d类 keywords=%s",
            user_id, len(result), keywords[:5],
        )
        return result

    def _match_template(self, keywords: List[str]) -> dict:
        """关键词匹配冷启动模板"""
        best_match = None
        best_score = 0

        for template_key, template in COLD_START_TEMPLATES.items():
            # 简单关键词交集评分
            score = 0
            for kw in keywords:
                if template_key in kw or kw in template_key:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = template

        return best_match if best_match else DEFAULT_COLD_START

    # ── 显式偏好 ────────────────────────────────────────────

    def like(
        self,
        user_id: str,
        category: str,
        preferences: List[str],
    ) -> Dict[str, List[dict]]:
        """用户点赞偏好 — 提升权重 + 重置衰减时钟

        Args:
            user_id: 用户ID
            category: 偏好类别
            preferences: 被点赞的偏好值列表

        Returns:
            更新后的该类别所有锚点
        """
        now = time.time()
        self._ensure_category(user_id, category)

        for pref_key in preferences:
            anchor = self._find_or_create_anchor(user_id, category, pref_key)

            # 提升权重（上限 MAX_WEIGHT）
            old_weight = anchor.weight
            anchor.weight = min(self.MAX_WEIGHT, anchor.weight + self.LIKE_BOOST)
            anchor.last_liked_at = now
            anchor.total_likes += 1
            anchor.decay_clock = now  # ★ 重置衰减时钟
            anchor.source = "explicit"
            # 若之前过期，恢复
            anchor.metadata.pop("expired", None)
            anchor.metadata.pop("expired_at", None)

            self._record_event(user_id, EvolutionEvent(
                timestamp=now,
                category=category,
                old_key=pref_key,
                new_key=pref_key,
                trigger="like",
                old_weight=old_weight,
                new_weight=anchor.weight,
            ))

        logger.info(
            "[PreferenceDecay] user=%s LIKE %s → %s",
            user_id, category, preferences,
        )
        return self._get_category_dict(user_id, category)

    def correct(
        self,
        user_id: str,
        category: str,
        from_pref: str,
        to_pref: str,
    ) -> Dict[str, Any]:
        """用户手动修正偏好 — 纠错学习机制

        连续 CORRECTION_MIGRATION_THRESHOLD 次从 from_pref 修正为 to_pref 时，
        自动将 to_pref 晋升为主要偏好，降低 from_pref 的权重。

        Args:
            user_id: 用户ID
            category: 偏好类别
            from_pref: 被替换的旧偏好值
            to_pref: 用户选择的新偏好值

        Returns:
            {migrated: bool, old_key, new_key, old_weight, new_weight, corrections}
        """
        now = time.time()
        self._ensure_category(user_id, category)

        # 记录修正
        self._correction_tracker[user_id][category][f"{from_pref}->{to_pref}"] += 1
        correction_count = self._correction_tracker[user_id][category][f"{from_pref}->{to_pref}"]

        # 降低旧偏好权重
        old_anchor = self._find_anchor(user_id, category, from_pref)
        old_weight_before = old_anchor.weight if old_anchor else 0.0
        if old_anchor:
            old_anchor.weight = max(0.0, old_anchor.weight - 0.10)
            old_anchor.total_corrections += 1

        # 提升新偏好权重
        new_anchor = self._find_or_create_anchor(user_id, category, to_pref)
        new_anchor.weight = min(self.MAX_WEIGHT, new_anchor.weight + 0.10)
        new_anchor.source = "learned"

        migrated = correction_count >= self.CORRECTION_MIGRATION_THRESHOLD

        if migrated:
            # ★ 纠正学习：将新偏好晋升为主要，重置 tracker
            new_anchor.weight = min(self.MAX_WEIGHT, new_anchor.weight + 0.20)
            new_anchor.decay_clock = now  # 重置衰减时钟
            # 清理 tracker 防止重复触发
            self._correction_tracker[user_id][category].pop(f"{from_pref}->{to_pref}", None)

            logger.info(
                "[PreferenceDecay] user=%s CORRECTION_MIGRATED %s: %s → %s (连续%d次)",
                user_id, category, from_pref, to_pref, correction_count,
            )

        self._record_event(user_id, EvolutionEvent(
            timestamp=now,
            category=category,
            old_key=from_pref,
            new_key=to_pref,
            trigger="correct" if not migrated else "correct_migrate",
            old_weight=old_weight_before,
            new_weight=new_anchor.weight,
        ))

        return {
            "category": category,
            "from": from_pref,
            "to": to_pref,
            "migrated": migrated,
            "corrections": correction_count,
            "threshold": self.CORRECTION_MIGRATION_THRESHOLD,
        }

    def dislike(
        self,
        user_id: str,
        category: str,
        preference: str,
    ) -> dict:
        """用户点踩 — 降低权重"""
        now = time.time()
        anchor = self._find_anchor(user_id, category, preference)
        if anchor:
            anchor.weight = max(0.0, anchor.weight - 0.20)
            anchor.metadata["disliked"] = True
            anchor.metadata["disliked_at"] = now

            self._record_event(user_id, EvolutionEvent(
                timestamp=now,
                category=category,
                old_key=preference,
                new_key=preference,
                trigger="dislike",
                old_weight=anchor.weight + 0.20,
                new_weight=anchor.weight,
            ))

        return {"category": category, "key": preference, "action": "disliked"}

    # ── 查询 ────────────────────────────────────────────────

    def get_active_preferences(
        self,
        user_id: str,
        now: Optional[float] = None,
        min_weight: float = 0.05,
    ) -> Dict[str, List[dict]]:
        """获取当前有效偏好（自动先衰减）

        Args:
            user_id: 用户ID
            now: 当前时间戳
            min_weight: 最低权重过滤

        Returns:
            {category: [{key, weight, source, total_likes, ...}, ...]}
        """
        if user_id not in self._store:
            return {}

        # 自动应用衰减
        self.apply_decay(user_id, now=now)

        result = {}
        for category, anchors in self._store[user_id].items():
            active = [
                a for a in anchors
                if a.weight >= min_weight
                and not a.metadata.get("disliked")
            ]
            if active:
                # 按权重降序排列
                active.sort(key=lambda a: a.weight, reverse=True)
                result[category] = [a.to_dict() for a in active]

        return result

    def get_top_preference(
        self,
        user_id: str,
        category: str,
    ) -> Optional[dict]:
        """获取某类别的最高权重偏好"""
        active = self.get_active_preferences(user_id)
        cat_prefs = active.get(category, [])
        return cat_prefs[0] if cat_prefs else None

    # ── 历史 ────────────────────────────────────────────────

    def get_evolution_history(
        self,
        user_id: str,
        days: int = 30,
    ) -> List[dict]:
        """获取偏好演化历史（用于可视化）"""
        now = time.time()
        cutoff = now - days * 86400

        events = self._history.get(user_id, [])
        recent = [e for e in events if e.timestamp >= cutoff]

        # 清理过期事件
        self._history[user_id] = recent

        return [e.to_dict() for e in recent]

    def get_profile_summary(
        self,
        user_id: str,
    ) -> dict:
        """获取用户偏好画像摘要（用于 UI 展示）"""
        active = self.get_active_preferences(user_id)
        history = self.get_evolution_history(user_id)

        # 统计
        total_anchors = sum(len(v) for v in active.values())
        categories_covered = list(active.keys())

        # 最高权重偏好
        top_by_category = {}
        for cat, anchors in active.items():
            if anchors:
                top_by_category[cat] = anchors[0]

        return {
            "user_id": user_id,
            "cold_start": total_anchors == 0,
            "total_anchors": total_anchors,
            "categories": categories_covered,
            "preferences": active,
            "top_picks": top_by_category,
            "evolution_events_count": len(history),
            "evolution_history": history[-20:],  # 最近 20 条
        }

    # ── 冲突解决 ────────────────────────────────────────────

    def resolve_conflict(
        self,
        user_id: str,
        category: str,
        explicit_choice: str,
        memory_suggestion: str,
    ) -> str:
        """冲突解决：显式用户指令 > 衰减记忆

        设计文档 §6.2: 若新项目风格与历史记忆冲突，
        导演以本次显式指令为准。

        Args:
            user_id: 用户ID
            category: 偏好类别
            explicit_choice: 本次用户显式选择
            memory_suggestion: 记忆引擎推荐

        Returns:
            最终使用的偏好（总是返回 explicit_choice）
        """
        if explicit_choice and explicit_choice != memory_suggestion:
            logger.info(
                "[PreferenceDecay] user=%s CONFLICT %s: explicit=%s > memory=%s",
                user_id, category, explicit_choice, memory_suggestion,
            )
            # 记录冲突但不覆盖记忆（标记为"例外"）
            self._record_event(user_id, EvolutionEvent(
                timestamp=time.time(),
                category=category,
                old_key=memory_suggestion,
                new_key=explicit_choice,
                trigger="conflict_override",
            ))

        return explicit_choice

    # ── 清理 ────────────────────────────────────────────────

    def clean_expired(
        self,
        user_id: str,
        older_than_days: int = 180,
    ) -> int:
        """清理过期偏好锚点"""
        now = time.time()
        cutoff = now - older_than_days * 86400
        removed = 0

        if user_id not in self._store:
            return 0

        for category, anchors in list(self._store[user_id].items()):
            # 移除权重极低且长期未使用的锚点
            new_anchors = [
                a for a in anchors
                if a.weight >= self.MIN_WEIGHT
                or a.last_used_at >= cutoff
            ]
            removed += len(anchors) - len(new_anchors)
            if new_anchors:
                self._store[user_id][category] = new_anchors
            else:
                del self._store[user_id][category]

        if removed:
            logger.info(
                "[PreferenceDecay] user=%s 清理 %d 过期锚点",
                user_id, removed,
            )

        return removed

    # ── 批量操作 ────────────────────────────────────────────

    def import_from_project(
        self,
        user_id: str,
        project_prefs: dict,
        source: str = "explicit",
    ):
        """从项目设置导入偏好（批量）

        Args:
            user_id: 用户ID
            project_prefs: {category: key} 或 {category: [key, ...]}
            source: 导入来源标记
        """
        now = time.time()
        count = 0

        for category, value in project_prefs.items():
            if category not in self.SWATCH_CATEGORIES:
                continue

            keys = value if isinstance(value, list) else [value]
            for key in keys:
                anchor = self._find_or_create_anchor(user_id, category, key)
                anchor.last_used_at = now
                anchor.source = source
                anchor.decay_clock = now
                count += 1

        logger.info(
            "[PreferenceDecay] user=%s 从项目导入 %d 偏好",
            user_id, count,
        )

    # ═══════════════════════════════════════════════════════════
    # 内部辅助
    # ═══════════════════════════════════════════════════════════

    def _ensure_category(self, user_id: str, category: str):
        """确保类别存在"""
        if category in self.SWATCH_CATEGORIES:
            if category not in self._store[user_id]:
                self._store[user_id][category] = []

    def _find_anchor(
        self,
        user_id: str,
        category: str,
        key: str,
    ) -> Optional[PreferenceAnchor]:
        """按 key 查找锚点"""
        for anchor in self._store[user_id].get(category, []):
            if anchor.key == key:
                return anchor
        return None

    def _find_or_create_anchor(
        self,
        user_id: str,
        category: str,
        key: str,
    ) -> PreferenceAnchor:
        """查找或创建锚点"""
        anchor = self._find_anchor(user_id, category, key)
        if anchor is None:
            anchor = PreferenceAnchor(
                key=key,
                category=category,
                weight=0.3,   # 新锚点起步权重
                source="inferred",
            )
            self._store[user_id][category].append(anchor)
        return anchor

    def _get_category_dict(
        self,
        user_id: str,
        category: str,
    ) -> Dict[str, List[dict]]:
        """获取某类别的字典表示"""
        anchors = self._store[user_id].get(category, [])
        return {category: [a.to_dict() for a in anchors]}

    def _record_event(self, user_id: str, event: EvolutionEvent):
        """记录演化事件"""
        self._history[user_id].append(event)

        # 定期清理旧事件（保留最近 30 天）
        cutoff = time.time() - self.MAX_HISTORY_DAYS * 86400
        self._history[user_id] = [
            e for e in self._history[user_id]
            if e.timestamp >= cutoff
        ]


# ═══════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════

preference_engine = PreferenceDecayEngine()
