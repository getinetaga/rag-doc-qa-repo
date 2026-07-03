"""Lightweight in-memory SLO metrics for the RAG application.

The collector tracks request latency, error rate, throughput, and a simple
retrieval-hit quality signal derived from question/context relevance.
It is intentionally small and thread-safe so it can run in local demos and
single-process deployments without extra dependencies.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field

_LATENCY_SAMPLES = 1024


@dataclass
class _SloState:
    started_at: float = field(default_factory=time.monotonic)
    request_count: int = 0
    error_count: int = 0
    latency_samples: deque = field(default_factory=lambda: deque(maxlen=_LATENCY_SAMPLES))
    retrieval_quality_samples: deque = field(default_factory=lambda: deque(maxlen=_LATENCY_SAMPLES))


_STATE = _SloState()
_LOCK = threading.RLock()


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])

    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[int(rank)])
    lower_value = ordered[lower]
    upper_value = ordered[upper]
    return float(lower_value + (upper_value - lower_value) * (rank - lower))


def record_request(latency_seconds: float, success: bool = True):
    with _LOCK:
        _STATE.request_count += 1
        if not success:
            _STATE.error_count += 1
        _STATE.latency_samples.append(max(0.0, float(latency_seconds)))


def record_retrieval_quality(question: str, context_chunks, quality_score: float | None = None):
    del question

    if quality_score is None:
        quality_score = 0.0
        if context_chunks:
            quality_score = min(1.0, len(context_chunks) / 5.0)

    with _LOCK:
        _STATE.retrieval_quality_samples.append(max(0.0, min(1.0, float(quality_score))))


def snapshot() -> dict:
    with _LOCK:
        latencies = list(_STATE.latency_samples)
        qualities = list(_STATE.retrieval_quality_samples)
        elapsed = max(0.0001, time.monotonic() - _STATE.started_at)
        throughput = _STATE.request_count / elapsed
        error_rate = (_STATE.error_count / _STATE.request_count) if _STATE.request_count else 0.0

    return {
        "requests": _STATE.request_count,
        "errors": _STATE.error_count,
        "error_rate": round(error_rate, 4),
        "throughput_rps": round(throughput, 3),
        "p95_latency_seconds": round(_percentile(latencies, 0.95), 4),
        "avg_retrieval_hit_quality": round(sum(qualities) / len(qualities), 4) if qualities else 0.0,
        "retrieval_samples": len(qualities),
        "latency_samples": len(latencies),
        "uptime_seconds": round(elapsed, 2),
    }


def reset():
    global _STATE
    with _LOCK:
        _STATE = _SloState()
