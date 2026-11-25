"""
Rate limiting (tiêu chí 7) — Sliding Window 60 giây dùng Redis Sorted Set.

State lưu trong Redis để mọi worker / instance dùng chung và vẫn giữ nguyên sau restart.
"""
import time
import uuid

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """Kiểm tra sliding window 60s cho mỗi API key; vượt ngưỡng trả HTTP 429."""
    if r is None:
        raise HTTPException(status_code=503, detail="Rate limiter backend unavailable")

    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"ratelimit:{key}"
    limit = settings.rate_limit_per_minute

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zcard(redis_key)
        _, current_count = pipe.execute()

        if current_count >= limit:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit exceeded",
                    "limit_per_minute": limit,
                    "retry_after_seconds": WINDOW_SECONDS,
                },
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )

        member = f"{now}:{uuid.uuid4().hex}"
        pipe = r.pipeline()
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, WINDOW_SECONDS + 5)
        pipe.execute()
    except HTTPException:
        raise
    except RedisError:
        raise HTTPException(status_code=503, detail="Rate limiter Redis unavailable")
