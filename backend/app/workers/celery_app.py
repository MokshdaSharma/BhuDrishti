"""Celery application configuration with graceful fallback."""

from __future__ import annotations

import os

try:
    from celery import Celery
    celery_app = Celery(
        "parcelai",
        broker=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        backend=os.getenv("REDIS_URL", "redis://redis:6379/0"),
    )
    celery_app.conf.task_serializer = "json"
    celery_app.conf.result_serializer = "json"
    celery_app.conf.accept_content = ["json"]
except ImportError:
    class MockCeleryTask:
        def __init__(self, fn):
            self.fn = fn
        def delay(self, *args, **kwargs):
            class MockAsyncResult:
                id = "mock-job-id"
                state = "SUCCESS"
                result = self.fn(None, *args, **kwargs)
                info = {"current": 100, "total": 100, "status": "Finished"}
            return MockAsyncResult()

    class MockCelery:
        def __init__(self, *args, **kwargs):
            self.conf = {}
        def task(self, *args, **kwargs):
            def decorator(fn):
                return MockCeleryTask(fn)
            return decorator

    celery_app = MockCelery("parcelai")
