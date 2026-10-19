"""Pydantic-backed configuration for Kafka client TLS and SASL settings."""

import os

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.messaging.models import KafkaClientSettings


class KafkaEnvironment(BaseModel):
    """Validated Kafka credentials and certificate paths from the environment.

    Args:
        username: SASL/SCRAM username.
        password: SASL/SCRAM password; hidden from representations.
        ca_location: File path to the trusted Kafka CA bundle.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    username: str = Field(validation_alias="KAFKA_SASL_USERNAME", min_length=1)
    password: str = Field(
        validation_alias="KAFKA_SASL_PASSWORD", min_length=1, repr=False
    )
    ca_location: str = Field(validation_alias="KAFKA_SSL_CA_LOCATION", min_length=1)


def load_client_settings(bootstrap_servers: str) -> KafkaClientSettings:
    """Load and validate settings for encrypted Kafka client connections.

    Args:
        bootstrap_servers: Broker addresses from the owning service config.

    Returns:
        Validated TLS/SASL configuration for a ``confluent-kafka`` client.

    Raises:
        RuntimeError: If a required SASL or CA setting is missing or invalid.
    """
    values = dict(os.environ)
    required_names = (
        "KAFKA_SASL_USERNAME",
        "KAFKA_SASL_PASSWORD",
        "KAFKA_SSL_CA_LOCATION",
    )
    if any(not values.get(name) for name in required_names):
        raise RuntimeError(
            "KAFKA_SASL_USERNAME, KAFKA_SASL_PASSWORD, and "
            "KAFKA_SSL_CA_LOCATION must be configured"
        )
    try:
        config = KafkaEnvironment.model_validate(values)
    except ValidationError as error:
        raise RuntimeError(f"Invalid Kafka client settings: {error}") from error
    return KafkaClientSettings(
        bootstrap_servers=bootstrap_servers,
        username=config.username,
        password=config.password,
        ca_location=config.ca_location,
    )
