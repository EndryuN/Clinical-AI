import requests
import json

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.1:8b"
TIMEOUT = 120

def check_ollama() -> bool:
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code != 200:
            return False
        models = [m['name'] for m in resp.json().get('models', [])]
        return any(MODEL.split(':')[0] in m for m in models)
    except requests.ConnectionError:
        return False

def generate(prompt: str) -> str:
    payload = {
        "model": MODEL,
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
