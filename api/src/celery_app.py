from celery import Celery
from src.config import AppConfig

config = AppConfig()

celery = Celery(
    "llm_tasks",
    broker=config.redis_url,
    backend=config.redis_url,
    include=["src.tasks"],
)

celery.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)
