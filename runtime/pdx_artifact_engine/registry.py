from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cli.validate import validate_file
from .errors import RegistryError


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    version: str
    domain: str
    description: str
    entrypoint: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    artifacts: tuple[str, ...]
    failure_codes: tuple[dict[str, Any], ...]
    verification_hooks: tuple[str, ...]
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SkillDefinition":
        required = (
            "name",
            "version",
            "domain",
            "description",
            "entrypoint",
            "inputs",
            "outputs",
            "failure_codes",
        )
        missing = [field for field in required if field not in value or value[field] in (None, "")]
        if missing:
            raise RegistryError(f"Skill is missing required fields: {', '.join(missing)}")
        if not isinstance(value["inputs"], list) or not isinstance(value["outputs"], list):
            raise RegistryError("Skill inputs/outputs must be arrays")
        if not isinstance(value["failure_codes"], list) or not value["failure_codes"]:
            raise RegistryError("Skill failure_codes must be a non-empty array")
        artifacts = value.get("artifacts")
        if artifacts is None:
            artifacts = value["outputs"]
        if not isinstance(artifacts, list):
            raise RegistryError("Skill artifacts must be an array")
        return cls(
            name=str(value["name"]),
            version=str(value["version"]),
            domain=str(value["domain"]),
            description=str(value["description"]),
            entrypoint=str(value["entrypoint"]),
            inputs=tuple(value["inputs"]),
            outputs=tuple(value["outputs"]),
            artifacts=tuple(artifacts),
            failure_codes=tuple(value["failure_codes"]),
            verification_hooks=tuple(value.get("verification_hooks", [])),
            input_schema=value.get("input_schema"),
            output_schema=value.get("output_schema"),
        )


class SkillRegistry:
    def __init__(self, skills: list[SkillDefinition]) -> None:
        names = [skill.name for skill in skills]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise RegistryError(f"Duplicate skill names: {', '.join(duplicates)}")
        self._skills = {skill.name: skill for skill in skills}

    @classmethod
    def load(cls, path: Path, schema_path: Path | None = None) -> "SkillRegistry":
        if schema_path is not None:
            errors = validate_file(schema_path, path)
            if errors:
                raise RegistryError(
                    "Invalid skill registry:\n" + "\n".join(f"- {error}" for error in errors)
                )
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(f"Cannot load registry {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise RegistryError("Registry root must be an object")
        if value.get("schema_version") != "pdx_skill_registry_v0":
            raise RegistryError("Unsupported skill registry schema_version")
        raw_skills = value.get("skills")
        if not isinstance(raw_skills, list):
            raise RegistryError("Registry 'skills' must be an array")
        if not all(isinstance(skill, dict) for skill in raw_skills):
            raise RegistryError("Each registry skill must be an object")
        return cls([SkillDefinition.from_dict(skill) for skill in raw_skills])

    def get(self, name: str) -> SkillDefinition:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise RegistryError(f"Unknown skill: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._skills))
