"""Custom exceptions for intent operations."""


class IntentValidationError(Exception):
    """Raised when intent data validation fails."""
    pass


class IntentNotFoundError(Exception):
    """Raised when intent is not found."""
    pass


class IntentVersionError(Exception):
    """Raised when versioning operation fails."""
    pass


class CircularReferenceError(Exception):
    """Raised when a circular reference is detected in intent relationships."""
    pass