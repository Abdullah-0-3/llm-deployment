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

    def generate_sync(self, prompt: str, source: str = "sync") -> dict:
        started_at = perf_counter()

        if self._prompt_cache:
            cached = self._prompt_cache.get(prompt)
            if cached is not None:
                app_metrics.record_llm_cache_hit(source)
                app_metrics.record_llm_generation(source, "cached", perf_counter() - started_at)
                self._log_generation(prompt, cached, started_at)
                return cached

        if self._prompt_cache:
            app_metrics.record_llm_cache_miss(source)

        try:
            result = self._llm_client.generate(prompt)
        except RuntimeError:
            app_metrics.record_llm_generation(source, "error", perf_counter() - started_at)
            raise

        if self._prompt_cache:
            self._prompt_cache.set(prompt, result)

        app_metrics.record_llm_generation(source, "success", perf_counter() - started_at)
        self._log_generation(prompt, result, started_at)

        return result

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
