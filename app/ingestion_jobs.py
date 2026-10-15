"""In-process asynchronous ingestion job queue.

This lightweight queue gives the app a non-blocking ingestion path for large
uploads without changing the UI. It is intentionally thread-based so it works
in the current local development setup; it can be swapped for Celery/RQ +
Redis later without changing the API contract.
"""

from __future__ import annotations

import queue
import logging
import threading
import time
import uuid
from collections.abc import Callable
from fastapi import HTTPException

logger = logging.getLogger(__name__)
_job_queue: "queue.Queue[tuple[str, Callable, tuple, dict]]" = queue.Queue(maxsize=128)
_job_status: dict[str, dict] = {}
_job_lock = threading.RLock()
_worker_started = False
_worker_start_lock = threading.Lock()


def _set_job(job_id: str, **updates) -> None:
    with _job_lock:
        current = _job_status.get(job_id, {"job_id": job_id})
        current.update(updates)
        _job_status[job_id] = current
        if len(_job_status) > 1000:
            for old_id, old_job in list(_job_status.items()):
                if old_id != job_id and old_job.get("status") in {"completed", "failed"}:
                    del _job_status[old_id]
                    if len(_job_status) <= 1000:
                        break


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
            logger.error("Ingestion job %s failed (%s).", job_id, type(exc).__name__)
            _set_job(
                job_id,
                status="failed",
                finished_at=time.time(),
                error="Document processing failed. Contact the operator with this job ID.",
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


def enqueue_job(handler, *args, job_owner=None, job_scope=None, **kwargs) -> str:
    ensure_worker_started()
    job_id = str(uuid.uuid4())
    scope = job_scope or (None, None)
    _set_job(
        job_id, status="queued", queued_at=time.time(), owner_id=job_owner,
        tenant_id=scope[0], collection_id=scope[1],
    )
    try:
        _job_queue.put_nowait((job_id, handler, args, kwargs))
    except queue.Full:
        with _job_lock:
            _job_status.pop(job_id, None)
        logger.warning("Ingestion queue is full.")
        raise HTTPException(503, "Ingestion queue is full. Retry later.") from None
    return job_id


def get_job(job_id: str) -> dict | None:
    with _job_lock:
        job = _job_status.get(job_id)
        return dict(job) if job else None
