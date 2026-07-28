from __future__ import annotations

from pathlib import Path

from .errors import PlanError


def ensure_within_directory(root: Path, candidate: Path | str, *, label: str) -> Path:
    """Resolve candidate under root and reject path traversal escapes."""
    root_resolved = root.resolve()
    raw = Path(candidate)
    if raw.is_absolute():
        raise PlanError(f"{label} must be a relative path under the output directory")
    if ".." in raw.parts:
        raise PlanError(f"{label} rejects path traversal ('..'): {candidate}")
    resolved = (root_resolved / raw).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PlanError(f"{label} escapes output directory: {candidate}") from exc
    return resolved
