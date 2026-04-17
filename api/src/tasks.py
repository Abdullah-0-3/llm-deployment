from src.config import AppConfig
from src.llm import OllamaLLMClient
from src.celery_app import celery


@celery.task(name="tasks.generate_with_ollama")
def generate_with_ollama(prompt: str) -> dict:
    config = AppConfig()
    client = OllamaLLMClient(ollama_url=config.ollama_url, model=config.model)
    return client.generate(prompt)
