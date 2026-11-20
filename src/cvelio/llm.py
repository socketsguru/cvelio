"""Small HTTP clients for the supported model providers. No SDKs required."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import config


class LLMError(Exception):
    pass


@dataclass(frozen=True)
class Provider:
    name: str
    key_env: str
    default_model: str | None
    base_url: str
    base_env: str


PROVIDERS = {
    p.name: p
    for p in (
        Provider("anthropic", "ANTHROPIC_API_KEY", "claude-opus-5-5", "https://api.anthropic.com/v1", "ANTHROPIC_BASE_URL"),
        Provider("gemini", "GEMINI_API_KEY", "gemini-3.8-flash", "https://generativelanguage.googleapis.com/v1beta/models", "GEMINI_BASE_URL"),
        Provider("openrouter", "OPENROUTER_API_KEY", "openrouter/free", "https://openrouter.ai/api/v1", "OPENROUTER_BASE_URL"),
        # Any OpenAI-compatible endpoint, including local ones such as Ollama.
        Provider("openai", "OPENAI_API_KEY", None, "https://api.openai.com/v1", "OPENAI_BASE_URL"),
    )
}


def api_key(p: Provider) -> str:
    return config.secret(p.key_env, p.name)


def _available(p: Provider) -> bool:
    config.load()
    return bool(api_key(p)) or (p.name == "openai" and bool(os.getenv(p.base_env)))


def available() -> list[Provider]:
    """Every provider that has a key right now, in order of preference."""
    return [p for p in PROVIDERS.values() if _available(p)]


def pick_provider(name: str | None = None) -> Provider:
    config.load()
    name = (name or os.getenv("CVELIO_PROVIDER") or "").strip().lower()
    if name:
        if name not in PROVIDERS:
            raise LLMError(f"Unknown provider '{name}'. Choose one of: {', '.join(PROVIDERS)}.")
        if not _available(PROVIDERS[name]):
            raise LLMError(f"No key for '{name}': {PROVIDERS[name].key_env} is not set.")
        return PROVIDERS[name]
    for provider in PROVIDERS.values():
        if _available(provider):
            return provider
    keys = ", ".join(p.key_env for p in PROVIDERS.values())
    raise LLMError(f"No API key found. Set one of {keys} in your environment or in a .env file, "
                   "or point Cvelio at AWS Parameter Store with: make init")


def pick_model(provider: Provider, model: str | None = None) -> str:
    # Most specific wins: the argument, then <PROVIDER>_MODEL, then CVELIO_MODEL, then the default.
    config.load()
    model = model or os.getenv(f"{provider.name.upper()}_MODEL") or os.getenv("CVELIO_MODEL") or provider.default_model
    if not model:
        raise LLMError(f"Provider '{provider.name}' has no default model. Pass --model or set CVELIO_MODEL.")
    return model


def _post(url: str, headers: dict, payload: dict) -> dict:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 529) and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            detail = error.read().decode("utf-8", "replace")[:300]
            raise LLMError(f"The provider answered HTTP {error.code}: {detail}") from None
        except urllib.error.URLError as error:
            raise LLMError(f"Could not reach the provider: {error.reason}") from None
    raise LLMError("The provider kept failing.")


def complete(system: str, user: str, provider: Provider, model: str) -> str:
    key = api_key(provider)
    base = (os.getenv(provider.base_env) or provider.base_url).rstrip("/")
    if provider.name == "anthropic":
        data = _post(
            base + "/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            # Generous on purpose: models that think first spend output tokens before the answer.
            {"model": model, "max_tokens": 24000, "system": system, "messages": [{"role": "user", "content": user}]},
        )
        if data.get("stop_reason") == "max_tokens":
            raise LLMError("The model ran out of output tokens before finishing. Try again.")
        return "".join(block["text"] for block in data["content"] if block["type"] == "text")
    if provider.name == "gemini":
        data = _post(
            f"{base}/{urllib.parse.quote(model, safe='')}:generateContent",
            {"x-goog-api-key": key},
            {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            },
        )
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part["text"] for part in parts if "text" in part and not part.get("thought"))
    data = _post(
        base + "/chat/completions",
        {"Authorization": "Bearer " + key} if key else {},
        {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
    )
    return data["choices"][0]["message"]["content"] or ""


def complete_json(system: str, user: str, provider: Provider, model: str) -> dict:
    """Ask for a JSON object; tolerate code fences and retry once on bad JSON."""
    for attempt in range(2):
        text = complete(system, user, provider, model)
        start, end = text.find("{"), text.rfind("}")
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return data
        except (ValueError, KeyError, IndexError):
            pass
    raise LLMError("The model did not return valid JSON. Try again or use a stronger model.")
