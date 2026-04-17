from celery.result import AsyncResult
from src.llm import LLMClient
from src.models import ResultResponse


class GenerationService:
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def generate_sync(self, prompt: str) -> dict:
        return self._llm_client.generate(prompt)


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
