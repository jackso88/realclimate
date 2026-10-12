"""Session-based authentication for the uploader's CMS requests."""

from functools import lru_cache
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.uploader.config import load_settings
from app.uploader.exceptions import UploaderAuthenticationError
from app.uploader.models import Settings


logger = logging.getLogger(__name__)


def extract_javascript_redirect(html: str, page_url: str) -> str:
    """Extract and resolve the quoted login redirect from response HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        script_text = script.string or script.get_text()
        _, marker, expression = script_text.partition("window.document.location")
        if not marker:
            continue
        _, assignment, expression = expression.partition("=")
        if not assignment:
            continue
        expression = expression.strip()
        quote = expression[:1]
        if quote not in ("'", '"'):
            continue
        redirect_path, closing_quote, _ = expression[1:].partition(quote)
        if closing_quote:
            return urljoin(page_url, redirect_path)

    raise UploaderAuthenticationError("Could not find a quoted login redirect")


def authenticate(settings: Settings, timeout: float = 30) -> requests.Session:
    """Log in and initialize the CMS context in one cookie-preserving session."""
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

    redirect_url = extract_javascript_redirect(response.text, response.url)
    response = session.get(redirect_url, timeout=timeout)
    response.raise_for_status()

    mosaic_url = urljoin(settings.cms_url + "/", settings.mosaic_path.lstrip("/") + "/")
    response = session.get(
        mosaic_url,
        params=[
            ("act", "main"),
            ("access", settings.access),
            ("ver_id", str(settings.ver_id)),
            ("design_id", str(settings.design_id)),
        ],
        timeout=timeout,
    )
    response.raise_for_status()
    logger.info("Uploader authenticated to the CMS")
    return session


@lru_cache(maxsize=1)
def get_auth_session() -> requests.Session:
    """Return a cached authenticated session for this uploader process."""
    return authenticate(load_settings())


def clear_auth_session_cache() -> None:
    """Discard the cached CMS session."""
    get_auth_session.cache_clear()
