from abc import ABC, abstractmethod
import logging
from threading import Lock

from pgvector.psycopg import Vector, register_vector
from psycopg import connect
from psycopg.types.json import Json
from src.observability import app_metrics


class GenerationLogStore(ABC):
    @abstractmethod
    def save(
        self,
        prompt: str,
        response: dict,
        latency_ms: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_session_message(self, session_id: str, role: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_recent_session_messages(self, session_id: str, limit: int = 10) -> list[tuple[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def save_rag_chunks(self, source: str, chunks: list[str], embeddings: list[list[float]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search_rag_chunks(self, query_embedding: list[float], limit: int = 3) -> list[tuple[str, str, float]]:
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
                        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    connection.commit()

                    register_vector(connection)

                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS llm_logs (
                                id BIGSERIAL PRIMARY KEY,
                                prompt TEXT NOT NULL,
                                response JSONB NOT NULL,
                                latency_ms INTEGER NOT NULL,
                                input_tokens INTEGER NOT NULL DEFAULT 0,
                                output_tokens INTEGER NOT NULL DEFAULT 0,
                                total_tokens INTEGER NOT NULL DEFAULT 0,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                        cursor.execute("ALTER TABLE llm_logs ADD COLUMN IF NOT EXISTS input_tokens INTEGER NOT NULL DEFAULT 0")
                        cursor.execute("ALTER TABLE llm_logs ADD COLUMN IF NOT EXISTS output_tokens INTEGER NOT NULL DEFAULT 0")
                        cursor.execute("ALTER TABLE llm_logs ADD COLUMN IF NOT EXISTS total_tokens INTEGER NOT NULL DEFAULT 0")
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
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS rag_chunks (
                                id BIGSERIAL PRIMARY KEY,
                                source TEXT NOT NULL,
                                chunk_index INTEGER NOT NULL,
                                content TEXT NOT NULL,
                                embedding vector(768) NOT NULL,
                                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE INDEX IF NOT EXISTS idx_rag_chunks_source
                            ON rag_chunks (source)
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

    def save(
        self,
        prompt: str,
        response: dict,
        latency_ms: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
    ) -> None:
        if not self._ensure_table():
            return

        try:
            with connect(self._postgres_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO llm_logs (prompt, response, latency_ms, input_tokens, output_tokens, total_tokens)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            prompt,
                            Json(response),
                            latency_ms,
                            max(input_tokens, 0),
                            max(output_tokens, 0),
                            max(total_tokens, 0),
                        ),
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

    def save_rag_chunks(self, source: str, chunks: list[str], embeddings: list[list[float]]) -> None:
        if not self._ensure_table():
            return

        if len(chunks) != len(embeddings):
            raise ValueError("Chunks and embeddings must have the same length")

        clean_source = source.strip() or "manual"

        try:
            with connect(self._postgres_url) as connection:
                register_vector(connection)
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM rag_chunks WHERE source = %s", (clean_source,))
                    for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                        cursor.execute(
                            """
                            INSERT INTO rag_chunks (source, chunk_index, content, embedding)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (clean_source, index, chunk, Vector(embedding)),
                        )
                connection.commit()
        except Exception:
            logging.exception("Failed to write RAG chunks to PostgreSQL")

    def search_rag_chunks(self, query_embedding: list[float], limit: int = 3) -> list[tuple[str, str, float]]:
        if not self._ensure_table():
            return []

        safe_limit = max(1, min(limit, 10))
        try:
            with connect(self._postgres_url) as connection:
                register_vector(connection)
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT source, content, (embedding <=> %s) AS distance
                        FROM rag_chunks
                        ORDER BY distance
                        LIMIT %s
                        """,
                        (Vector(query_embedding), safe_limit),
                    )
                    rows = cursor.fetchall()
                    return [(str(row[0]), str(row[1]), float(row[2])) for row in rows]
        except Exception:
            logging.exception("Failed to search RAG chunks in PostgreSQL")
            return []