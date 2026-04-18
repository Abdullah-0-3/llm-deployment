import os


class BaseConfig:
    @staticmethod
    def read_env(name: str, default: str | None = None) -> str | None:
        return os.getenv(name, default)


class AppConfig(BaseConfig):
    def __init__(self) -> None:
        self.ollama_url = self.read_env("OLLAMA_URL", "http://localhost:11434") or "http://localhost:11434"
        self.redis_url = self.read_env("REDIS_URL", "redis://redis:6379/0") or "redis://redis:6379/0"
        self.postgres_url = self.read_env("POSTGRES_URL")
        self.api_key = self.read_env("API_KEY")
        self.model = self.read_env("OLLAMA_MODEL", "tinyllama") or "tinyllama"
        self.embed_model = self.read_env("OLLAMA_EMBED_MODEL", "nomic-embed-text") or "nomic-embed-text"
        self.rate_limit_per_minute = self._read_rate_limit_per_minute()
        self.cache_ttl_seconds = self._read_cache_ttl_seconds()
        self.cache_prefix = self.read_env("CACHE_PREFIX", "llm:prompt") or "llm:prompt"
        self.slow_request_seconds = self._read_slow_request_seconds()
        self.rag_top_k = self._read_rag_top_k()
        self.rag_chunk_size = self._read_rag_chunk_size()

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

    @staticmethod
    def _read_slow_request_seconds() -> float:
        raw_value = os.getenv("SLOW_REQUEST_SECONDS", "1.0")
        try:
            value = float(raw_value)
        except ValueError:
            return 1.0
        return max(value, 0.05)

    @staticmethod
    def _read_rag_top_k() -> int:
        raw_value = os.getenv("RAG_TOP_K", "3")
        try:
            value = int(raw_value)
        except ValueError:
            return 3
        return max(value, 1)

    @staticmethod
    def _read_rag_chunk_size() -> int:
        raw_value = os.getenv("RAG_CHUNK_SIZE", "1000")
        try:
            value = int(raw_value)
        except ValueError:
            return 1000
        return max(value, 200)
