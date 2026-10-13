"""DTOs for admin authentication requests and serializable sessions."""

from dataclasses import dataclass
from http.cookiejar import Cookie
from typing import Any

import requests


@dataclass(frozen=True)
class AdminSettings:
    """Settings required to authenticate a CMS client session."""

    base_url: str
    cms_url: str
    username: str
    password: str
    access: str
    ver_id: int
    design_id: int
    session_cache_ttl_seconds: int = 14400
    login_path: str = "/login"
    mosaic_path: str = "/mosaic"
    form_name: str = "login_form"
    username_field: str = "email"
    password_field: str = "password"


@dataclass(frozen=True)
class SessionSnapshot:
    """JSON-safe subset of a requests.Session needed by worker services."""

    cookies: list[dict[str, Any]]
    headers: dict[str, str]

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
