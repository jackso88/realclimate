"""Configuration loading for authenticated Kafka client connections."""

import os

from app.messaging.models import KafkaClientSettings


def load_client_settings(bootstrap_servers: str) -> KafkaClientSettings:
    """Load TLS and SASL/SCRAM settings for Kafka clients from the environment.

    Args:
        bootstrap_servers: Comma-separated broker addresses accepted by
            ``confluent-kafka``.

    Returns:
        Immutable settings DTO for TLS-encrypted connections authenticated
        with SCRAM-SHA-512.

    Raises:
        RuntimeError: If the SASL username, SASL password, or CA certificate
            path is absent from the process environment.
    """
    username = os.getenv("KAFKA_SASL_USERNAME")
    password = os.getenv("KAFKA_SASL_PASSWORD")
    ca_location = os.getenv("KAFKA_SSL_CA_LOCATION")
    if not username or not password or not ca_location:
        raise RuntimeError(
            "KAFKA_SASL_USERNAME, KAFKA_SASL_PASSWORD, and "
            "KAFKA_SSL_CA_LOCATION must be configured"
        )

    return KafkaClientSettings(
        bootstrap_servers=bootstrap_servers,
        username=username,
        password=password,
        ca_location=ca_location,
    )
