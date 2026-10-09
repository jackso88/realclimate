"""Domain-specific exceptions for export processing."""


class AuthenticationError(RuntimeError):
    """Raised when the admin login redirect cannot be processed."""


class ExportNotReadyError(RuntimeError):
    """Raised when the admin queue has no completed ZIP export."""


class ExportArchiveError(RuntimeError):
    """Raised when the downloaded archive is invalid or has no single CSV."""


class AdminFileNotFoundError(LookupError):
    """Raised when the admin file manager has no matching archive filename."""
