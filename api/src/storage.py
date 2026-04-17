from abc import ABC, abstractmethod
import logging
from threading import Lock

from psycopg import connect
from psycopg.types.json import Json
from src.observability import app_metrics


class GenerationLogStore(ABC):
    @abstractmethod
    def save(self, prompt: str, response: dict, latency_ms: int) -> None:
        raise NotImplementedError


class PostgresLogStore(GenerationLogStore):
    def __init__(self, postgres_url: str | None) -> None:
        self._postgres_url = postgres_url
        self._lock = Lock()
        self._table_ready = False

    def _ensure_table(self) -> bool:
        if not self._postgres_url:
            return False

        if self._table_ready:
            return True

        with self._lock:
            if self._table_ready:
                return True

            try:
                with connect(self._postgres_url) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS llm_logs (
                                id BIGSERIAL PRIMARY KEY,
                                prompt TEXT NOT NULL,
                                response JSONB NOT NULL,
                                latency_ms INTEGER NOT NULL,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                    connection.commit()
                self._table_ready = True
                existing_records = self.count_records()
                if existing_records is not None:
                    app_metrics.set_db_records(existing_records)
                return True
            except Exception:
                logging.exception("Failed to prepare PostgreSQL logging table")
                return False

    def initialize(self) -> None:
        self._ensure_table()

    def count_records(self) -> int | None:
        if not self._postgres_url:
            return None

        try:
            with connect(self._postgres_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM llm_logs")
                    count = cursor.fetchone()
                    if count is None:
                        return 0
                    return int(count[0])
        except Exception:
            logging.exception("Failed to count records in PostgreSQL")
            return None

    def save(self, prompt: str, response: dict, latency_ms: int) -> None:
        if not self._ensure_table():
            return

        try:
            with connect(self._postgres_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO llm_logs (prompt, response, latency_ms)
                        VALUES (%s, %s, %s)
                        """,
                        (prompt, Json(response), latency_ms),
                    )
                connection.commit()
            app_metrics.record_db_write()
        except Exception:
            logging.exception("Failed to write generation log to PostgreSQL")