from abc import ABC, abstractmethod
import hashlib
import json
import logging
from redis import Redis
from redis.exceptions import RedisError


class PromptCache(ABC):
    @abstractmethod
    def get(self, prompt: str) -> dict | None:
        raise NotImplementedError

    @abstractmethod
    def set(self, prompt: str, value: dict) -> None:
        raise NotImplementedError


class RedisPromptCache(PromptCache):
    def __init__(self, redis_url: str, ttl_seconds: int = 3600, key_prefix: str = "llm:prompt") -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._ttl_seconds = max(ttl_seconds, 1)
        self._key_prefix = key_prefix

    def _key(self, prompt: str) -> str:
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return f"{self._key_prefix}:{prompt_hash}"

    def get(self, prompt: str) -> dict | None:
        key = self._key(prompt)
        try:
            raw = self._redis.get(key)
            if not raw:
                return None
            return json.loads(raw)
        except (RedisError, json.JSONDecodeError):
            logging.exception("Cache get failed")
            return None

    def set(self, prompt: str, value: dict) -> None:
        key = self._key(prompt)
        try:
            self._redis.setex(key, self._ttl_seconds, json.dumps(value))
        except (RedisError, TypeError, ValueError):
            logging.exception("Cache set failed")
