"""Pick an AI model automatically: whichever provider and model actually works.

Order: OpenAI (if OPENAI_API_KEY is set), then Gemini (if GEMINI_API_KEY is set).
For each provider the account's model list is fetched once and ranked; a model you
name in OPENAI_MODEL / GEMINI_MODEL is tried first. If a model is unavailable or
fails, the next one is tried; key, permission and quota errors skip to the next
provider. Keys are only ever sent in request headers.
"""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import gemini_generator
import openai_generator

MODELS_PER_PROVIDER = 3
_cache = {}

OPENAI_SKIP = ("audio", "realtime", "tts", "transcribe", "image", "search", "embedding",
               "instruct", "codex", "cyber", "oss", "moderation", "dall", "whisper", "sora")
GEMINI_SKIP = ("image", "tts", "embedding", "live", "audio", "native", "vision", "aqa",
               "robotics", "computer-use", "gemma")
FATAL = ("rejected the api key", "http 401", "http 403", "quota", "http 429", "configure")


def _get_json(url, headers):
    with urlopen(Request(url, headers=headers), timeout=20) as response:
        return json.loads(response.read(2_000_001))


def _version(name):
    m = re.search(r"(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def rank_openai(ids):
    """Newest GPT chat models first; full size before mini before nano; aliases before snapshots."""
    usable = [i for i in ids if i.startswith("gpt-") and not any(t in i for t in OPENAI_SKIP)]

    def key(i):
        size = 2 if "nano" in i else 1 if "mini" in i else 0
        dated = bool(re.search(r"\d{4}-\d{2}-\d{2}", i))
        return (-_version(i), size, dated, "preview" in i, i)
    return sorted(usable, key=key)


def rank_gemini(models):
    """Newest Gemini text models first; flash, then pro, then flash-lite; stable before preview."""
    usable = []
    for m in models:
        name = m.get("name", "").split("/")[-1]
        if (name.startswith("gemini-") and "generateContent" in m.get("supportedGenerationMethods", [])
                and not any(t in name for t in GEMINI_SKIP)):
            usable.append(name)

    def key(n):
        tier = 2 if "lite" in n else 0 if "flash" in n else 1
        return (-_version(n), tier, "preview" in n or "exp" in n, n)
    return sorted(usable, key=key)


def openai_models(api_key):
    cache_key = ("openai", hash(api_key))
    if cache_key not in _cache:
        try:
            data = _get_json("https://api.openai.com/v1/models",
                             {"Authorization": f"Bearer {api_key}"})
            _cache[cache_key] = rank_openai([m["id"] for m in data.get("data", [])])
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError):
            _cache[cache_key] = [openai_generator.DEFAULT_MODEL]
    return _cache[cache_key]


def gemini_models(api_key):
    cache_key = ("gemini", hash(api_key))
    if cache_key not in _cache:
        try:
            data = _get_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
                             {"x-goog-api-key": api_key})
            _cache[cache_key] = rank_gemini(data.get("models", [])) or [gemini_generator.DEFAULT_MODEL]
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError):
            _cache[cache_key] = [gemini_generator.DEFAULT_MODEL]
    return _cache[cache_key]


def providers(openai_key="", gemini_key="", openai_model="", gemini_model=""):
    """[(name, key, model list, generate)] for every provider that has a key."""
    out = []
    if openai_key:
        models = openai_models(openai_key)
        if openai_model:
            models = [openai_model] + [m for m in models if m != openai_model]
        out.append(("OpenAI", openai_key, models, openai_generator.generate))
    if gemini_key:
        models = gemini_models(gemini_key)
        if gemini_model:
            models = [gemini_model] + [m for m in models if m != gemini_model]
        out.append(("Gemini", gemini_key, models, gemini_generator.generate))
    return out


def auto_generate(text, available):
    """Try each provider and model in turn; return (spec, 'Provider · model')."""
    errors = []
    for name, key, models, generate in available:
        for model in models[:MODELS_PER_PROVIDER]:
            try:
                return generate(text, key, model), f"{name} · {model}"
            except ValueError as exc:
                message = str(exc)
                errors.append(f"{name} {model}: {message}")
                if any(t in message.lower() for t in FATAL):
                    break                      # key or quota problem: other models won't help
                if "unavailable" not in message.lower() and "http 404" not in message.lower() \
                        and "http 400" not in message.lower():
                    break                      # the model answered but badly: try the next provider
    raise ValueError("No AI model could answer. " + " | ".join(errors[-3:]))
