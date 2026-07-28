from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator


def load_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_file(schema_path: Path, data_path: Path) -> list[str]:
    schema = load_json(schema_path)
    data = load_json(data_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: error.path)
    return [f"{list(error.path)}: {error.message}" for error in errors]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a PDX JSON file against a schema.")
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    args = parser.parse_args()

    errors = validate_file(args.schema, args.data)
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

