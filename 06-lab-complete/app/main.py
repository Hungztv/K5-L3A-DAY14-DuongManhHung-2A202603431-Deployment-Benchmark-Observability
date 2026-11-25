"""
Production AI Agent — Part 6 Final Project.

Đáp ứng đủ 12 tiêu chí Production Readiness:
  - Config 12-Factor từ biến môi trường (app/config.py)
  - Structured JSON logging
  - Liveness (/health) & Readiness (/ready kiểm tra Redis)
  - API Key authentication (X-API-Key → 401)
  - Stateless sliding-window rate limiting trong Redis (→ 429)
  - Cost guard trong Redis (→ 402)
  - Graceful shutdown (SIGTERM + FastAPI lifespan)
"""
from __future__ import annotations

import json
import logging
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mỗi dòng log của ứng dụng thành một JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> logging.Logger:
    app_logger = logging.getLogger("production_agent")
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    app_logger.setLevel(level)
    app_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.propagate = False
    return app_logger


logger = _configure_logging()
START_TIME = time.time()


def _log(level: int, event: str, **fields) -> None:
    logger.log(level, event, extra={"extra_fields": {"event": event, **fields}})


# Bảo toàn SIGTERM handler mặc định của uvicorn để graceful shutdown hoạt động đúng
if hasattr(signal, "SIGTERM"):
    _previous_sigterm = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum, frame):
        _log(logging.INFO, "sigterm_received", signum=signum)
        if callable(_previous_sigterm):
            _previous_sigterm(signum, frame)

    signal.signal(signal.SIGTERM, _on_sigterm)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log(
        logging.INFO,
        "startup",
        environment=settings.environment,
        port=settings.port,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        daily_budget_usd=settings.daily_budget_usd,
    )
    yield
    _log(logging.INFO, "shutdown_initiated")
    close_redis()
    _log(logging.INFO, "shutdown_complete")


app = FastAPI(
    title="Production AI Agent",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        _log(
            logging.INFO,
            "http_request",
            method=request.method,
            path=request.url.path,
            status=status_code,
            ms=elapsed_ms,
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    _log(
        logging.ERROR,
        "unhandled_exception",
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness probe — luôn trả 200 khi process còn sống, không phụ thuộc Redis."""
    return {
        "status": "ok",
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


@app.get("/ready")
def ready():
    """Readiness probe — 200 khi Redis kết nối được, 503 khi Redis down."""
    if not redis_healthy():
        _log(logging.WARNING, "readiness_failed", dependency="redis")
        raise HTTPException(status_code=503, detail="Redis is not reachable")
    return {"status": "ready", "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)

    input_tokens = max(1, len(body.question) // 4)
    output_tokens = max(1, len(answer) // 4)
    cost_usd = record_cost(input_tokens, output_tokens)

    _log(
        logging.INFO,
        "ask_completed",
        user_id=body.user_id or "anonymous",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost_usd, 8),
    )

    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 8),
        },
    }
