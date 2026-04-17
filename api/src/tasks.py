from src.config import AppConfig
from src.cache import RedisPromptCache
from src.llm import OllamaLLMClient
from src.celery_app import celery
from src.services import GenerationService
from src.storage import PostgresLogStore
from src.worker_metrics import worker_metrics
from time import perf_counter


worker_metrics.start()


@celery.task(name="tasks.generate_with_ollama")
def generate_with_ollama(prompt: str) -> dict:
    started_at = perf_counter()
    config = AppConfig()
    client = OllamaLLMClient(ollama_url=config.ollama_url, model=config.model)
    cache = RedisPromptCache(
        redis_url=config.redis_url,
        ttl_seconds=config.cache_ttl_seconds,
        key_prefix=config.cache_prefix,
    )
    log_store = PostgresLogStore(config.postgres_url)
    service = GenerationService(llm_client=client, prompt_cache=cache, log_store=log_store)
    try:
        result = service.generate_sync(prompt, source="async")
    except Exception:
        worker_metrics.record("tasks.generate_with_ollama", "failure", started_at)
        raise

    worker_metrics.record("tasks.generate_with_ollama", "success", started_at)
    return result
