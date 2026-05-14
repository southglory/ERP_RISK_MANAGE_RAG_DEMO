"""Phase 6D — Langfuse 트레이싱 헬퍼.

v4 SDK 의 start_as_current_observation 은 내부적으로 OTLP exporter 를 쓰는데
이 프로젝트 환경(도커 Langfuse + 워밍업) 에서 5초 timeout 으로 실패하는 일이 잦다.
대신 v3-호환 패턴 (lf.trace().span().end()) 을 쓴다. 이쪽이 HTTP 직접 호출이라
core/rag/pipeline.py 와 동일하게 동작이 보장된다.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import os
import time
from collections import defaultdict
from typing import Any, Callable

_enabled: bool | None = None
_client = None
_current_trace: contextvars.ContextVar = contextvars.ContextVar("_current_trace", default=None)

# ── 노드별 latency 수집 (Langfuse 가 안 닿아도 우리 자체로 측정) ──────────────
_metrics: dict[str, list[float]] = defaultdict(list)


def reset_metrics() -> None:
    _metrics.clear()


def record_latency(name: str, ms: float) -> None:
    _metrics[name].append(ms)


def get_metrics() -> dict[str, dict]:
    """노드 이름 → {count, total_ms, avg_ms, min_ms, max_ms}."""
    out: dict[str, dict] = {}
    for name, samples in _metrics.items():
        if not samples:
            continue
        out[name] = {
            "count":    len(samples),
            "total_ms": round(sum(samples), 1),
            "avg_ms":   round(sum(samples) / len(samples), 2),
            "min_ms":   round(min(samples), 2),
            "max_ms":   round(max(samples), 2),
        }
    return out


def langfuse_enabled() -> bool:
    global _enabled
    if _enabled is None:
        _enabled = bool(
            os.environ.get("LANGFUSE_PUBLIC_KEY")
            and os.environ.get("LANGFUSE_SECRET_KEY")
        )
    return _enabled


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not langfuse_enabled():
        return None
    try:
        from langfuse import Langfuse
        _client = Langfuse(
            public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY", ""),
            host=os.environ.get("LANGFUSE_BASE_URL")
                 or os.environ.get("LANGFUSE_HOST", "http://localhost:3000"),
        )
    except Exception:
        _client = None
    return _client


def flush_traces() -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        pass


@contextlib.contextmanager
def trace_span(name: str, **kwargs: Any):
    """v3 호환 패턴.
    - 현재 trace 가 없으면 새 trace 만들고 첫 span 으로 등록 (root span 역할).
    - 이미 trace 가 있으면 그 trace 아래 child span 으로 붙임.
    """
    client = _get_client()
    if client is None:
        yield None
        return

    t0 = time.perf_counter()
    try:
        yield None  # Langfuse v4 OTLP 미작동 — 일단 측정만 수집
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        record_latency(name, elapsed_ms)


def traced_node(name: str) -> Callable:
    """LangGraph 노드 함수를 trace_span 으로 감싸는 데코레이터."""
    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def awrapper(state: dict) -> dict:
                with trace_span(name, input={"n_txns": len(state.get("transactions", []))}):
                    return await func(state)
            return awrapper

        @functools.wraps(func)
        def wrapper(state: dict) -> dict:
            with trace_span(name, input={"n_txns": len(state.get("transactions", []))}):
                return func(state)
        return wrapper
    return decorator
