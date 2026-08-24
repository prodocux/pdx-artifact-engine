from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'compatibility' / 'pdx_prodocux_compatibility_v3.json'
REGISTRY = ROOT / 'skills' / 'registry.sample.json'
SIBLING = (
    ROOT.parent / 'prodocux' / 'compatibility' / 'pdx_prodocux_compatibility_v3.json'
)
FROZEN_V3_MANIFEST_SHA256 = (
    '904935c8eae2d3c8d068f2addecc5a866996fc1cbd9de8b9fde3a500dcac40e7'
)
FROZEN_V2_MANIFEST_SHA256 = (
    'c301aba7442b150b8186ce3b7cd8da99e9470ad0592c13f7f2818d38fd5f378e'
)
FROZEN_V1_MANIFEST_SHA256 = (
    '0b860fc0a5693a96083de1560ff030398e762c9f0c9dc4c0975eceb1d6ca1303'
)
PRODOCUX_COMMIT_A = 'fa35cb05b9c4926ecd3b56dc705a1ecacc55ac30'
PDX_COMMIT_A = 'cccc9a192d1f773d5bf6b8becbe16e41e3164dd2'
_COMMIT_SHA = re.compile(r'^[0-9a-f]{40}$')


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def test_compatibility_v1_and_v2_bytes_remain_frozen() -> None:
    v1_path = ROOT / 'compatibility' / 'pdx_prodocux_compatibility_v1.json'
    v2_path = ROOT / 'compatibility' / 'pdx_prodocux_compatibility_v2.json'
    assert hashlib.sha256(v1_path.read_bytes()).hexdigest() == FROZEN_V1_MANIFEST_SHA256
    assert hashlib.sha256(v2_path.read_bytes()).hexdigest() == FROZEN_V2_MANIFEST_SHA256


def test_compatibility_v3_bytes_are_frozen() -> None:
    assert hashlib.sha256(MANIFEST.read_bytes()).hexdigest() == FROZEN_V3_MANIFEST_SHA256


def test_compatibility_v3_pins_commit_a_and_adapter_tools() -> None:
    manifest = _manifest()
    assert manifest['schema_version'] == 'pdx_prodocux_compatibility_v3'
    assert manifest['status'] == 'frozen'
    assert manifest['compatibility_base'] == {
        'manifest': 'pdx_prodocux_compatibility_v2.json',
        'sha256': FROZEN_V2_MANIFEST_SHA256,
    }

    engine = manifest['pdx_artifact_engine']
    assert engine['distribution'] == 'pdx-artifact-engine'
    assert engine['pin']['commit'] == PDX_COMMIT_A
    assert _COMMIT_SHA.fullmatch(engine['pin']['commit'])
    assert manifest['prodocux']['pin']['commit'] == PRODOCUX_COMMIT_A
    assert _COMMIT_SHA.fullmatch(manifest['prodocux']['pin']['commit'])
    assert manifest['prodocux']['version'] == '0.3.0rc1'

    registry = json.loads(REGISTRY.read_text(encoding='utf-8'))
    names = {entry['name'] for entry in registry['skills']}
    assert set(engine['additive_tools']) <= names

    fixtures = manifest['g1a_conformance']['pdx_fixtures']
    actual_fixtures = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in fixtures
    }
    assert fixtures == actual_fixtures
    assert manifest['g1a_conformance']['status'] == 'frozen'


def test_compatibility_v3_is_byte_identical_with_sibling_when_present() -> None:
    if SIBLING.is_file():
        assert SIBLING.read_bytes() == MANIFEST.read_bytes()
