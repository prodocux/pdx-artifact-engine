"""Frozen public contract checks require only this repository checkout."""
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT=Path(__file__).resolve().parents[1]/'docs'/'external-operations'

def test_public_contract_freeze_hashes():
    record=json.loads((ROOT/'contract-freeze.v1.json').read_text(encoding='utf-8'))
    assert record['status']=='frozen' and record['runtime_available'] is False
    assert len(record['files'])==len({x['path'] for x in record['files']})
    for item in record['files']:
        path=(ROOT/item['path']).resolve()
        assert path.is_relative_to(ROOT.resolve())
        data=path.read_text(encoding='utf-8').encode('utf-8')
        assert hashlib.sha256(data).hexdigest()==item['sha256_utf8_lf'],item['path']

def test_public_contract_schemas_and_local_references():
    schemas={}
    for folder in ('dependencies','schemas'):
        for path in (ROOT/folder).glob('*.json'):
            obj=json.loads(path.read_text(encoding='utf-8'))
            Draft202012Validator.check_schema(obj)
            schemas[obj['$id']]=obj
    registry=Registry()
    for key,obj in schemas.items(): registry=registry.with_resource(key,Resource.from_contents(obj))
    for case in json.loads((ROOT/'shape-fixtures.json').read_text()):
        validator=Draft202012Validator({'$ref':case['schema']},registry=registry)
        assert validator.is_valid(case['instance'])==case['valid'],case['name']
    mapping=json.loads((ROOT/'route-mapping.json').read_text())
    assert len(mapping['routes'])==len({r['operation'] for r in mapping['routes']})
    for route in mapping['routes']:
        for name in ('request_schema','success_schema'):
            reference=route[name]
            if reference:
                uri,_,fragment=reference.partition('#')
                obj=schemas[uri]
                for part in fragment.strip('/').split('/') if fragment else []:obj=obj[part]
