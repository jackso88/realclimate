"""Serializable envelopes used to exchange events between services."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError


class Envelope(BaseModel):
    """Validated transport metadata and payload for one Kafka message.

    Args:
        message_id: Unique identifier for this message.
        command: Operation name understood by the receiving service.
        payload: JSON-compatible command-specific data.
        correlation_id: Optional ID linking this message to its request.
        reply_to: Optional Kafka topic for a correlated response.
        error: Optional failure detail returned by a service.
        created_at: ISO-8601 timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_id: str = Field(min_length=1)
    command: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    reply_to: str | None = None
    error: str | None = None
    created_at: AwareDatetime

    @classmethod
    def create(
        cls,
        command: str,
        payload: dict[str, Any] | None = None,
        *,
        correlation_id: str | None = None,
        reply_to: str | None = None,
        error: str | None = None,
    ) -> "Envelope":
        """Create an envelope with a fresh ID and UTC creation timestamp.

        Args:
            command: Operation name carried by the message.
            payload: JSON-compatible command data; defaults to an empty dict.
            correlation_id: Optional ID linking this message to a request.
            reply_to: Optional response topic for request/reply messages.
            error: Optional error text associated with a failure response.

        Returns:
            A complete immutable envelope with generated ID and timestamp.
        """
        return cls(
            message_id=str(uuid4()),
            command=command,
            payload=payload or {},
            correlation_id=correlation_id,
            reply_to=reply_to,
            error=error,
            created_at=datetime.now(timezone.utc),
        )

    def encode(self) -> bytes:
        """Serialize the envelope as UTF-8 JSON bytes."""
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def decode(cls, value: bytes) -> "Envelope":
        """Deserialize a Kafka message value into an envelope.

        Args:
            value: UTF-8 JSON bytes from a Kafka record.

        Returns:
            The reconstructed envelope.

        Raises:
            pydantic.ValidationError: If the record does not contain valid JSON
                or does not match the envelope schema and field constraints.
        """
        return cls.model_validate_json(value)
