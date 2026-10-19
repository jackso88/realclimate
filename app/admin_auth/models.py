"""DTOs for admin authentication requests and serializable sessions."""

from http.cookiejar import Cookie
from typing import Any
from urllib.parse import urlsplit

import requests
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)


class AdminSettings(BaseModel):
    """Validated settings required to authenticate a CMS client session.

    Args:
        base_url: Public CMS origin used for login redirects.
        cms_url: CMS API origin and base path.
        username: CMS login name.
        password: CMS password, excluded from object representations.
        access: CMS access parameter.
        ver_id: Positive CMS version identifier.
        design_id: Positive CMS design identifier.
        session_cache_ttl_seconds: Positive cache lifetime in seconds.
        login_path: Relative CMS login endpoint.
        mosaic_path: Relative CMS landing endpoint after login.
        form_name: Login form name submitted to the CMS.
        username_field: Login form field carrying the username.
        password_field: Login form field carrying the password.
        bootstrap_servers: Kafka broker addresses for the auth worker.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    base_url: str = Field(min_length=1)
    cms_url: str = Field(min_length=1)
    username: str = Field(min_length=1)
    password: str = Field(repr=False, min_length=1)
    access: str = Field(min_length=1)
    ver_id: int = Field(gt=0)
    design_id: int = Field(gt=0)
    session_cache_ttl_seconds: int = Field(default=14400, gt=0)
    login_path: str = "/login"
    mosaic_path: str = "/mosaic"
    form_name: str = "login_form"
    username_field: str = "email"
    password_field: str = "password"
    bootstrap_servers: str = Field(default="localhost:9092", min_length=1)

    @field_validator("base_url", "cms_url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        """Require an absolute HTTP or HTTPS URL and remove trailing slashes."""
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute HTTP or HTTPS URL")
        return normalized


class SessionSnapshot(BaseModel):
    """Validated JSON-safe subset of a requests session.

    Args:
        cookies: Cookie attributes required to restore the authenticated session.
        headers: HTTP headers captured from the original session.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cookies: list[dict[str, Any]] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """Convert the snapshot into a JSON-serializable Kafka payload.

        Returns:
            A dictionary containing the cookie records and session headers.
        """
        return {"cookies": self.cookies, "headers": self.headers}

    @classmethod
    def from_session(cls, session: requests.Session) -> "SessionSnapshot":
        """Capture serializable cookie metadata and headers from a session.

        Args:
            session: Authenticated HTTP session whose cookies and headers are
                to be transferred to another service.

        Returns:
            A snapshot that can be serialized and later used to restore a
            process-local :class:`requests.Session`.
        """
        cookies = []
        for cookie in session.cookies:
            cookies.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                    "secure": cookie.secure,
                    "expires": cookie.expires,
                    "rest": cookie._rest,
                }
            )
        return cls(cookies=cookies, headers=dict(session.headers))

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SessionSnapshot":
        """Build a session snapshot from its serialized Kafka payload.

        Args:
            payload: Mapping containing the ``cookies`` and ``headers`` keys.

        Returns:
            A snapshot suitable for reconstructing a requests session.
        """
        return cls(cookies=payload["cookies"], headers=payload["headers"])

    def create_session(self) -> requests.Session:
        """Restore a process-local HTTP session from the saved snapshot.

        Returns:
            A :class:`requests.Session` with the captured headers and cookies.
        """
        session = requests.Session()
        session.headers.update(self.headers)
        for data in self.cookies:
            cookie = Cookie(
                version=0,
                name=data["name"],
                value=data["value"],
                port=None,
                port_specified=False,
                domain=data.get("domain", ""),
                domain_specified=bool(data.get("domain")),
                domain_initial_dot=data.get("domain", "").startswith("."),
                path=data.get("path", "/"),
                path_specified=True,
                secure=bool(data.get("secure", False)),
                expires=data.get("expires"),
                discard=data.get("expires") is None,
                comment=None,
                comment_url=None,
                rest=data.get("rest", {}),
                rfc2109=False,
            )
            session.cookies.set_cookie(cookie)
        return session


class AdminEnvironment(BaseModel):
    """Validated environment values consumed by the admin-auth service.

    Args:
        base_url: Public admin site origin.
        cms_url: CMS API origin and base path.
        username: Admin account name.
        password: Admin account password, hidden from representations.
        access: CMS access parameter.
        ver_id: Positive CMS version ID.
        design_id: Positive CMS design ID.
        session_cache_ttl_seconds: Positive auth-session cache lifetime.
        login_path: Login endpoint path.
        mosaic_path: Post-login CMS path.
        form_name: Login form identifier.
        username_field: Username input name.
        password_field: Password input name.
        bootstrap_servers: Kafka brokers for this worker.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    base_url: str = Field(validation_alias="TAPTOP_BASE_URL", min_length=1)
    cms_url: str = Field(validation_alias="TAPTOP_CMS_URL", min_length=1)
    username: str = Field(validation_alias="TAPTOP_USERNAME", min_length=1)
    password: str = Field(validation_alias="TAPTOP_PASSWORD", min_length=1, repr=False)
    access: str = Field(validation_alias="TAPTOP_ACCESS", min_length=1)
    ver_id: int = Field(validation_alias="TAPTOP_VER_ID", gt=0)
    design_id: int = Field(validation_alias="TAPTOP_DESIGN_ID", gt=0)
    session_cache_ttl_seconds: int = Field(
        default=14400, validation_alias="ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS", gt=0
    )
    login_path: str = Field(default="/login", validation_alias="TAPTOP_LOGIN_PATH")
    mosaic_path: str = Field(default="/mosaic", validation_alias="TAPTOP_MOSAIC_PATH")
    form_name: str = Field(default="login_form", validation_alias="TAPTOP_FORM_NAME")
    username_field: str = Field(
        default="email", validation_alias="TAPTOP_USERNAME_FIELD"
    )
    password_field: str = Field(
        default="password", validation_alias="TAPTOP_PASSWORD_FIELD"
    )
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
