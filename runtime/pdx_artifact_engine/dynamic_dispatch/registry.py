"""Trusted live registry for governed dispatch tools."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import rfc8785


@dataclass(frozen=True)
class DispatchTool:
    frozen_definition: dict[str, Any]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    executor: Callable[[dict[str, Any]], dict[str, Any]]

    def __post_init__(self) -> None:
        if hashlib.sha256(rfc8785.dumps(self.input_schema)).hexdigest() != self.frozen_definition["input_schema_digest"]:
            raise ValueError("dispatch input schema digest mismatch")
        if hashlib.sha256(rfc8785.dumps(self.output_schema)).hexdigest() != self.frozen_definition["output_schema_digest"]:
            raise ValueError("dispatch output schema digest mismatch")


class DispatchToolRegistry:
    def __init__(self, tools: list[DispatchTool]) -> None:
        names = [tool.frozen_definition["name"] for tool in tools]
        if len(names) != len(set(names)):
            raise ValueError("duplicate dispatch tool")
        self._tools = dict(zip(names, tools, strict=True))

    def get(self, name: str) -> DispatchTool | None:
        return self._tools.get(name)
