class DomainConflictError(ValueError):
    """Raised when a domain identity already exists."""


class DomainNotFoundError(ValueError):
    """Raised when a referenced domain object does not exist."""


class DomainInvalidTransitionError(DomainConflictError):
    """Raised when a workflow state transition is not allowed."""


class DomainRetryLimitError(DomainConflictError):
    """Raised when a research task has exhausted its domain attempts."""
