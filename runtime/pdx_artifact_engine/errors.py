class PDXError(Exception):
    """Base exception for expected PDX runtime failures."""


class RegistryError(PDXError):
    """Raised when a skill registry is invalid."""


class PlanError(PDXError):
    """Raised when a plan is invalid or cannot be dispatched."""


class SkillExecutionError(PDXError):
    """Raised when a skill executor fails."""
