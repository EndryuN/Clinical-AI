import os
import requests
import json

# Module-level Session for connection pooling
_session = requests.Session()

# Load .env file if present
_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _val = _line.split('=', 1)
                os.environ.setdefault(_key.strip(), _val.strip())

# --- Settings ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OLLAMA_URL = "http://localhost:11434"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
TIMEOUT = 120

# Runtime state
_backend = "claude" if ANTHROPIC_API_KEY else "ollama"
_ollama_model = "qwen3.5:4b"  # default local model

SUGGESTED_MODELS = [
    "qwen2.5:14b-instruct",
    "qwen3:8b",
    "qwen3.5:4b",
    "llama3.1:8b",
    "llama3.2:3b"
]


def get_backend() -> str:
    return _backend


def set_backend(backend: str):
    global _backend
    if backend not in ("claude", "ollama"):
        raise ValueError("Backend must be 'claude' or 'ollama'")
    _backend = backend


def get_ollama_model() -> str:
    return _ollama_model


def set_ollama_model(model: str):
    global _ollama_model
    _ollama_model = model


def list_ollama_models() -> list[str]:
    """Return list of models available in Ollama."""
    try:
        resp = _session.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if resp.status_code == 200:
            return [m['name'] for m in resp.json().get('models', [])]
    except requests.ConnectionError:
        pass
    return []


def check_ollama_available() -> bool:
    """Check if Ollama is running and has at least one model."""
    try:
        resp = _session.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return resp.status_code == 200 and len(resp.json().get('models', [])) > 0
    except requests.ConnectionError:
        return False


def check_claude_available() -> bool:
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
        resp = _session.post(CLAUDE_URL, headers=headers, json=payload, timeout=TIMEOUT)
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
        "model": _ollama_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 8192
        }
    }
    try:
        resp = _session.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json().get('response', '')
    except requests.ConnectionError:
        raise ConnectionError("Cannot connect to Ollama. Is it running? Start with: ollama serve")
    except requests.Timeout:
        raise TimeoutError(f"Ollama request timed out after {TIMEOUT}s")
