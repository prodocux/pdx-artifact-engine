"""Verify frozen document contracts using this checkout only."""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path
from jsonschema import Draft202012Validator
import semantic_validator as v
import semantic_cases
ROOT=Path(__file__).resolve().parent

def file_hash(path):
    return hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()

def main():
    manifest=json.loads((ROOT/'contract-freeze.v1.json').read_text(encoding='utf-8'))
    assert manifest['status']=='frozen' and manifest['runtime_available'] is False
    for row in manifest['files']:
        path=(ROOT/row['path']).resolve()
        assert path.is_relative_to(ROOT.resolve())
        assert file_hash(path)==row['sha256_utf8_lf'],row['path']
    schemas=list((ROOT/'schemas').glob('*.json'))
    for path in schemas: Draft202012Validator.check_schema(json.loads(path.read_text()))
    fixtures=json.loads((ROOT/'shape-fixtures.json').read_text())
    for case in fixtures:
        try: v.shape(case['schema'],case['instance']); actual=True
        except v.Invalid: actual=False
        assert actual==case['valid'],case['name']
    semantic_count=semantic_cases.run()
    node=subprocess.run(['node',str(ROOT/'verify_node.mjs')],text=True,capture_output=True)
    assert node.returncode==0,node.stderr
    result=json.loads(node.stdout)
    vectors=json.loads((ROOT/'canonical-vectors.json').read_text())
    positive=[]
    for item in vectors['positive']:
        raw=v.rfc8785.dumps(v.parse(item['raw']))
        positive.append({'name':item['name'],'utf8_hex':raw.hex(),'sha256':hashlib.sha256(raw).hexdigest()})
    assert positive==result['positive']
    for item in vectors['negative']:
        try: v.digest(v.parse(item['raw']))
        except v.Invalid: continue
        raise AssertionError(item['name'])
    print(json.dumps({'schema_documents':len(schemas),'shape_cases':len(fixtures),
        'semantic_cases':semantic_count,'jcs_positive':len(positive),'jcs_negative':len(vectors['negative']),
        'standalone_checkout':True,'runtime_executed':False}))
if __name__=='__main__':main()
