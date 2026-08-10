class DomainConflictError(ValueError):
    """Raised when a domain identity already exists."""


class DomainNotFoundError(ValueError):
    """Raised when a referenced domain object does not exist."""
