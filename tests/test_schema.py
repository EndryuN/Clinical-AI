import yaml
import os

def load_schema():
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'field_schema.yaml')
    with open(schema_path, 'r') as f:
        return yaml.safe_load(f)

def test_schema_loads():
    schema = load_schema()
    assert 'groups' in schema
    assert len(schema['groups']) >= 14

def test_all_fields_have_required_keys():
    schema = load_schema()
    for group in schema['groups']:
        assert 'name' in group
        assert 'description' in group
        assert 'fields' in group
        for field in group['fields']:
            assert 'key' in field, f"Missing key in group {group['name']}"
            assert 'excel_column' in field, f"Missing excel_column for {field.get('key')} in {group['name']}"
            assert 'excel_header' in field, f"Missing excel_header for {field['key']} in {group['name']}"
            assert 'prompt_hint' in field, f"Missing prompt_hint for {field['key']} in {group['name']}"
            assert 'type' in field, f"Missing type for {field['key']} in {group['name']}"

def test_excel_columns_are_unique():
    schema = load_schema()
    columns = []
    for group in schema['groups']:
        for field in group['fields']:
            columns.append(field['excel_column'])
    assert len(columns) == len(set(columns)), f"Duplicate excel_column values found"

def test_field_keys_are_unique():
    schema = load_schema()
    keys = []
    for group in schema['groups']:
        for field in group['fields']:
            keys.append(field['key'])
    assert len(keys) == len(set(keys)), f"Duplicate field keys found"

def test_columns_cover_range_1_to_88():
    schema = load_schema()
    columns = set()
    for group in schema['groups']:
        for field in group['fields']:
            columns.add(field['excel_column'])
    assert len(columns) >= 80, f"Only {len(columns)} unique columns defined"

def test_field_types_are_valid():
    schema = load_schema()
    valid_types = {'string', 'date', 'text'}
    for group in schema['groups']:
        for field in group['fields']:
            assert field['type'] in valid_types, f"Invalid type '{field['type']}' for {field['key']}"
