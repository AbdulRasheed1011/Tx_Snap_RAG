from __future__ import annotations

from urllib.parse import urlparse, urlunparse

import requests


def generate(
    *,
    url: str,
    model: str,
    prompt: str,
    timeout_seconds: int,
) -> str:
    payload = {"model": model, "prompt": prompt, "stream": False}
    response = requests.post(url, json=payload, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    return (data.get("response") or "").strip()


def is_model_ready(*, url: str, model: str, timeout_seconds: int = 2) -> tuple[bool, str]:
    """Check whether Ollama is reachable and the configured model is available."""
    parsed = urlparse(url)
    tags_url = urlunparse(parsed._replace(path="/api/tags", params="", query="", fragment=""))

    try:
        response = requests.get(tags_url, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # pragma: no cover - network condition
        return False, f"ollama_unreachable: {exc}"

    models = payload.get("models") or []
    names = [str(item.get("name", "")).strip() for item in models]

    if ":" in model:
        found = model in names
    else:
        found = any(name == model or name.startswith(f"{model}:") for name in names)

    if not found:
        return False, f"model_not_downloaded: {model}"
    return True, "ok"
