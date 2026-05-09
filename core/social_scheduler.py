"""
Social Scheduler — 社媒排期发布引擎
功能：定时发布、跨平台同步、队列管理、自动Hashtag
"""
import asyncio, json, logging, os, uuid
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger("quanquan.social_scheduler")

@dataclass
class ScheduledPost:
    post_id: str
    platform: str
    content: dict                      # {title, description, tags, video_path, thumbnail}
    scheduled_time: str                # ISO datetime
    status: str = "pending"            # pending/published/failed/cancelled
    result: dict = field(default_factory=dict)
    created_at: str = ""
    published_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


class SocialScheduler:
    """社媒排期发布引擎"""

    def __init__(self, data_dir: str = "/data/quanquan/data"):
        self._data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._queue: Dict[str, ScheduledPost] = {}
        self._history: List[ScheduledPost] = []
        self._load()

    def _load(self):
        path = os.path.join(self._data_dir, "social_queue.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                for p in data.get("queue", []):
                    sp = ScheduledPost(**p)
                    self._queue[sp.post_id] = sp
                for p in data.get("history", []):
                    self._history.append(ScheduledPost(**p))
                logger.info(f"加载 {len(self._queue)} 个待发 + {len(self._history)} 条历史")
            except Exception as e:
                logger.warning(f"加载排期数据失败: {e}")

    def _save(self):
        path = os.path.join(self._data_dir, "social_queue.json")
        data = {
            "queue": [p.__dict__ for p in self._queue.values()],
            "history": [p.__dict__ for p in self._history[-100:]],
        }
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    # ── 公共 API ──

    def schedule_post(self, platform: str, content: dict, scheduled_time: str = None) -> str:
        """排期发布帖子

        Args:
            platform: bilibili/douyin/youtube
            content: {title, description, tags, video_path, thumbnail}
            scheduled_time: ISO格式时间，None=立即

        Returns:
            post_id: 帖子唯一ID
        """
        post_id = f"post_{uuid.uuid4().hex[:12]}"
        if not scheduled_time:
            scheduled_time = datetime.utcnow().isoformat()

        post = ScheduledPost(
            post_id=post_id,
            platform=platform,
            content=content,
            scheduled_time=scheduled_time,
        )
        self._queue[post_id] = post
        self._save()
        logger.info(f"排期: {post_id} → {platform} @ {scheduled_time}")
        return post_id

    def cross_post(self, content: dict, platforms: List[str], scheduled_time: str = None) -> Dict[str, str]:
        """跨平台同步发布

        Args:
            content: 基础内容
            platforms: 目标平台列表
            scheduled_time: 统一发布时间

        Returns:
            {platform: post_id} 映射
        """
        results = {}
        for platform in platforms:
            # 为每个平台优化内容
            pc = dict(content)
            pc["platform"] = platform
            post_id = self.schedule_post(platform, pc, scheduled_time)
            results[platform] = post_id
        return results

    def get_queue(self, platform: str = None, status: str = None) -> List[dict]:
        """获取待发队列"""
        posts = list(self._queue.values())
        if platform:
            posts = [p for p in posts if p.platform == platform]
        if status:
            posts = [p for p in posts if p.status == status]
        posts.sort(key=lambda p: p.scheduled_time)
        return [p.__dict__ for p in posts]

    def get_upcoming(self, hours: int = 24) -> List[dict]:
        """获取未来N小时内要发布的帖子"""
        now = datetime.utcnow()
        cutoff = now + timedelta(hours=hours)
        upcoming = []
        for p in self._queue.values():
            if p.status == "pending":
                try:
                    pt = datetime.fromisoformat(p.scheduled_time)
                    if now <= pt <= cutoff:
                        upcoming.append(p.__dict__)
                except: pass
        return sorted(upcoming, key=lambda x: x["scheduled_time"])

    def cancel_scheduled(self, post_id: str) -> bool:
        """取消排期"""
        if post_id in self._queue:
            post = self._queue[post_id]
            post.status = "cancelled"
            self._history.append(post)
            del self._queue[post_id]
            self._save()
            logger.info(f"取消排期: {post_id}")
            return True
        return False

    def mark_published(self, post_id: str, result: dict = None) -> bool:
        """标记为已发布"""
        if post_id in self._queue:
            post = self._queue[post_id]
            post.status = "published"
            post.published_at = datetime.utcnow().isoformat()
            if result:
                post.result = result
            self._history.append(post)
            del self._queue[post_id]
            self._save()
            return True
        return False

    def mark_failed(self, post_id: str, error: str = "") -> bool:
        """标记为失败"""
        if post_id in self._queue:
            post = self._queue[post_id]
            post.status = "failed"
            post.result = {"error": error}
            self._history.append(post)
            del self._queue[post_id]
            self._save()
            return True
        return False

    def get_analytics(self) -> dict:
        """聚合发布分析"""
        total = len(self._history)
        published = sum(1 for p in self._history if p.status == "published")
        failed = sum(1 for p in self._history if p.status == "failed")
        cancelled = sum(1 for p in self._history if p.status == "cancelled")

        by_platform = {}
        for p in self._history:
            by_platform.setdefault(p.platform, {"total": 0, "published": 0, "failed": 0})
            by_platform[p.platform]["total"] += 1
            if p.status == "published":
                by_platform[p.platform]["published"] += 1
            elif p.status == "failed":
                by_platform[p.platform]["failed"] += 1

        # 最近7天趋势
        now = datetime.utcnow()
        week_ago = now - timedelta(days=7)
        daily = {}
        for p in self._history:
            try:
                pt = datetime.fromisoformat(p.published_at or p.created_at)
                if pt >= week_ago:
                    day = pt.strftime("%Y-%m-%d")
                    daily.setdefault(day, 0)
                    daily[day] += 1
            except: pass

        return {
            "total_posts": total,
            "published": published,
            "failed": failed,
            "cancelled": cancelled,
            "success_rate": round(published / total * 100, 1) if total > 0 else 0,
            "queue_size": len(self._queue),
            "by_platform": by_platform,
            "daily_trend": [{"date": k, "count": v} for k, v in sorted(daily.items())],
            "generated_at": now.isoformat(),
        }

    def get_best_times(self, platform: str) -> dict:
        """获取最佳发布时间建议（基于平台特性）"""
        suggestions = {
            "bilibili": {
                "best_days": ["周五", "周六", "周日"],
                "best_hours": ["12:00", "18:00", "20:00"],
                "avoid_hours": ["02:00-06:00"],
                "tip": "B站用户活跃高峰在午餐和晚间，周末流量更大",
            },
            "douyin": {
                "best_days": ["每天"],
                "best_hours": ["07:00", "12:00", "18:00", "21:00"],
                "avoid_hours": ["02:00-05:00"],
                "tip": "抖音全天活跃，早7点/午12点/晚6-9点是黄金时段",
            },
            "youtube": {
                "best_days": ["周四", "周五", "周六"],
                "best_hours": ["14:00", "16:00", "20:00"],
                "avoid_hours": ["00:00-06:00"],
                "tip": "YouTube推荐周四-周六下午发布，给算法时间索引",
            },
        }
        return suggestions.get(platform, suggestions["bilibili"])

    def auto_hashtag_content(self, content: dict, platform: str) -> dict:
        """自动添加平台优化标签"""
        try:
            from core.auto_hashtag import hashtag_generator
            tags = hashtag_generator.generate_tags(
                text=content.get("title", "") + " " + content.get("description", ""),
                platform=platform,
                count={"bilibili": 8, "douyin": 5, "youtube": 15}.get(platform, 5),
            )
            content["tags"] = list(set(content.get("tags", []) + (tags or [])))
        except Exception as e:
            logger.warning(f"自动标签失败: {e}")
        return content

    def clear_history(self, days: int = 30):
        """清理旧历史"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        self._history = [
            p for p in self._history
            if datetime.fromisoformat(p.published_at or p.created_at) >= cutoff
        ]
        self._save()


# 模块级实例
social_scheduler = SocialScheduler()
