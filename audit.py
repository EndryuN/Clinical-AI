import json
import os
from datetime import datetime

LOG_PATH = os.path.join(os.path.dirname(__file__), 'logs', 'audit.jsonl')

def _ensure_log_dir():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

def log_event(action: str, **kwargs):
    _ensure_log_dir()
    entry = {
        "timestamp": datetime.now().isoformat(timespec='seconds'),
        "action": action,
        **kwargs
    }
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')

def read_log() -> list[dict]:
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, 'r', encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]
