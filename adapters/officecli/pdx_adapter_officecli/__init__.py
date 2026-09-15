"""Optional OfficeCLI executor adapter."""

from .executor import (
    OfficeCliAdapterError,
    OfficeCliConfig,
    OfficeCliExecutor,
    build_officecli_command,
)

__all__ = [
    "OfficeCliAdapterError",
    "OfficeCliConfig",
    "OfficeCliExecutor",
    "build_officecli_command",
]
