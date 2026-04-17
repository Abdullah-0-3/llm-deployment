from abc import ABC, abstractmethod
from collections import defaultdict, deque
from threading import Lock
from time import time
from fastapi import HTTPException


class RateLimiter(ABC):
    @abstractmethod
    def enforce(self, client_key: str) -> None:
        raise NotImplementedError


class InMemoryRateLimiter(RateLimiter):
    def __init__(self, max_requests: int, window_seconds: int = 60) -> None:
        self._max_requests = max(max_requests, 1)
        self._window_seconds = window_seconds
        self._logs = defaultdict(deque)
        self._lock = Lock()

    def enforce(self, client_key: str) -> None:
        now = time()
        window_start = now - self._window_seconds

        with self._lock:
            timestamps = self._logs[client_key]

            while timestamps and timestamps[0] < window_start:
                timestamps.popleft()

            if len(timestamps) >= self._max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: max {self._max_requests} requests per minute",
                )

            timestamps.append(now)
