from celery.result import AsyncResult
from src.cache import PromptCache
from src.llm import LLMClient
from src.models import ResultResponse
from src.storage import GenerationLogStore
from src.observability import app_metrics
from time import perf_counter


class GenerationService:
    def __init__(
        self,
        llm_client: LLMClient,
        prompt_cache: PromptCache | None = None,
        log_store: GenerationLogStore | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._prompt_cache = prompt_cache
        self._log_store = log_store

    def generate_sync(self, prompt: str, source: str = "sync", session_id: str | None = None) -> dict:
        started_at = perf_counter()
        normalized_session_id = (session_id or "").strip() or None
        effective_prompt = prompt

        if normalized_session_id and self._log_store:
            history = self._log_store.get_recent_session_messages(normalized_session_id)
            effective_prompt = self._build_prompt_with_history(prompt, history)

        use_cache = self._prompt_cache is not None and normalized_session_id is None

        if use_cache and self._prompt_cache:
            cached = self._prompt_cache.get(prompt)
            if cached is not None:
                app_metrics.record_llm_cache_hit(source)
                app_metrics.record_llm_generation(source, "cached", perf_counter() - started_at)
                self._log_generation(prompt, cached, started_at)
                self._save_session_turn(normalized_session_id, prompt, cached)
                return cached

        if use_cache:
            app_metrics.record_llm_cache_miss(source)

        try:
            result = self._llm_client.generate(effective_prompt)
        except RuntimeError:
            app_metrics.record_llm_generation(source, "error", perf_counter() - started_at)
            raise

        if use_cache and self._prompt_cache:
            self._prompt_cache.set(prompt, result)

        app_metrics.record_llm_generation(source, "success", perf_counter() - started_at)
        self._log_generation(prompt, result, started_at)
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

    def _save_session_turn(self, session_id: str | None, prompt: str, result: dict) -> None:
        if not session_id or not self._log_store:
            return

        assistant_text = str(result.get("response", "")).strip()
        self._log_store.save_session_message(session_id=session_id, role="user", content=prompt)
        if assistant_text:
            self._log_store.save_session_message(session_id=session_id, role="assistant", content=assistant_text)

    def _log_generation(self, prompt: str, response: dict, started_at: float) -> None:
        if not self._log_store:
            return

        latency_ms = int((perf_counter() - started_at) * 1000)
        self._log_store.save(prompt=prompt, response=response, latency_ms=latency_ms)


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
