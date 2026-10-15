import queue

import pytest
from fastapi import HTTPException

from app import ingestion_jobs


def test_full_queue_rejects_without_leaking_job_state(monkeypatch):
    pending = queue.Queue(maxsize=1)
    pending.put("already full")
    monkeypatch.setattr(ingestion_jobs, "_job_queue", pending)
    monkeypatch.setattr(ingestion_jobs, "_job_status", {})
    monkeypatch.setattr(ingestion_jobs, "ensure_worker_started", lambda: None)
    with pytest.raises(HTTPException) as error:
        ingestion_jobs.enqueue_job(lambda: None, job_owner="writer", job_scope=("a", "p"))
    assert error.value.status_code == 503
    assert not ingestion_jobs._job_status


def test_completed_job_history_is_bounded(monkeypatch):
    monkeypatch.setattr(ingestion_jobs, "_job_status", {})
    for number in range(1010):
        ingestion_jobs._set_job(str(number), status="completed")
    assert len(ingestion_jobs._job_status) == 1000
    assert "1009" in ingestion_jobs._job_status


def test_background_error_is_sanitized(monkeypatch, caplog):
    def failing_handler():
        raise ValueError("sensitive-source-detail")

    class OneJobQueue:
        consumed = False

        def get(self):
            if self.consumed:
                raise KeyboardInterrupt
            self.consumed = True
            return "job", failing_handler, (), {}

        def task_done(self):
            pass

    monkeypatch.setattr(ingestion_jobs, "_job_queue", OneJobQueue())
    monkeypatch.setattr(ingestion_jobs, "_job_status", {})
    with pytest.raises(KeyboardInterrupt):
        ingestion_jobs._worker_loop()
    status = ingestion_jobs.get_job("job")
    assert status["status"] == "failed"
    assert "sensitive-source-detail" not in status["error"]
    assert "sensitive-source-detail" not in caplog.text
