"""Validated data models for the email notification service."""

import re
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

EMAIL_ADDRESS_PATTERN = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")
REQUIRED_RECIPIENT_COUNT = 2


def _is_email_address(value: str) -> bool:
    """Return whether a string looks like a plain ``local@domain.tld`` address.

    Args:
        value: Candidate email address.
    """
    return EMAIL_ADDRESS_PATTERN.fullmatch(value) is not None


class EmailSettings(BaseModel):
    """Validated SMTP, recipient, and Kafka settings of the email service.

    Values are read from the container's environment variables, so each field
    is validated through an environment-variable alias.

    Args:
        bootstrap_servers: Kafka broker addresses (``KAFKA_BOOTSTRAP_SERVERS``).
        smtp_host: SMTP server host name (``EMAIL_SMTP_HOST``).
        smtp_port: SMTP server port (``EMAIL_SMTP_PORT``).
        smtp_security: Connection security: ``starttls`` upgrades a plain
            connection, ``ssl`` connects over TLS from the start, and ``none``
            sends without encryption (``EMAIL_SMTP_SECURITY``).
        smtp_username: Optional SMTP login; blank means no authentication
            (``EMAIL_SMTP_USERNAME``).
        smtp_password: Optional SMTP password, hidden from model
            representations (``EMAIL_SMTP_PASSWORD``).
        smtp_timeout_seconds: Maximum time for each SMTP network operation
            (``EMAIL_SMTP_TIMEOUT_SECONDS``).
        sender: Address shown in the ``From`` header (``EMAIL_SENDER``).
        recipients: Exactly two distinct destination addresses, given as a
            comma-separated list (``EMAIL_RECIPIENTS``).
    """

    model_config = ConfigDict(
        extra="ignore", str_strip_whitespace=True, populate_by_name=True
    )

    bootstrap_servers: str = Field(
        default="localhost:9092",
        validation_alias="KAFKA_BOOTSTRAP_SERVERS",
        min_length=1,
    )
    smtp_host: str = Field(validation_alias="EMAIL_SMTP_HOST", min_length=1)
    smtp_port: int = Field(
        default=587, validation_alias="EMAIL_SMTP_PORT", ge=1, le=65535
    )
    smtp_security: Literal["starttls", "ssl", "none"] = Field(
        default="starttls", validation_alias="EMAIL_SMTP_SECURITY"
    )
    smtp_username: str | None = Field(
        default=None, validation_alias="EMAIL_SMTP_USERNAME"
    )
    smtp_password: SecretStr | None = Field(
        default=None, validation_alias="EMAIL_SMTP_PASSWORD", repr=False
    )
    smtp_timeout_seconds: float = Field(
        default=15, validation_alias="EMAIL_SMTP_TIMEOUT_SECONDS", gt=0
    )
    sender: str = Field(validation_alias="EMAIL_SENDER")
    recipients: list[str] = Field(validation_alias="EMAIL_RECIPIENTS")

    @field_validator("smtp_username", "smtp_password", mode="before")
    @classmethod
    def blank_credentials_mean_none(cls, value: Any) -> Any:
        """Treat an empty or whitespace-only credential as not configured.

        Args:
            value: Raw username or password from the environment.
        """
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("recipients", mode="before")
    @classmethod
    def split_recipients(cls, value: Any) -> Any:
        """Split a comma-separated recipient string into a list of addresses.

        Args:
            value: Raw ``EMAIL_RECIPIENTS`` value or an already split list.
        """
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("sender")
    @classmethod
    def sender_is_an_address(cls, value: str) -> str:
        """Ensure the sender looks like an email address.

        Args:
            value: Configured sender address.
        """
        if not _is_email_address(value):
            raise ValueError("EMAIL_SENDER must be a valid email address")
        return value

    @field_validator("recipients")
    @classmethod
    def recipients_are_two_distinct_addresses(cls, value: list[str]) -> list[str]:
        """Ensure there are exactly two valid, distinct recipient addresses.

        Args:
            value: Split recipient list.
        """
        if len(value) != REQUIRED_RECIPIENT_COUNT:
            raise ValueError(
                f"EMAIL_RECIPIENTS must contain exactly {REQUIRED_RECIPIENT_COUNT} "
                "addresses"
            )
        invalid = [address for address in value if not _is_email_address(address)]
        if invalid:
            raise ValueError("EMAIL_RECIPIENTS contains an invalid email address")
        if len({address.lower() for address in value}) != len(value):
            raise ValueError("EMAIL_RECIPIENTS must contain distinct addresses")
        return value

    @model_validator(mode="after")
    def credentials_come_in_pairs(self) -> "EmailSettings":
        """Require the SMTP username and password to be set together."""
        if (self.smtp_username is None) != (self.smtp_password is None):
            raise ValueError(
                "EMAIL_SMTP_USERNAME and EMAIL_SMTP_PASSWORD must be set together"
            )
        return self


class DetailedChangesPayload(BaseModel):
    """Payload of a ``detailed_changes`` notification envelope.

    Args:
        changes: Human-readable change descriptions. A missing or ``None``
            value becomes an empty list, and blank entries are dropped.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    changes: list[str] = Field(default_factory=list)

    @field_validator("changes", mode="before")
    @classmethod
    def none_means_no_changes(cls, value: Any) -> Any:
        """Accept an explicit ``None`` as an empty change list.

        Args:
            value: Raw ``changes`` value from the envelope payload.
        """
        return [] if value is None else value

    @field_validator("changes")
    @classmethod
    def drop_blank_changes(cls, value: list[str]) -> list[str]:
        """Remove entries that contain only whitespace.

        Args:
            value: Validated list of change descriptions.
        """
        return [change for change in value if change.strip()]


class EmailNotification(BaseModel):
    """Subject, body, and trace ID of one email to be sent.

    Args:
        subject: Email subject line.
        body: Plain-text email body.
        correlation_id: Pipeline ID carried over from the Kafka envelope, so a
            report can be traced back to the run that produced it.
    """

    model_config = ConfigDict(frozen=True)

    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    correlation_id: str | None = None
