"""Validated settings for the database service."""

from pydantic import BaseModel, ConfigDict, Field


class DbServiceSettings(BaseModel):
    """Environment settings for the database worker.

    Args:
        bootstrap_servers: Comma-separated Kafka broker addresses.
        database_url: PostgreSQL connection URL.
    """

    model_config = ConfigDict(
        extra="ignore", str_strip_whitespace=True, populate_by_name=True
    )

    bootstrap_servers: str = Field(
        default="localhost:9092",
        validation_alias="KAFKA_BOOTSTRAP_SERVERS",
        min_length=1,
    )
    database_url: str = Field(validation_alias="DATABASE_URL", min_length=1)
