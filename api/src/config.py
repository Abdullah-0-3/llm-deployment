import os


class BaseConfig:
    @staticmethod
    def read_env(name: str, default: str | None = None) -> str | None:
        return os.getenv(name, default)


class AppConfig(BaseConfig):
    def __init__(self) -> None:
        self.ollama_url = self.read_env("OLLAMA_URL", "http://localhost:11434") or "http://localhost:11434"
        self.redis_url = self.read_env("REDIS_URL", "redis://redis:6379/0") or "redis://redis:6379/0"
        self.api_key = self.read_env("API_KEY")
        self.model = self.read_env("OLLAMA_MODEL", "tinyllama") or "tinyllama"
        self.rate_limit_per_minute = self._read_rate_limit_per_minute()
        self.cache_ttl_seconds = self._read_cache_ttl_seconds()
        self.cache_prefix = self.read_env("CACHE_PREFIX", "llm:prompt") or "llm:prompt"

    @staticmethod
    def _read_rate_limit_per_minute() -> int:
        raw_value = os.getenv("RATE_LIMIT_PER_MINUTE", "20")
        try:
            value = int(raw_value)
        except ValueError:
            return 20
        return max(value, 1)

    @staticmethod
    def _read_cache_ttl_seconds() -> int:
        raw_value = os.getenv("CACHE_TTL_SECONDS", "3600")
        try:
            value = int(raw_value)
        except ValueError:
            return 3600
        return max(value, 1)
