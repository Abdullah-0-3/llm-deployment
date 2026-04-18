from celery.result import AsyncResult
import re
from src.cache import PromptCache
from src.llm import EmbeddingClient, LLMClient
from src.models import ResultResponse
from src.storage import GenerationLogStore
from src.observability import app_metrics
from time import perf_counter


class RAGService:
    def __init__(
        self,
        embedding_client: EmbeddingClient,
        store: GenerationLogStore,
        top_k: int = 3,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
    ) -> None:
        self._embedding_client = embedding_client
        self._store = store
        self._top_k = top_k
        self._chunk_size = max(chunk_size, 200)
        self._chunk_overlap = max(0, min(chunk_overlap, self._chunk_size - 50))

    def ingest_text(self, text: str, source: str = "manual") -> int:
        chunks = self._chunk_text(text)
        if not chunks:
            return 0

        embeddings = [self._embedding_client.embed(chunk) for chunk in chunks]
        self._store.save_rag_chunks(source=source, chunks=chunks, embeddings=embeddings)
        return len(chunks)

    def retrieve_context(self, query: str) -> str:
        matches = self.search(query, limit=self._top_k)
        if not matches:
            return ""

        lines = ["Relevant context:", ""]
        for source, content, _distance in matches:
            lines.append(f"Source: {source}")
            lines.append(content)
            lines.append("")
        return "\n".join(lines).strip()

    def search(self, query: str, limit: int | None = None) -> list[tuple[str, str, float]]:
        query_embedding = self._embedding_client.embed(query)
        resolved_limit = self._top_k if limit is None else limit
        return self._store.search_rag_chunks(query_embedding, limit=resolved_limit)

    def list_sources(self) -> list[tuple[str, int, str]]:
        return self._store.list_rag_sources()

    def delete_source(self, source: str) -> int:
        return self._store.delete_rag_source(source)

    def list_session_ids(self, limit: int = 100) -> list[tuple[str, int, str]]:
        return self._store.list_session_ids(limit=limit)

    def _chunk_text(self, text: str) -> list[str]:
        normalized = " ".join(text.split())
        if not normalized:
            return []

        if len(normalized) <= self._chunk_size:
            return [normalized]

        chunks: list[str] = []
        start = 0
        text_length = len(normalized)

        while start < text_length:
            tentative_end = min(start + self._chunk_size, text_length)
            end = tentative_end

            if tentative_end < text_length:
                window = normalized[start:tentative_end]
                best_cut = -1
                for pattern in (r"\. ", r"\? ", r"! "):
                    match = None
                    for match in re.finditer(pattern, window):
                        pass
                    if match:
                        best_cut = max(best_cut, match.end())

                if best_cut > self._chunk_size // 2:
                    end = start + best_cut

            chunk = normalized[start:end].strip()
            if chunk and (not chunks or chunk != chunks[-1]):
                chunks.append(chunk)

            if end >= text_length:
                break

            next_start = end - self._chunk_overlap
            if next_start <= start:
                next_start = end
            start = next_start

        return chunks


