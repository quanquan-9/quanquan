"""
API 速率限制 (Rate Limiter)

功能：
- 令牌桶算法 (Token Bucket)
- 滑动窗口计数
- 多维度限流 (用户/IP/API)
- 自动降级响应
"""

import time
import asyncio
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """限流配置"""
    requests: int         # 请求数
    window_sec: float     # 时间窗口（秒）
    burst: int = 0        # 突发允许（令牌桶）


# 预设限流规则
RATE_LIMITS = {
    "default": RateLimitConfig(requests=60, window_sec=60, burst=10),
    "create_project": RateLimitConfig(requests=10, window_sec=60, burst=3),
    "video_inspect": RateLimitConfig(requests=30, window_sec=60),
    "encode": RateLimitConfig(requests=5, window_sec=60, burst=2),
    "export": RateLimitConfig(requests=3, window_sec=60),
    "search": RateLimitConfig(requests=20, window_sec=60),
    "health": RateLimitConfig(requests=120, window_sec=60),
}


class TokenBucket:
    """令牌桶算法"""

    def __init__(self, rate: float, capacity: int):
        self.rate = rate              # 令牌填充速率（每秒）
        self.capacity = capacity      # 桶容量
        self.tokens = float(capacity) # 当前令牌数
        self.last_refill = time.monotonic()

    def consume(self, tokens: int = 1) -> bool:
        """消费令牌"""
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    @property
    def available(self) -> int:
        self._refill()
        return int(self.tokens)


class SlidingWindowCounter:
    """滑动窗口计数器"""

    def __init__(self, window_sec: float):
        self.window_sec = window_sec
        self._timestamps: list = []

    def increment(self) -> int:
        """增加计数，返回窗口内总数"""
        now = time.monotonic()
        self._timestamps.append(now)
        self._cleanup(now)
        return len(self._timestamps)

    def count(self) -> int:
        """当前窗口内计数"""
        self._cleanup(time.monotonic())
        return len(self._timestamps)

    def _cleanup(self, now: float):
        cutoff = now - self.window_sec
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.pop(0)

    def would_exceed(self, limit: int) -> bool:
        return self.count() >= limit


class RateLimiter:
    """速率限制器"""

    def __init__(self):
        # 用户维度
        self._user_buckets: Dict[str, Dict[str, TokenBucket]] = defaultdict(dict)
        self._user_counters: Dict[str, Dict[str, SlidingWindowCounter]] = defaultdict(dict)
        # IP 维度
        self._ip_counters: Dict[str, Dict[str, SlidingWindowCounter]] = defaultdict(dict)

    def check(
        self,
        key: str,           # user_id or IP
        endpoint: str = "default",
        dimension: str = "user",
    ) -> Tuple[bool, dict]:
        """检查是否允许请求

        Returns:
            (allowed, headers_dict)
        """
        config = RATE_LIMITS.get(endpoint, RATE_LIMITS["default"])

        # 令牌桶检查
        if dimension == "user":
            bucket = self._user_buckets[key].get(endpoint)
            if bucket is None:
                bucket = TokenBucket(
                    rate=config.requests / config.window_sec,
                    capacity=config.requests + config.burst,
                )
                self._user_buckets[key][endpoint] = bucket

            allowed = bucket.consume(1)
            remaining = bucket.available
        else:
            # IP 维度：滑动窗口
            counter = self._ip_counters[key].get(endpoint)
            if counter is None:
                counter = SlidingWindowCounter(config.window_sec)
                self._ip_counters[key][endpoint] = counter

            if counter.would_exceed(config.requests):
                allowed = False
                remaining = 0
            else:
                counter.increment()
                allowed = True
                remaining = config.requests - counter.count()

        # 构建响应头
        headers = {
            "X-RateLimit-Limit": str(config.requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(time.time() + config.window_sec)),
        }

        if not allowed:
            headers["Retry-After"] = str(int(config.window_sec))
            logger.warning(f"Rate limit exceeded: {key} on {endpoint}")

        return allowed, headers

    def reset(self, key: str, endpoint: Optional[str] = None):
        """重置限流计数"""
        if endpoint:
            self._user_buckets[key].pop(endpoint, None)
            self._user_counters[key].pop(endpoint, None)
        else:
            self._user_buckets.pop(key, None)
            self._user_counters.pop(key, None)


# 全局实例
rate_limiter = RateLimiter()


# ============================================================
# FastAPI 中间件
# ============================================================

class RateLimitMiddleware:
    """FastAPI 速率限制中间件"""

    def __init__(self, app, limiter: RateLimiter = None):
        self.app = app
        self.limiter = limiter or rate_limiter

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 提取客户端 IP
        client_ip = scope.get("client", ("unknown", 0))[0]

        # 提取用户（如果有认证）
        headers = dict(scope.get("headers", []))
        user_id = None
        auth_header = headers.get(b"authorization", b"").decode()
        if auth_header.startswith("Bearer "):
            user_id = "auth_user"

        key = user_id or client_ip
        path = scope.get("path", "/")
        endpoint = path.split("/")[-1] if "/" in path else path

        allowed, rate_headers = self.limiter.check(key, endpoint)

        if not allowed:
            # 429 Too Many Requests
            from urllib.parse import quote
            body = b'{"error":"rate_limit_exceeded","message":"Too many requests"}'
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    *[(k.encode(), str(v).encode()) for k, v in rate_headers.items()],
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)
