from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from prometheus_fastapi_instrumentator import Instrumentator
import os
import requests
import logging

app = FastAPI()
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

class PromptRequest(BaseModel):
    prompt: str

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

logging.basicConfig(level=logging.INFO)

@app.get("/")
def health():
    return {"status": "healthy"}

@app.post("/generate")
def generate(request_data: PromptRequest):
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