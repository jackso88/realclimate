"""Kafka client configuration models."""

from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError


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
