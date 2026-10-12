"""Create an authenticated CMS session and convert it into a DTO."""

import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.admin_auth.exceptions import AdminLoginError
from app.admin_auth.models import AdminSettings, SessionSnapshot

logger = logging.getLogger(__name__)


def extract_javascript_redirect(html: str, page_url: str) -> str:
    """Extract the quoted JavaScript location used by the CMS login page."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        _, marker, expression = text.partition("window.document.location")
        if not marker:
            continue
        _, assignment, expression = expression.partition("=")
        if not assignment:
            continue
        expression = expression.strip()
        quote = expression[:1]
        if quote not in ("'", '"'):
            continue
        target, closing_quote, _ = expression[1:].partition(quote)
        if closing_quote:
            return urljoin(page_url, target)
    raise AdminLoginError("Could not find the CMS login redirect")


def create_session_snapshot(
    settings: AdminSettings,
    timeout: float = 30,
) -> SessionSnapshot:
    """Authenticate once and return serializable cookies and request headers."""
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

    logger.info("Created authenticated admin session snapshot")
    return SessionSnapshot.from_session(session)
