import os
import yaml

_schema = None

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
