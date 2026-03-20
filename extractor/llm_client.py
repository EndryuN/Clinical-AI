import os
import requests
import json

# Load .env file if present
_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _val = _line.split('=', 1)
                os.environ.setdefault(_key.strip(), _val.strip())

# --- Backend selection ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Ollama settings
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.1:8b"

# Claude settings
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
TIMEOUT = 120

# Runtime backend choice — can be switched via set_backend()
_backend = "claude" if ANTHROPIC_API_KEY else "ollama"


def get_backend() -> str:
    return _backend


def set_backend(backend: str):
    global _backend
    if backend not in ("claude", "ollama"):
        raise ValueError("Backend must be 'claude' or 'ollama'")
    _backend = backend


def check_ollama_available() -> bool:
    """Check if Ollama is running and has the model."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        models = [m['name'] for m in resp.json().get('models', [])]
        return any(OLLAMA_MODEL.split(':')[0] in m for m in models)
    except requests.ConnectionError:
        return False


def check_claude_available() -> bool:
    """Check if Claude API key is set."""
    return bool(ANTHROPIC_API_KEY)


def check_ollama() -> bool:
    """Check if the selected backend is available."""
    if _backend == "claude":
        return check_claude_available()
    return check_ollama_available()


def generate(prompt: str) -> str:
    """Send a prompt to the selected LLM backend."""
    if _backend == "claude":
        return _generate_claude(prompt)
    return _generate_ollama(prompt)


def _generate_claude(prompt: str) -> str:
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 4096,
        "temperature": 0,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    try:
        resp = requests.post(CLAUDE_URL, headers=headers, json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        if content and len(content) > 0:
            return content[0].get("text", "")
        return ""
    except requests.ConnectionError:
        raise ConnectionError("Cannot connect to Claude API. Check your internet connection.")
    except requests.HTTPError as e:
        raise ConnectionError(f"Claude API error: {e.response.status_code} - {e.response.text}")
    except requests.Timeout:
        raise TimeoutError(f"Claude API timed out after {TIMEOUT}s")


def _generate_ollama(prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 8192
        }
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json().get('response', '')
    except requests.ConnectionError:
        raise ConnectionError("Cannot connect to Ollama. Is it running? Start with: ollama serve")
    except requests.Timeout:
        raise TimeoutError(f"Ollama request timed out after {TIMEOUT}s")
