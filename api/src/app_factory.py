import logging
from fastapi import Depends, FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from src.config import AppConfig
from src.models import PromptRequest, ResultResponse, SubmitResponse
from src.security import APIKeyAuthenticator
from src.rate_limit import InMemoryRateLimiter
from src.llm import OllamaLLMClient
from src.services import GenerationService, TaskService
from src.celery_app import celery
from src.tasks import generate_with_ollama


class AppFactory:
    def __init__(self) -> None:
        self.config = AppConfig()
        self.authenticator = APIKeyAuthenticator(self.config.api_key)
        self.rate_limiter = InMemoryRateLimiter(self.config.rate_limit_per_minute)
        self.generation_service = GenerationService(
            OllamaLLMClient(ollama_url=self.config.ollama_url, model=self.config.model)
        )
        self.task_service = TaskService(celery)

    def create(self) -> FastAPI:
        logging.basicConfig(level=logging.INFO)

        app = FastAPI(
            title="Simple LLM Deployment API",
            description="Synchronous and asynchronous LLM inference with queue-based processing.",
            version="1.0.0",
        )
        Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

        @app.get("/")
        def health() -> dict:
            return {"status": "healthy"}

        @app.post("/generate")
        def generate(request_data: PromptRequest, api_key: str = Depends(self.authenticator)) -> dict:
            self.rate_limiter.enforce(api_key)
            prompt = request_data.prompt.strip()
            if not prompt:
                raise HTTPException(status_code=400, detail="Prompt cannot be empty")

            try:
                return self.generation_service.generate_sync(prompt)
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail="Failed to reach Ollama") from exc

        @app.post("/submit", response_model=SubmitResponse)
        def submit(request_data: PromptRequest, api_key: str = Depends(self.authenticator)) -> SubmitResponse:
            self.rate_limiter.enforce(api_key)
            prompt = request_data.prompt.strip()
            if not prompt:
                raise HTTPException(status_code=400, detail="Prompt cannot be empty")

            task = generate_with_ollama.delay(prompt)
            return SubmitResponse(task_id=task.id, status="queued")

        @app.get("/result/{task_id}", response_model=ResultResponse)
        def result(task_id: str, _api_key: str = Depends(self.authenticator)) -> ResultResponse:
            return self.task_service.build_result(task_id)

        return app


def create_app() -> FastAPI:
    return AppFactory().create()
