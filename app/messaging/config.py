"""Pydantic-backed configuration for Kafka client TLS and SASL settings."""

import os

from pydantic import ValidationError

from app.messaging.models import KafkaClientSettings
from app.messaging.models import KafkaEnvironment


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
