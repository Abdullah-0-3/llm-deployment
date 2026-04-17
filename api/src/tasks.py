from src.config import AppConfig
from src.cache import RedisPromptCache
from src.llm import OllamaLLMClient
from src.celery_app import celery
from src.services import GenerationService
from src.storage import PostgresLogStore


@celery.task(name="tasks.generate_with_ollama")
def generate_with_ollama(prompt: str) -> dict:
    config = AppConfig()
    client = OllamaLLMClient(ollama_url=config.ollama_url, model=config.model)
    cache = RedisPromptCache(
        redis_url=config.redis_url,
        ttl_seconds=config.cache_ttl_seconds,
        key_prefix=config.cache_prefix,
    )
    log_store = PostgresLogStore(config.postgres_url)
    service = GenerationService(llm_client=client, prompt_cache=cache, log_store=log_store)
    return service.generate_sync(prompt)
