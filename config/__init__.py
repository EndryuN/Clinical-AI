import os
import yaml

_schema = None
_overrides = None

def load_schema() -> dict:
    global _schema
    if _schema is None:
        schema_path = os.path.join(os.path.dirname(__file__), 'field_schema.yaml')
        with open(schema_path, 'r', encoding='utf-8') as f:
            _schema = yaml.safe_load(f)
    return _schema

def get_groups() -> list[dict]:
    return load_schema()['groups']

def get_all_fields() -> list[dict]:
    fields = []
    for group in get_groups():
        for field in group['fields']:
            fields.append({**field, 'group_name': group['name']})
    return fields

def _overrides_path() -> str:
    return os.path.join(os.path.dirname(__file__), 'field_overrides.yaml')

def load_overrides() -> dict:
    """Load field overrides (doctor-defined types and allowed values)."""
    global _overrides
    if _overrides is None:
        try:
            with open(_overrides_path(), 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            _overrides = data.get('overrides', {}) or {}
        except FileNotFoundError:
            _overrides = {}
    return _overrides

def save_overrides(overrides: dict) -> None:
    """Persist field overrides to YAML."""
    global _overrides
    _overrides = overrides
    with open(_overrides_path(), 'w', encoding='utf-8') as f:
        yaml.dump({'overrides': overrides}, f, default_flow_style=False, allow_unicode=True)

def get_field_override(field_key: str) -> dict:
    """Get override for a specific field. Returns {} if none."""
    return load_overrides().get(field_key, {})
