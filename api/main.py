from collections import defaultdict, deque
from threading import Lock
from time import time
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator
import os
import requests
import logging

app = FastAPI()
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
API_KEY = os.getenv("API_KEY")


def _read_rate_limit_per_minute() -> int:
    raw_value = os.getenv("RATE_LIMIT_PER_MINUTE", "20")
    try:
        value = int(raw_value)
    except ValueError:
        logging.warning("Invalid RATE_LIMIT_PER_MINUTE value '%s'; using default 20", raw_value)
        return 20

    return max(value, 1)


RATE_LIMIT_PER_MINUTE = _read_rate_limit_per_minute()
REQUEST_WINDOW_SECONDS = 60
request_logs = defaultdict(deque)
rate_limit_lock = Lock()

logging.basicConfig(level=logging.INFO)


def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    if not API_KEY:
        logging.error("API_KEY is not configured")
        raise HTTPException(status_code=500, detail="Server API key is not configured")

    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return x_api_key


def enforce_rate_limit(client_key: str) -> None:
    now = time()
    window_start = now - REQUEST_WINDOW_SECONDS

    with rate_limit_lock:
        timestamps = request_logs[client_key]

        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        if len(timestamps) >= RATE_LIMIT_PER_MINUTE:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: max {RATE_LIMIT_PER_MINUTE} requests per minute",
            )

        timestamps.append(now)

@app.get("/")
def health():
    return {"status": "healthy"}

@app.post("/generate")
def generate(request_data: PromptRequest, api_key: str = Depends(verify_api_key)):
    enforce_rate_limit(api_key)

    prompt = request_data.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    logging.info("Prompt received")

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "tinyllama",
                "prompt": prompt,
                "stream": False,
            },
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.exception("Failed to call Ollama")
        raise HTTPException(status_code=502, detail="Failed to reach Ollama") from exc

    try:
        return response.json()
    except ValueError as exc:
        logging.exception("Ollama returned a non-JSON response")
        raise HTTPException(status_code=502, detail="Invalid response from Ollama") from exc