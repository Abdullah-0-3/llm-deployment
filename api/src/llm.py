from abc import ABC, abstractmethod
import logging
import requests


class LLMClient(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> dict:
        raise NotImplementedError


class OllamaLLMClient(LLMClient):
    def __init__(self, ollama_url: str, model: str = "tinyllama", timeout_seconds: int = 60) -> None:
        self._ollama_url = ollama_url
        self._model = model
        self._timeout_seconds = timeout_seconds

    def generate(self, prompt: str) -> dict:
        try:
            response = requests.post(
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logging.exception("Failed to call Ollama")
            raise RuntimeError("Failed to reach Ollama") from exc

        try:
            return response.json()
        except ValueError as exc:
            logging.exception("Ollama returned a non-JSON response")
            raise RuntimeError("Invalid response from Ollama") from exc
