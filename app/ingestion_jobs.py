"""In-process asynchronous ingestion job queue.

This lightweight queue gives the app a non-blocking ingestion path for large
uploads without changing the UI. It is intentionally thread-based so it works
in the current local development setup; it can be swapped for Celery/RQ +
Redis later without changing the API contract.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable

_job_queue: "queue.Queue[tuple[str, Callable, tuple, dict]]" = queue.Queue()
_job_status: dict[str, dict] = {}
_job_lock = threading.RLock()
_worker_started = False
_worker_start_lock = threading.Lock()


def _set_job(job_id: str, **updates) -> None:
    with _job_lock:
        current = _job_status.get(job_id, {"job_id": job_id})
        current.update(updates)
        _job_status[job_id] = current


def _worker_loop() -> None:
    while True:
        job_id, handler, args, kwargs = _job_queue.get()
        _set_job(job_id, status="running", started_at=time.time())
        try:
            result = handler(*args, **kwargs)
            _set_job(
                job_id,
                status="completed",
                finished_at=time.time(),
                result=result,
            )
        except Exception as exc:  # pragma: no cover - defensive background handling
            _set_job(
                job_id,
                status="failed",
                finished_at=time.time(),
                error=str(exc),
            )
        finally:
            _job_queue.task_done()


def ensure_worker_started() -> None:
    global _worker_started
    if _worker_started:
        return

    with _worker_start_lock:
        if _worker_started:
            return

        worker = threading.Thread(target=_worker_loop, daemon=True, name="ingestion-worker")
        worker.start()
        _worker_started = True


def enqueue_job(handler, *args, **kwargs) -> str:
    ensure_worker_started()
    job_id = str(uuid.uuid4())
    _set_job(job_id, status="queued", queued_at=time.time())
    _job_queue.put((job_id, handler, args, kwargs))
    return job_id


def get_job(job_id: str) -> dict | None:
    with _job_lock:
        job = _job_status.get(job_id)
        return dict(job) if job else None
