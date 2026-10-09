"""Unit tests for authentication redirect parsing and session caching."""

from unittest import TestCase
from unittest.mock import Mock, patch

from app.downloader.current.auth import (
    AuthenticationError,
    authenticate,
    clear_auth_session_cache,
    extract_javascript_redirect,
    get_auth_session,
)
from app.downloader.current.config import Settings


class RedirectParsingTests(TestCase):
    """Verify JavaScript redirect extraction from HTML documents."""

    def test_extracts_absolute_redirect(self):
        html = "<script>window.document.location = 'https://example.test/login?mcc=123';</script>"
        self.assertEqual(
            extract_javascript_redirect(html, "https://example.test/"),
            "https://example.test/login?mcc=123",
        )

    def test_resolves_relative_redirect(self):
        html = '<script>window.document.location = "/login?mcc=123";</script>'
        self.assertEqual(
            extract_javascript_redirect(html, "https://example.test/start"),
            "https://example.test/login?mcc=123",
        )

    def test_raises_when_redirect_is_missing(self):
        with self.assertRaises(AuthenticationError):
            extract_javascript_redirect("<html></html>", "https://example.test/")


class AuthenticationTests(TestCase):
    """Verify login requests, HTTP errors, and in-memory session caching."""

    def setUp(self):
        clear_auth_session_cache()

    def tearDown(self):
        clear_auth_session_cache()

    @patch("app.downloader.current.auth.requests.Session")
    def test_posts_credentials_then_follows_redirect(self, session_factory):
        session = session_factory.return_value
        initial = Mock(
            url="https://example.test/login",
            text=("<script>window.document.location = '/login?mcc=123';</script>"),
        )
        initial.raise_for_status.return_value = None
        redirected = Mock()
        redirected.raise_for_status.return_value = None
        mosaic_response = Mock()
        mosaic_response.raise_for_status.return_value = None
        session.post.return_value = initial
        session.get.side_effect = [redirected, mosaic_response]

        returned = authenticate(
            Settings(
                cms_url="https://cms.test/",
                base_url="https://example.test",
                username="alice",
                password="pw",
                username_field="email",
                password_field="password",
                form_name="login_form",
                shop_id=1234,
                ver_id=123456789,
                access="u;123123",
                design_id=4321,
            )
        )

        self.assertIs(returned, session)
        session.post.assert_called_once_with(
            "https://example.test/login",
            data={"_form": "login_form", "email": "alice", "password": "pw"},
            timeout=30,
        )
        self.assertEqual(
            session.get.call_args_list[0].args,
            ("https://example.test/login?mcc=123",),
        )
        self.assertEqual(session.get.call_args_list[0].kwargs, {"timeout": 30})
        self.assertEqual(
            session.get.call_args_list[1].args,
            ("https://cms.test/mosaic/",),
        )
        self.assertEqual(
            session.get.call_args_list[1].kwargs,
            {
                "params": [
                    ("act", "main"),
                    ("access", "u;123123"),
                    ("ver_id", "123456789"),
                    ("design_id", "4321"),
                ],
                "timeout": 30,
            },
        )
        initial.raise_for_status.assert_called_once_with()
        redirected.raise_for_status.assert_called_once_with()
        mosaic_response.raise_for_status.assert_called_once_with()

    @patch("app.downloader.current.auth.requests.Session")
    def test_http_error_stops_authentication(self, session_factory):
        session = session_factory.return_value
        failed_response = Mock()
        failed_response.raise_for_status.side_effect = RuntimeError("HTTP error")
        session.post.return_value = failed_response

        with self.assertRaisesRegex(RuntimeError, "HTTP error"):
            authenticate(
                Settings(
                    base_url="https://example.test",
                    username="alice",
                    password="pw",
                    shop_id=1234,
                    ver_id=12345678,
                    access="u;123456",
                    cms_url="https://cms.test/",
                    design_id=4321,
                )
            )

        session.get.assert_not_called()

    @patch("app.downloader.current.auth.requests.Session")
    def test_redirect_http_error_is_raised(self, session_factory):
        session = session_factory.return_value
        login_response = Mock(
            url="https://example.test/login",
            text=("<script>window.document.location = '/login?mcc=123';</script>"),
        )
        login_response.raise_for_status.return_value = None
        redirect_response = Mock()
        redirect_response.raise_for_status.side_effect = RuntimeError("HTTP error")
        session.post.return_value = login_response
        session.get.return_value = redirect_response

        with self.assertRaisesRegex(RuntimeError, "HTTP error"):
            authenticate(
                Settings(
                    base_url="https://example.test",
                    username="alice",
                    password="pw",
                    shop_id=1234,
                    ver_id=1234567,
                    access="u;123456",
                    cms_url="https://cms.test/",
                    design_id=4321,
                )
            )

        redirect_response.raise_for_status.assert_called_once_with()

    @patch("app.downloader.current.auth.authenticate")
    @patch("app.downloader.current.config.load_settings")
    def test_cached_session_authenticates_once(
        self, load_settings_mock, authenticate_mock
    ):
        cached_session = Mock()
        authenticate_mock.return_value = cached_session
        load_settings_mock.return_value = Settings(
            base_url="https://example.test",
            username="alice",
            password="pw",
            shop_id=1234,
            ver_id=12345678,
            access="u;123456",
            cms_url="https://cms.test/",
            design_id=4321,
        )

        first = get_auth_session()
        second = get_auth_session()

        self.assertIs(first, cached_session)
        self.assertIs(second, cached_session)
        authenticate_mock.assert_called_once()
