"""Tests for extracting the JavaScript redirect from the CMS login page."""

import pytest

from app.admin_auth.auth import extract_javascript_redirect
from app.admin_auth.exceptions import AdminLoginError

PAGE_URL = "https://cms.example/login"


def page(*scripts):
    body = "".join(f"<script>{script}</script>" for script in scripts)
    return f"<html><body>{body}</body></html>"


def test_double_quoted_relative_target_is_resolved_against_the_page():
    html = page('window.document.location = "/mosaic/?a=1";')

    redirect = extract_javascript_redirect(html, PAGE_URL)

    assert redirect == "https://cms.example/mosaic/?a=1"


def test_single_quoted_absolute_target_is_returned_as_is():
    html = page("window.document.location='https://other.example/home';")

    redirect = extract_javascript_redirect(html, PAGE_URL)

    assert redirect == "https://other.example/home"


def test_unrelated_scripts_are_skipped():
    html = page("var analytics = 1;", 'window.document.location = "/next";')

    redirect = extract_javascript_redirect(html, PAGE_URL)

    assert redirect == "https://cms.example/next"


def test_method_calls_without_an_assignment_are_not_redirects():
    html = page("window.document.location.reload();")

    with pytest.raises(AdminLoginError, match="redirect"):
        extract_javascript_redirect(html, PAGE_URL)


def test_assignments_of_unquoted_expressions_are_not_supported():
    html = page("window.document.location = destination;")

    with pytest.raises(AdminLoginError, match="redirect"):
        extract_javascript_redirect(html, PAGE_URL)


def test_an_unterminated_string_is_not_a_redirect():
    html = page('window.document.location = "/never-closed;')

    with pytest.raises(AdminLoginError, match="redirect"):
        extract_javascript_redirect(html, PAGE_URL)


def test_a_page_without_scripts_has_no_redirect():
    with pytest.raises(AdminLoginError, match="redirect"):
        extract_javascript_redirect("<html><body>Login failed</body></html>", PAGE_URL)
