"""
Cost guard (tiêu chí 8) — theo dõi chi phí LLM trong Redis.

Cộng dồn chi phí theo token vào Redis; vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _daily_key() -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"cost:daily:{day}"


def _monthly_key() -> str:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"cost:monthly:{month}"


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    if r is None:
        raise HTTPException(status_code=503, detail="Cost guard backend unavailable")

    try:
        daily_spent = float(r.get(_daily_key()) or 0.0)
        monthly_spent = float(r.get(_monthly_key()) or 0.0)
    except RedisError:
        raise HTTPException(status_code=503, detail="Cost guard Redis unavailable")

    if daily_spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily LLM budget exceeded",
                "spent_usd": round(daily_spent, 6),
                "budget_usd": settings.daily_budget_usd,
            },
        )

    if monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly LLM budget exceeded",
                "spent_usd": round(monthly_spent, 6),
                "budget_usd": settings.monthly_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí request vào Redis, trả về chi phí request."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    if r is not None:
        try:
            d_key = _daily_key()
            m_key = _monthly_key()
            pipe = r.pipeline()
            pipe.incrbyfloat(d_key, cost)
            pipe.expire(d_key, 48 * 3600)
            pipe.incrbyfloat(m_key, cost)
            pipe.expire(m_key, 35 * 24 * 3600)
            pipe.execute()
        except RedisError:
            pass
    return cost
