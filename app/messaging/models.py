"""Serializable Kafka message envelopes."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Mapping
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
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def encode(self) -> bytes:
        """Serialize the envelope as UTF-8 JSON bytes."""
        return json.dumps(asdict(self), ensure_ascii=False).encode("utf-8")

    @classmethod
    def decode(cls, value: bytes) -> "Envelope":
        """Deserialize a Kafka message value into an envelope.

        Args:
            value: UTF-8 JSON bytes from a Kafka record.

        Returns:
            The reconstructed envelope.

        Raises:
            UnicodeDecodeError: If the record is not UTF-8 encoded.
            json.JSONDecodeError: If the record does not contain valid JSON.
            TypeError: If the JSON object does not match the envelope fields.
        """
        return cls(**json.loads(value.decode("utf-8")))


@dataclass(frozen=True)
class KafkaClientSettings:
    """Connection and authentication settings for a Kafka client.

    The password is excluded from the generated representation to reduce the
    chance of exposing it through debug logs.
    """

    bootstrap_servers: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    ca_location: str
    security_protocol: str = "SASL_SSL"
    sasl_mechanism: str = "SCRAM-SHA-512"

    def to_dict(self) -> dict[str, object]:
        """Serialize the settings into a ``confluent-kafka`` config mapping.

        Returns:
            A new mapping of Kafka client property names to configured values.
            It includes the SASL password and must be handled as secret data.
        """
        return {
            "bootstrap.servers": self.bootstrap_servers,
            "security.protocol": self.security_protocol,
            "sasl.mechanism": self.sasl_mechanism,
            "sasl.username": self.username,
            "sasl.password": self.password,
            "ssl.ca.location": self.ca_location,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> "KafkaClientSettings":
        """Deserialize a ``confluent-kafka`` config mapping into this DTO.

        Args:
            values: Mapping containing the bootstrap address, security
                protocol, SASL mechanism and credentials, and CA certificate
                path under their ``confluent-kafka`` property names.

        Returns:
            An immutable settings DTO.

        Raises:
            ValueError: If a required property is missing, empty, or not a
                string.
        """
        property_names = {
            "bootstrap_servers": "bootstrap.servers",
            "security_protocol": "security.protocol",
            "sasl_mechanism": "sasl.mechanism",
            "username": "sasl.username",
            "password": "sasl.password",
            "ca_location": "ssl.ca.location",
        }
        settings: dict[str, str] = {}
        for field_name, property_name in property_names.items():
            value = values.get(property_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"Missing or invalid Kafka property: {property_name}")
            settings[field_name] = value

        return cls(**settings)
