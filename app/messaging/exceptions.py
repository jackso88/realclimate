"""Messaging exceptions shared by Kafka-connected workers."""


class MessagingError(RuntimeError):
    """Base class for Kafka transport and RPC failures."""


class RequestTimeoutError(MessagingError):
    """Raised when no matching Kafka reply arrives before the deadline."""


class RemoteServiceError(MessagingError):
    """Raised when a remote service returns a failed response envelope."""


class RetryableMessageError(MessagingError):
    """Raised when a consumed record must remain uncommitted for retry."""
