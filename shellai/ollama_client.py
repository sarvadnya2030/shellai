"""Ollama API client for ShellAI."""

import sys
import urllib.request
import urllib.error
import json
from typing import Optional

from .config import Config


class OllamaClient:
    """Client for interacting with a local Ollama instance."""

    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.ollama_url
        self.model = config.model
        self.timeout = config.timeout

    def _post(self, endpoint: str, payload: dict) -> dict:
        """Make a POST request to the Ollama API."""
        url = f"{self.base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            if "Connection refused" in str(e) or "actively refused" in str(e):
                print(
                    "\n\033[91m✗ Cannot connect to Ollama at "
                    f"{self.base_url}\033[0m"
                )
                print("  Make sure Ollama is running:  ollama serve")
                print(f"  Make sure the model exists:   ollama pull {self.model}\n")
                sys.exit(1)
            raise

    def is_available(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Return available model names."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def generate(self, prompt: str, stream: bool = False, think: bool = False) -> str:
        """Generate a response from the model.

        think=False disables chain-of-thought for qwen3/qwen3.5 thinking models,
        giving direct answers instead of putting everything in the <think> block.
        Use think=True only for the explain prompt where reasoning is helpful.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
            "think": think,
            "options": {
                "temperature": 0.1,   # Low temp for deterministic commands
                "num_predict": 256,
            },
        }

        if stream:
            return self._stream_generate(payload)

        response = self._post("/api/generate", payload)
        # Fallback: some model versions put output in thinking when think=True
        return (response.get("response") or response.get("thinking", "")).strip()

    def _stream_generate(self, payload: dict) -> str:
        """Stream tokens and return the full response."""
        url = f"{self.base_url}/api/generate"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        full_response = []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for line in resp:
                    chunk = json.loads(line.decode("utf-8"))
                    token = chunk.get("response", "")
                    print(token, end="", flush=True)
                    full_response.append(token)
                    if chunk.get("done"):
                        print()  # newline after stream ends
                        break
        except urllib.error.URLError as e:
            print(f"\n\033[91m✗ Stream error: {e}\033[0m")
            sys.exit(1)
        return "".join(full_response).strip()

    def chat(self, messages: list[dict]) -> str:
        """Use chat endpoint for multi-turn conversation."""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 512},
        }
        response = self._post("/api/chat", payload)
        return response.get("message", {}).get("content", "").strip()
