class ValidationError(ValueError):
    """Raised when form level requirements are not satisfied."""


class SensitiveContentError(RuntimeError):
    """Raised when sensitive keywords are detected in user inputs."""
