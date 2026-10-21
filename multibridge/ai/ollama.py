"""Minimal client for a local Ollama server, standard library only.

- Loopback only: the URL must point at 127.0.0.1 / localhost / ::1 (COMPLIANCE C3).
  `MULTIBRIDGE_OLLAMA_URL` can change the port, never the machine.
- `format` takes a JSON schema, so the model can only answer in that shape.
- `think` switches Qwen3's reasoning on or off. The thinking text is never returned or stored.
- `temperature 0` + fixed seed: the same input gives the same proposal.
- `unload()` frees the model's memory when the proposal is done (keep_alive 0).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

DEFAULT_URL = "http://127.0.0.1:11434"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class OllamaUnavailable(RuntimeError):
    """Ollama isn't running, the model isn't installed, or the reply wasn't usable."""


def base_url() -> str:
    url = os.environ.get("MULTIBRIDGE_OLLAMA_URL", DEFAULT_URL).rstrip("/")
    host = urlparse(url).hostname
    if host not in LOOPBACK:
        raise ValueError(f"Ollama must run on this machine (127.0.0.1); refusing {host!r} (COMPLIANCE C3)")
    return url


def _post(path: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(base_url() + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise OllamaUnavailable(f"Ollama respondió {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise OllamaUnavailable(f"no se puede conectar con Ollama en {base_url()}: {e}") from None


def chat(model: str, system: str, user: str, schema: dict | None = None, think: bool = False,
         timeout: float = 600, keep_alive: str | int = "2m", num_ctx: int = 12288,
         num_predict: int = 4096) -> dict:
    """One non-streaming chat turn. Returns the parsed JSON answer (or {"text": ...} without a schema).

    num_ctx: Ollama's default window (~4k tokens) is smaller than prompt + answer for a real file,
    and an overflowing context makes the model ramble until the timeout. num_predict caps the answer
    (thinking included) so a confused model fails fast instead of running for minutes.
    """
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "think": think,
        "keep_alive": keep_alive,
        "options": {"temperature": 0, "seed": 7, "num_ctx": num_ctx,
                    "num_predict": num_predict * (3 if think else 1)},
    }
    if schema is not None:
        body["format"] = schema
    reply = _post("/api/chat", body, timeout)
    if reply.get("done_reason") == "length":
        raise OllamaUnavailable("la respuesta del modelo se cortó (límite de longitud): no se usa una respuesta incompleta")
    content = (reply.get("message") or {}).get("content", "")
    if schema is None:
        return {"text": content}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        raise OllamaUnavailable("el modelo no devolvió JSON válido") from None


def unload(model: str) -> None:
    """Free the model's memory now instead of waiting for keep_alive to expire."""
    try:
        _post("/api/generate", {"model": model, "keep_alive": 0}, timeout=30)
    except OllamaUnavailable:
        pass


def available(model: str, timeout: float = 3) -> bool:
    try:
        with urllib.request.urlopen(base_url() + "/api/tags", timeout=timeout) as resp:
            tags = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
        return False
    names = {m.get("name") for m in tags.get("models", [])}
    return model in names or f"{model}:latest" in names
