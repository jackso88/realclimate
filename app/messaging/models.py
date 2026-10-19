"""Serializable Kafka message envelopes."""

from datetime import datetime, timezone
from typing import Any, Mapping
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


class KafkaClientSettings(BaseModel):
    """Validated TLS and SASL settings for a Kafka client.

    Args:
        bootstrap_servers: Comma-separated Kafka broker addresses.
        username: SASL/SCRAM username; hidden from model representations.
        password: SASL/SCRAM password; hidden from model representations.
        ca_location: Path to the trusted Kafka CA certificate.
        security_protocol: Kafka transport security protocol, normally SASL_SSL.
        sasl_mechanism: SASL mechanism, normally SCRAM-SHA-512.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    bootstrap_servers: str = Field(min_length=1)
    username: str = Field(repr=False, min_length=1)
    password: str = Field(repr=False, min_length=1)
    ca_location: str = Field(min_length=1)
    security_protocol: str = Field(default="SASL_SSL", min_length=1)
    sasl_mechanism: str = Field(default="SCRAM-SHA-512", min_length=1)

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
        settings = {
            field_name: values.get(property_name)
            for field_name, property_name in property_names.items()
        }
        try:
            return cls.model_validate(settings)
        except ValidationError as error:
            field_name = str(error.errors()[0]["loc"][0])
            property_name = property_names[field_name]
            raise ValueError(
                f"Missing or invalid Kafka property: {property_name}"
            ) from error
