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

    @abstractmethod
    def save_session_message(self, session_id: str, role: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_recent_session_messages(self, session_id: str, limit: int = 10) -> list[tuple[str, str]]:
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
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS session_messages (
                                id BIGSERIAL PRIMARY KEY,
                                session_id TEXT NOT NULL,
                                role TEXT NOT NULL,
                                content TEXT NOT NULL,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_session_messages_session_created
                            ON session_messages (session_id, created_at)
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

    def save_session_message(self, session_id: str, role: str, content: str) -> None:
        if not self._ensure_table():
            return

        if not session_id.strip() or not content.strip():
            return

        try:
            with connect(self._postgres_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO session_messages (session_id, role, content)
                        VALUES (%s, %s, %s)
                        """,
                        (session_id.strip(), role, content),
                    )
                connection.commit()
        except Exception:
            logging.exception("Failed to write session message to PostgreSQL")

    def get_recent_session_messages(self, session_id: str, limit: int = 10) -> list[tuple[str, str]]:
        if not self._ensure_table():
            return []

        safe_limit = max(1, min(limit, 20))
        try:
            with connect(self._postgres_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT role, content
                        FROM (
                            SELECT role, content, created_at
                            FROM session_messages
                            WHERE session_id = %s
                            ORDER BY created_at DESC
                            LIMIT %s
                        ) recent
                        ORDER BY created_at ASC
                        """,
                        (session_id.strip(), safe_limit),
                    )
                    rows = cursor.fetchall()
                    return [(str(row[0]), str(row[1])) for row in rows]
        except Exception:
            logging.exception("Failed to read session messages from PostgreSQL")
            return []