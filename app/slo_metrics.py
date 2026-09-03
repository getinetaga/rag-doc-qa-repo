"""Service-level objective (SLO) metrics for the RAG application.

A dependency-free, thread-safe collector that turns raw request timings into a
structured SLO report:

* **Traffic** — total requests and average throughput.
* **Availability** — success / error counts and rates.
* **Latency** — a p50 / p90 / p95 / p99 / max / mean distribution over a rolling
  window of the most recent samples.
* **Retrieval quality** — the mean question-to-context hit-quality signal.
* **SLO** — each of the above compared against a configured target, with a
  per-objective attainment ratio, an overall status, and a simple error-budget
  figure.

Targets are read once at import time and can be overridden through the
environment (``SLO_*`` variables). The collector is in-process and bounded; for
multi-process or long-horizon reporting, export ``snapshot()`` to a real metrics
backend such as Prometheus.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Rolling window size for latency and retrieval-quality samples.
_LATENCY_SAMPLES = 1024

# --- SLO targets (override via environment) ---------------------------------
SERVICE_NAME = os.getenv("SLO_SERVICE_NAME", "rag-doc-qa")
AVAILABILITY_TARGET = float(os.getenv("SLO_AVAILABILITY_TARGET", "0.99"))
LATENCY_P95_TARGET_SECONDS = float(os.getenv("SLO_LATENCY_P95_TARGET_SECONDS", "3.0"))
LATENCY_P99_TARGET_SECONDS = float(os.getenv("SLO_LATENCY_P99_TARGET_SECONDS", "8.0"))
RETRIEVAL_QUALITY_TARGET = float(os.getenv("SLO_RETRIEVAL_QUALITY_TARGET", "0.6"))

# Status vocabulary.
_MET = "met"
_AT_RISK = "at_risk"
_BREACHED = "breached"
_UNKNOWN = "unknown"


@dataclass
class _SloState:
    started_at: float = field(default_factory=time.monotonic)
    first_request_at: float | None = None
    last_request_at: float | None = None
    request_count: int = 0
    error_count: int = 0
    latency_samples: deque = field(
        default_factory=lambda: deque(maxlen=_LATENCY_SAMPLES)
    )
    retrieval_quality_samples: deque = field(
        default_factory=lambda: deque(maxlen=_LATENCY_SAMPLES)
    )


_STATE = _SloState()
_LOCK = threading.RLock()


def _percentile(values: list[float], percentile: float) -> float:
    """Linear-interpolation percentile (0.0-1.0) over an unsorted list."""

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


def record_request(latency_seconds: float, success: bool = True) -> None:
    """Record one completed request: its wall-clock latency and outcome."""

    with _LOCK:
        now = time.monotonic()
        _STATE.request_count += 1
        if not success:
            _STATE.error_count += 1
        _STATE.latency_samples.append(max(0.0, float(latency_seconds)))
        if _STATE.first_request_at is None:
            _STATE.first_request_at = now
        _STATE.last_request_at = now


def record_retrieval_quality(
    question: str, context_chunks, quality_score: float | None = None
) -> None:
    """Record a retrieval-hit quality sample in the range 0.0-1.0.

    A caller-supplied ``quality_score`` (e.g. lexical question/context overlap) is
    preferred; otherwise a coarse fallback based on the number of retrieved
    chunks is used. ``question`` is accepted for call-site symmetry and ignored.
    """

    del question

    if quality_score is None:
        quality_score = 0.0
        if context_chunks:
            quality_score = min(1.0, len(context_chunks) / 5.0)

    with _LOCK:
        _STATE.retrieval_quality_samples.append(
            max(0.0, min(1.0, float(quality_score)))
        )


def _objective(
    name: str, observed: float, target: float, mode: str, *, has_data: bool
) -> dict:
    """Compare one observed value against its target.

    ``mode`` is ``"max"`` when higher is better (availability, quality) or
    ``"min"`` when lower is better (latency). An objective with no samples yet is
    reported as ``unknown`` and does not affect the overall status.
    """

    if not has_data or target <= 0:
        return {
            "name": name,
            "observed": round(observed, 4),
            "target": round(target, 4),
            "attainment": None,
            "status": _UNKNOWN,
        }

    if mode == "max":
        attainment = observed / target
        if observed < target:
            status = _BREACHED
        elif observed < target * 1.05:
            status = _AT_RISK
        else:
            status = _MET
    else:  # "min" — lower is better
        attainment = target / observed if observed > 0 else 1.0
        if observed > target:
            status = _BREACHED
        elif observed > target * 0.8:
            status = _AT_RISK
        else:
            status = _MET

    return {
        "name": name,
        "observed": round(observed, 4),
        "target": round(target, 4),
        "attainment": round(attainment, 4),
        "status": status,
    }


def snapshot() -> dict:
    """Return the current SLO report as a JSON-serializable dict."""

    with _LOCK:
        latencies = list(_STATE.latency_samples)
        qualities = list(_STATE.retrieval_quality_samples)
        total = _STATE.request_count
        errors = _STATE.error_count
        started_at = _STATE.started_at
        first_at = _STATE.first_request_at
        last_at = _STATE.last_request_at

    now = time.monotonic()
    elapsed = max(1e-4, now - started_at)

    successes = total - errors
    success_rate = (successes / total) if total else 1.0
    error_rate = (errors / total) if total else 0.0

    p50 = _percentile(latencies, 0.50)
    p90 = _percentile(latencies, 0.90)
    p95 = _percentile(latencies, 0.95)
    p99 = _percentile(latencies, 0.99)
    latency_max = max(latencies) if latencies else 0.0
    latency_mean = (sum(latencies) / len(latencies)) if latencies else 0.0

    avg_quality = (sum(qualities) / len(qualities)) if qualities else 0.0

    # Error budget: the share of the allowed failure rate still unspent.
    allowed_failure_rate = max(0.0, 1.0 - AVAILABILITY_TARGET)
    if allowed_failure_rate == 0.0:
        error_budget_remaining = 1.0 if error_rate == 0.0 else 0.0
    else:
        error_budget_remaining = max(0.0, 1.0 - (error_rate / allowed_failure_rate))

    objectives = [
        _objective(
            "availability", success_rate, AVAILABILITY_TARGET, "max",
            has_data=total > 0,
        ),
        _objective(
            "latency_p95_seconds", p95, LATENCY_P95_TARGET_SECONDS, "min",
            has_data=bool(latencies),
        ),
        _objective(
            "latency_p99_seconds", p99, LATENCY_P99_TARGET_SECONDS, "min",
            has_data=bool(latencies),
        ),
        _objective(
            "retrieval_hit_quality", avg_quality, RETRIEVAL_QUALITY_TARGET, "max",
            has_data=bool(qualities),
        ),
    ]

    if any(o["status"] == _BREACHED for o in objectives):
        status = _BREACHED
    elif error_budget_remaining < 0.25 or any(
        o["status"] == _AT_RISK for o in objectives
    ):
        status = _AT_RISK
    else:
        status = "healthy"

    return {
        "service": SERVICE_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window": {
            "uptime_seconds": round(elapsed, 2),
            "latency_sample_size": len(latencies),
            "latency_sample_capacity": _LATENCY_SAMPLES,
            "retrieval_sample_size": len(qualities),
            "first_request_seconds_ago": (
                round(now - first_at, 2) if first_at is not None else None
            ),
            "last_request_seconds_ago": (
                round(now - last_at, 2) if last_at is not None else None
            ),
        },
        "traffic": {
            "requests_total": total,
            "requests_per_second_since_start": round(total / elapsed, 3),
        },
        "availability": {
            "success_total": successes,
            "error_total": errors,
            "success_rate": round(success_rate, 4),
            "error_rate": round(error_rate, 4),
        },
        "latency_seconds": {
            "p50": round(p50, 4),
            "p90": round(p90, 4),
            "p95": round(p95, 4),
            "p99": round(p99, 4),
            "max": round(latency_max, 4),
            "mean": round(latency_mean, 4),
        },
        "retrieval_quality": {
            "avg_hit_quality": round(avg_quality, 4),
            "samples": len(qualities),
        },
        "slo": {
            "status": status,
            "error_budget_remaining": round(error_budget_remaining, 4),
            "targets": {
                "availability": AVAILABILITY_TARGET,
                "latency_p95_seconds": LATENCY_P95_TARGET_SECONDS,
                "latency_p99_seconds": LATENCY_P99_TARGET_SECONDS,
                "retrieval_hit_quality": RETRIEVAL_QUALITY_TARGET,
            },
            "objectives": objectives,
        },
    }


def reset() -> None:
    """Discard all collected samples and counters (used between tests)."""

    global _STATE
    with _LOCK:
        _STATE = _SloState()
