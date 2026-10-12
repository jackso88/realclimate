"""Serializable Kafka message envelopes."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class Envelope:
    """Transport metadata and JSON payload for one request or response."""

    message_id: str
    command: str
    payload: dict[str, Any]
    correlation_id: str | None = None
    reply_to: str | None = None
    error: str | None = None
    created_at: str = ""

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
        """Create an envelope with fresh ID and UTC timestamp."""
        return cls(
            message_id=str(uuid4()),
            command=command,
            payload=payload or {},
            correlation_id=correlation_id,
            reply_to=reply_to,
            error=error,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def encode(self) -> bytes:
        """Serialize the envelope as UTF-8 JSON bytes."""
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    @classmethod
    def decode(cls, value: bytes) -> "Envelope":
        """Deserialize a Kafka message value."""
        return cls(**json.loads(value.decode("utf-8")))
