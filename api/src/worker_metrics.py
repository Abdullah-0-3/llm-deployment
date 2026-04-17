import os
from threading import Lock
from time import perf_counter

from prometheus_client import Counter, Histogram, start_http_server


class WorkerMetrics:
    def __init__(self) -> None:
        self._started = False
        self._lock = Lock()
        self.celery_task_total = Counter(
            "celery_task_total",
            "Total Celery task executions",
            ["task_name", "status"],
        )
        self.celery_task_duration_seconds = Histogram(
            "celery_task_duration_seconds",
            "Celery task duration in seconds",
            ["task_name"],
        )

    def start(self) -> None:
        port_value = os.getenv("WORKER_METRICS_PORT")
        if not port_value:
            return

        with self._lock:
            if self._started:
                return

            start_http_server(int(port_value))
            self._started = True

    def record(self, task_name: str, status: str, started_at: float) -> None:
        self.celery_task_total.labels(task_name=task_name, status=status).inc()
        self.celery_task_duration_seconds.labels(task_name=task_name).observe(max(perf_counter() - started_at, 0.0))


worker_metrics = WorkerMetrics()