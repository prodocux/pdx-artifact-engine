"""Write docs/phase0/fixture-digest-manifest.json from current JSON contract files."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE0 = ROOT / "docs" / "phase0"
SCHEMA = sys.argv[1] if len(sys.argv) > 1 else "pdx_phase0_fixture_digest_manifest_v1"

files: dict[str, str] = {}
for path in sorted(PHASE0.rglob("*.json")):
    rel = path.relative_to(PHASE0).as_posix()
    if rel == "fixture-digest-manifest.json":
        continue
    files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()

manifest = {
    "schema_version": SCHEMA,
    "algorithm": "sha256",
    "canonicalization": "raw UTF-8 file bytes as stored; JSON uses LF; no JSON re-encoding",
    "root": "docs/phase0",
    "files": files,
}
target = PHASE0 / "fixture-digest-manifest.json"
target.write_text(
    json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
    encoding="utf-8",
    newline="\n",
)
print(f"wrote {target} ({len(files)} files)")
