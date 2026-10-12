"""Errors raised by the shared admin authentication service."""


class AdminAuthError(RuntimeError):
    """Base class for admin authentication service errors."""


class AdminLoginError(AdminAuthError):
    """Raised when the CMS login flow cannot establish a session."""