class GenerationService:
    def __init__(
        self,
        llm_client: LLMClient,
        prompt_cache: PromptCache | None = None,
        log_store: GenerationLogStore | None = None,
        rag_service: RAGService | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._prompt_cache = prompt_cache
        self._log_store = log_store
        self._rag_service = rag_service

    def generate_sync(self, prompt: str, source: str = "sync", session_id: str | None = None) -> dict:
        started_at = perf_counter()
        normalized_session_id = (session_id or "").strip() or None
        effective_prompt = prompt
        rag_context = ""

        if normalized_session_id and self._log_store:
            history = self._log_store.get_recent_session_messages(normalized_session_id)
            effective_prompt = self._build_prompt_with_history(prompt, history)

        if not normalized_session_id and self._rag_service:
            rag_context = self._rag_service.retrieve_context(prompt)
            if rag_context:
                effective_prompt = self._build_prompt_with_rag(prompt, rag_context)

        use_cache = self._prompt_cache is not None and normalized_session_id is None and not rag_context

        if use_cache and self._prompt_cache:
            cached = self._prompt_cache.get(prompt)
            if cached is not None:
                app_metrics.record_llm_cache_hit(source)
                app_metrics.record_llm_generation(source, "cached", perf_counter() - started_at)
                self._log_generation(prompt, cached, started_at, input_tokens=0, output_tokens=0)
                self._save_session_turn(normalized_session_id, prompt, cached)
                return cached

        if use_cache:
            app_metrics.record_llm_cache_miss(source)

        try:
            result = self._llm_client.generate(effective_prompt)
        except RuntimeError:
            app_metrics.record_llm_generation(source, "error", perf_counter() - started_at)
            raise

        input_tokens, output_tokens = self._extract_tokens(result)
        app_metrics.record_llm_tokens(source, input_tokens, output_tokens)

        if use_cache and self._prompt_cache:
            self._prompt_cache.set(prompt, result)

        app_metrics.record_llm_generation(source, "success", perf_counter() - started_at)
        self._log_generation(prompt, result, started_at, input_tokens=input_tokens, output_tokens=output_tokens)
        self._save_session_turn(normalized_session_id, prompt, result)

        return result

    @staticmethod
    def _build_prompt_with_history(prompt: str, history: list[tuple[str, str]]) -> str:
        if not history:
            return prompt

        lines = ["Use the conversation history below to answer naturally.", ""]
        for role, content in history:
            role_name = "User" if role == "user" else "Assistant"
            lines.append(f"{role_name}: {content}")
        lines.append(f"User: {prompt}")
        lines.append("Assistant:")
        return "\n".join(lines)

    @staticmethod
    def _build_prompt_with_rag(prompt: str, rag_context: str) -> str:
        return "\n\n".join(
            [
                "Use the retrieved context below if it helps answer the question.",
                rag_context,
                f"User: {prompt}",
                "Assistant:",
            ]
        )

    def _save_session_turn(self, session_id: str | None, prompt: str, result: dict) -> None:
        if not session_id or not self._log_store:
            return

        assistant_text = str(result.get("response", "")).strip()
        self._log_store.save_session_message(session_id=session_id, role="user", content=prompt)
        if assistant_text:
            self._log_store.save_session_message(session_id=session_id, role="assistant", content=assistant_text)

    @staticmethod
    def _extract_tokens(response: dict) -> tuple[int, int]:
        raw_input = response.get("prompt_eval_count", 0)
        raw_output = response.get("eval_count", 0)

        try:
            input_tokens = int(raw_input)
        except (TypeError, ValueError):
            input_tokens = 0

        try:
            output_tokens = int(raw_output)
        except (TypeError, ValueError):
            output_tokens = 0

        return max(input_tokens, 0), max(output_tokens, 0)

    def _log_generation(self, prompt: str, response: dict, started_at: float, input_tokens: int, output_tokens: int) -> None:
        if not self._log_store:
            return

        latency_ms = int((perf_counter() - started_at) * 1000)
        total_tokens = max(input_tokens, 0) + max(output_tokens, 0)
        self._log_store.save(
            prompt=prompt,
            response=response,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )


class TaskService:
    def __init__(self, celery_app) -> None:
        self._celery_app = celery_app

    def build_result(self, task_id: str) -> ResultResponse:
        task_result = AsyncResult(task_id, app=self._celery_app)

        if task_result.state == "PENDING":
            return ResultResponse(task_id=task_id, status="queued")

        if task_result.state in {"STARTED", "RETRY"}:
            return ResultResponse(task_id=task_id, status="processing")

        if task_result.state == "SUCCESS":
            return ResultResponse(task_id=task_id, status="completed", result=task_result.result)

        if task_result.state == "FAILURE":
            return ResultResponse(task_id=task_id, status="failed", error=str(task_result.result))

        return ResultResponse(task_id=task_id, status=task_result.state.lower())
