"""Server-side OpenAI adapter; the key is sent only in the Authorization header."""
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from gemini_generator import INSTRUCTION, parse_proposal

# Change with the OPENAI_MODEL environment variable or secret if your account uses another model.
DEFAULT_MODEL = "gpt-5.6-sol"
URL = "https://api.openai.com/v1/chat/completions"


def generate(description, api_key, model=DEFAULT_MODEL):
    """Ask OpenAI for a machine; returns an editor spec validated by automata.import_machine."""
    if not api_key or not api_key.strip():
        raise ValueError("Configure OPENAI_API_KEY first.")
    if not description.strip() or len(description) > 4000:
        raise ValueError("Enter a language description of 1–4000 characters.")
    if not re.fullmatch(r"[a-zA-Z0-9._:-]+", model):
        raise ValueError("Invalid OpenAI model name.")
    body = {"model": model,
            "messages": [{"role": "system", "content": INSTRUCTION},
                         {"role": "user", "content": description}],
            "response_format": {"type": "json_object"}}
    request = Request(URL, data=json.dumps(body).encode(),
                      headers={"Content-Type": "application/json",
                               "Authorization": f"Bearer {api_key.strip()}"})
    try:
        for attempt in range(3):
            try:
                with urlopen(request, timeout=90) as response:
                    raw = response.read(1_000_001)
                break
            except HTTPError as exc:
                if exc.code not in (429, 500, 503) or attempt == 2:
                    raise
                exc.close()
                time.sleep(attempt + 1)
        if len(raw) > 1_000_000:
            raise ValueError("OpenAI response exceeds size limit.")
        choice = json.loads(raw)["choices"][0]
        if choice.get("finish_reason") not in ("stop", None):
            raise ValueError("OpenAI did not finish the response. Simplify the question.")
        return parse_proposal(choice["message"]["content"])
    except HTTPError as exc:
        if exc.code == 401:
            raise ValueError("OpenAI rejected the API key (HTTP 401). Check OPENAI_API_KEY.") from None
        if exc.code == 404:
            raise ValueError(f"OpenAI model '{model}' is unavailable for this account. Set OPENAI_MODEL "
                             "to a model listed on your OpenAI dashboard and restart Streamlit.") from None
        if exc.code == 429:
            raise ValueError("OpenAI rate limit or quota reached (HTTP 429). Check billing and try again.") from None
        raise ValueError(f"OpenAI request failed (HTTP {exc.code}). Check the key, model and quota.") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("Could not reach OpenAI. Check your connection and retry.") from None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise ValueError("OpenAI returned an incomplete or invalid response. Try again.") from None
