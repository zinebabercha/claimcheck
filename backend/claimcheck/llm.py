"""Minimal Mistral client (JSON mode) + a fake client for tests."""
from __future__ import annotations

import json
import os
import re
import time

import httpx

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"


class LLMError(RuntimeError):
    pass


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)  # tolerate ```json fences
        if m:
            return json.loads(m.group(0))
        raise


class MistralLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float = 60.0):
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY", "")
        self.model = model or os.getenv("MISTRAL_MODEL", "mistral-small-latest")
        self.timeout = timeout
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def json(self, system: str, user: str, temperature: float = 0.0, retries: int = 3) -> dict:
        if not self.configured:
            raise LLMError("MISTRAL_API_KEY manquante : ajoutez-la dans le fichier .env")
        payload = {
            "model": self.model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last = None
        for attempt in range(retries):
            try:
                r = httpx.post(MISTRAL_URL, json=payload, headers=headers, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:  # free tier: rate limits are common
                    last = LLMError(f"Mistral {r.status_code}: {r.text[:200]}")
                    time.sleep(2 ** attempt * 1.5)
                    continue
                if r.status_code != 200:
                    raise LLMError(f"Mistral {r.status_code}: {r.text[:300]}")
                data = r.json()
                for k in self.usage:
                    self.usage[k] += data.get("usage", {}).get(k, 0)
                return _parse_json(data["choices"][0]["message"]["content"])
            except (httpx.HTTPError, json.JSONDecodeError) as e:
                last = e
                time.sleep(2 ** attempt)
        raise LLMError(f"Échec de l'appel Mistral : {last}")


class FakeLLM:
    """Returns scripted responses in order (for tests / offline runs)."""

    model = "fake"
    configured = True

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def json(self, system: str, user: str, **_) -> dict:
        self.calls.append((system, user))
        return self.responses.pop(0)
