"""Session-based authentication helpers for the TapTop admin site.

The login endpoint accepts a form POST and responds with HTML containing a
JavaScript redirect. This module checks each HTTP response, follows that
redirect in the same session, and retains the resulting cookies.
"""

from functools import lru_cache
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.downloader.current.config import Settings, load_settings


class AuthenticationError(RuntimeError):
    """Raised when the login page or its redirect cannot be processed."""


def extract_javascript_redirect(html: str, page_url: str) -> str:
    """Find and resolve the ``window.document.location`` URL in HTML scripts.

    Args:
        html: HTML response body containing a JavaScript redirect assignment.
        page_url: URL of the response, used to resolve relative redirect URLs.

    Returns:
        An absolute redirect URL.

    Raises:
        AuthenticationError: If no supported redirect assignment is present.

    Note:
        This handles the simple quoted assignment shown by the site, such as
        ``window.document.location = 'https://.../login?mcc=...'``. It does not
        execute JavaScript or evaluate arbitrary script expressions.
    """
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        script_text = script.string or script.get_text()
        marker = "window.document.location"
        if marker not in script_text:
            continue

        # Keep the remainder after the redirect variable, if it is present.
        _, marker_found, expression = script_text.partition(marker)
        if not marker_found:
            continue
        # partition() returns (text before, separator, text after).
        _, assignment_operator, expression = expression.partition("=")
        if not assignment_operator:
            continue

        expression = expression.strip()
        quote = expression[:1]
        if quote not in ("'", '"'):
            continue

        # Read the quoted URL without evaluating JavaScript from the page.
        url_expression = expression[1:]
        redirect_path, closing_quote, _ = url_expression.partition(quote)
        if not closing_quote:
            continue
        return urljoin(page_url, redirect_path)

    raise AuthenticationError("Could not find a quoted JavaScript login redirect")


def authenticate(settings: Settings, timeout: float = 30) -> requests.Session:
    """Create a session, follow the login redirect, and submit the login form.

    The login endpoint receives the form fields observed in the working browser
    flow. Its HTML response contains a JavaScript redirect, which is then
    followed using the same session. ``raise_for_status`` is called on both
    responses so HTTP error codes fail immediately.

    Args:
        settings: Site URL, credentials, and login form field names.
        timeout: Per-request timeout in seconds.

    Returns:
        An authenticated ``requests.Session`` with its cookies retained.

    Raises:
        requests.HTTPError: If any HTTP request fails.
        AuthenticationError: If the login redirect cannot be found.
    """
    session = requests.Session()
    login_url = urljoin(settings.base_url + "/", settings.login_path.lstrip("/"))

    response = session.post(
        login_url,
        data={
            settings.username_field: settings.username,
            settings.password_field: settings.password,
            "_form": settings.form_name,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    redirected_url = extract_javascript_redirect(response.text, response.url)

    response = session.get(redirected_url, timeout=timeout)
    response.raise_for_status()
    return session


@lru_cache(maxsize=1)
def get_auth_session() -> requests.Session:
    """Return the process-wide cached authenticated session.

    Settings are loaded from ``.env`` on the first call. The returned session
    can be reused for subsequent admin requests, retaining cookies. If the
    server expires the session, call :func:`clear_auth_session_cache` and retry.

    Returns:
        A cached authenticated ``requests.Session``.
    """
    return authenticate(load_settings())


def clear_auth_session_cache() -> None:
    """Discard the cached session so the next call authenticates again."""
    get_auth_session.cache_clear()
