import logging
from time import perf_counter
from fastapi import Depends, FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
from src.config import AppConfig
from src.cache import RedisPromptCache
from src.observability import app_metrics
from src.models import IngestRequest, IngestResponse, PromptRequest, RagSearchMatch, RagSearchRequest, RagSearchResponse, ResultResponse, SubmitResponse
from src.security import APIKeyAuthenticator
from src.rate_limit import InMemoryRateLimiter
from src.llm import OllamaEmbeddingClient, OllamaLLMClient
from src.services import GenerationService, RAGService, TaskService
from src.storage import PostgresLogStore
from src.celery_app import celery
from src.tasks import generate_with_ollama


class AppFactory:
    def __init__(self) -> None:
        self.config = AppConfig()
        self.authenticator = APIKeyAuthenticator(self.config.api_key)
        self.rate_limiter = InMemoryRateLimiter(self.config.rate_limit_per_minute)
        self.prompt_cache = RedisPromptCache(
            redis_url=self.config.redis_url,
            ttl_seconds=self.config.cache_ttl_seconds,
            key_prefix=self.config.cache_prefix,
        )
        self.log_store = PostgresLogStore(self.config.postgres_url)
        self.log_store.initialize()
        self.rag_service = RAGService(
            OllamaEmbeddingClient(ollama_url=self.config.ollama_url, model=self.config.embed_model),
            store=self.log_store,
            top_k=self.config.rag_top_k,
            chunk_size=self.config.rag_chunk_size,
            chunk_overlap=self.config.rag_chunk_overlap,
        )
        self.generation_service = GenerationService(
            OllamaLLMClient(ollama_url=self.config.ollama_url, model=self.config.model),
            prompt_cache=self.prompt_cache,
            log_store=self.log_store,
            rag_service=self.rag_service,
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

        @app.middleware("http")
        async def metrics_middleware(request, call_next):
            started = perf_counter()
            method = request.method
            path = request.url.path
            try:
                request_size = int(request.headers.get("content-length", "0") or "0")
            except ValueError:
                request_size = 0

            try:
                response = await call_next(request)
            except Exception:
                duration = perf_counter() - started
                app_metrics.observe_http(
                    method=method,
                    path=path,
                    status_code=500,
                    duration_seconds=duration,
                    request_size_bytes=request_size,
                    response_size_bytes=0,
                    slow_threshold_seconds=self.config.slow_request_seconds,
                )
                raise

            duration = perf_counter() - started
            try:
                response_size = int(response.headers.get("content-length", "0") or "0")
            except ValueError:
                response_size = 0

            app_metrics.observe_http(
                method=method,
                path=path,
                status_code=response.status_code,
                duration_seconds=duration,
                request_size_bytes=request_size,
                response_size_bytes=response_size,
                slow_threshold_seconds=self.config.slow_request_seconds,
            )

            return response

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
                return self.generation_service.generate_sync(prompt, session_id=request_data.session_id)
            except RuntimeError as exc:
                raise HTTPException(status_code=502, detail="Failed to reach Ollama") from exc

        @app.post("/ingest", response_model=IngestResponse)
        def ingest(request_data: IngestRequest, api_key: str = Depends(self.authenticator)) -> IngestResponse:
            self.rate_limiter.enforce(api_key)
            text = request_data.text.strip()
            if not text:
                raise HTTPException(status_code=400, detail="Text cannot be empty")

            chunks_stored = self.rag_service.ingest_text(text, source=request_data.source.strip() or "manual")
            return IngestResponse(source=request_data.source.strip() or "manual", chunks_stored=chunks_stored)

        @app.post("/rag/search", response_model=RagSearchResponse)
        def rag_search(request_data: RagSearchRequest, api_key: str = Depends(self.authenticator)) -> RagSearchResponse:
            self.rate_limiter.enforce(api_key)
            query = request_data.query.strip()
            if not query:
                raise HTTPException(status_code=400, detail="Query cannot be empty")

            matches = [
                RagSearchMatch(source=source, content=content, distance=distance)
                for source, content, distance in self.rag_service.search(query, limit=request_data.limit)
            ]
            return RagSearchResponse(query=query, matches=matches)

        @app.post("/submit", response_model=SubmitResponse)
        def submit(request_data: PromptRequest, api_key: str = Depends(self.authenticator)) -> SubmitResponse:
            self.rate_limiter.enforce(api_key)
            prompt = request_data.prompt.strip()
            if not prompt:
                raise HTTPException(status_code=400, detail="Prompt cannot be empty")

            task = generate_with_ollama.delay(prompt, request_data.session_id)
            return SubmitResponse(task_id=task.id, status="queued")

        @app.get("/result/{task_id}", response_model=ResultResponse)
        def result(task_id: str, _api_key: str = Depends(self.authenticator)) -> ResultResponse:
            return self.task_service.build_result(task_id)

        return app


def create_app() -> FastAPI:
    return AppFactory().create()
