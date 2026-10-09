import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.downloader.current.config import load_settings


class SettingsTests(TestCase):
    """Verify required configuration values are loaded and validated."""

    @patch.dict(
        os.environ,
        {
            "TAPTOP_BASE_URL": "https://dashboard.test.pro/",
            "TAPTOP_USERNAME": "user",
            "TAPTOP_PASSWORD": "secret",
            "TAPTOP_SHOP_ID": "1234",
            "TAPTOP_VER_ID": "12345678",
            "TAPTOP_ACCESS": "u;12345678",
            "TAPTOP_DESIGN_ID": "4321",
            "TAPTOP_CMS_URL": "https://test.pro",
        },
        clear=True,
    )
    def test_loads_settings_and_removes_trailing_slash(self):
        settings = load_settings(env_file="/path/that/does/not/exist")
        self.assertEqual(settings.base_url, "https://dashboard.test.pro")
        self.assertEqual(settings.cms_url, "https://test.pro")
        self.assertEqual(settings.username, "user")

    @patch.dict(os.environ, {}, clear=True)
    def test_requires_credentials(self):
        with self.assertRaises(ValueError):
            load_settings(env_file="/path/that/does/not/exist")

    @patch.dict(
        os.environ,
        {
            "TAPTOP_BASE_URL": "https://dashboard.test.pro",
            "TAPTOP_USERNAME": "user",
            "TAPTOP_PASSWORD": "secret",
            "TAPTOP_VER_ID": "12345678",
            "TAPTOP_ACCESS": "u;12345678",
            "TAPTOP_DESIGN_ID": "4321",
        },
        clear=True,
    )
    def test_requires_shop_id(self):
        with self.assertRaisesRegex(ValueError, "TAPTOP_SHOP_ID"):
            load_settings(env_file="/path/that/does/not/exist")

    @patch.dict(
        os.environ,
        {
            "TAPTOP_BASE_URL": "https://dashboard.test.pro",
            "TAPTOP_USERNAME": "user",
            "TAPTOP_PASSWORD": "secret",
            "TAPTOP_SHOP_ID": "1234",
            "TAPTOP_VER_ID": "12345678",
            "TAPTOP_ACCESS": "u;12345678",
            "TAPTOP_DESIGN_ID": "4321",
            "TAPTOP_LOGIN_PATH": "/custom-login",
            "TAPTOP_USERNAME_FIELD": "account_email",
            "TAPTOP_PASSWORD_FIELD": "account_password",
            "TAPTOP_FORM_NAME": "admin_login",
            "TAPTOP_CMS_URL": "https://test.pro",
        },
        clear=True,
    )
    def test_loads_optional_login_form_settings(self):
        settings = load_settings(env_file="/path/that/does/not/exist")

        self.assertEqual(settings.login_path, "/custom-login")
        self.assertEqual(settings.username_field, "account_email")
        self.assertEqual(settings.password_field, "account_password")
        self.assertEqual(settings.form_name, "admin_login")

    @patch.dict(
        os.environ,
        {
            "TAPTOP_BASE_URL": "https://dashboard.test.pro",
            "TAPTOP_USERNAME": "user",
            "TAPTOP_PASSWORD": "secret",
            "TAPTOP_SHOP_ID": "1234",
            "TAPTOP_VER_ID": "12345678",
            "TAPTOP_ACCESS": "u;12345678",
            "TAPTOP_DESIGN_ID": "4321",
            "TAPTOP_CMS_URL": "https://test.pro",
        },
        clear=True,
    )
    def test_loads_export_settings(self):
        settings = load_settings(env_file="/path/that/does/not/exist")

        self.assertEqual(settings.shop_id, 1234)
        self.assertEqual(settings.ver_id, 12345678)
        self.assertEqual(settings.access, "u;12345678")
        self.assertEqual(settings.design_id, 4321)

    @patch.dict(
        os.environ,
        {
            "TAPTOP_BASE_URL": "https://test.pro",
            "TAPTOP_USERNAME": "user",
            "TAPTOP_PASSWORD": "secret",
            "TAPTOP_SHOP_ID": "not-a-number",
            "TAPTOP_VER_ID": "12345678",
            "TAPTOP_ACCESS": "u;12345678",
            "TAPTOP_DESIGN_ID": "not-a-number",
            "TAPTOP_CMS_URL": "https://test.pro",
        },
        clear=True,
    )
    def test_rejects_non_integer_export_ids(self):
        with self.assertRaisesRegex(ValueError, "TAPTOP_SHOP_ID must be an integer"):
            load_settings(env_file="/path/that/does/not/exist")

    @patch.dict(
        os.environ,
        {
            "TAPTOP_BASE_URL": "https://dashboard.test.pro",
            "TAPTOP_USERNAME": "user",
            "TAPTOP_PASSWORD": "secret",
            "TAPTOP_SHOP_ID": "1234",
            "TAPTOP_VER_ID": "12345678",
            "TAPTOP_ACCESS": "u;12345678",
            "TAPTOP_CMS_URL": "https://test.pro",
        },
        clear=True,
    )
    def test_requires_design_id(self):
        with self.assertRaisesRegex(ValueError, "TAPTOP_DESIGN_ID"):
            load_settings(env_file="/path/that/does/not/exist")

    @patch.dict(
        os.environ,
        {
            "TAPTOP_BASE_URL": "https://dashboard.test.pro",
            "TAPTOP_USERNAME": "user",
            "TAPTOP_PASSWORD": "secret",
            "TAPTOP_SHOP_ID": "1234",
            "TAPTOP_VER_ID": "12345678",
            "TAPTOP_ACCESS": "u;12345678",
            "TAPTOP_DESIGN_ID": "not-a-number",
            "TAPTOP_CMS_URL": "https://test.pro",
        },
        clear=True,
    )
    def test_rejects_non_integer_design_id(self):
        with self.assertRaisesRegex(ValueError, "TAPTOP_DESIGN_ID must be an integer"):
            load_settings(env_file="/path/that/does/not/exist")

    @patch("app.downloader.current.config.load_dotenv")
    @patch.dict(
        os.environ,
        {
            "TAPTOP_BASE_URL": "https://dashboard.test.pro",
            "TAPTOP_USERNAME": "environment-user",
            "TAPTOP_PASSWORD": "environment-secret",
            "TAPTOP_SHOP_ID": "1234",
            "TAPTOP_VER_ID": "12345678",
            "TAPTOP_ACCESS": "u;12345678",
            "TAPTOP_DESIGN_ID": "4321",
            "TAPTOP_CMS_URL": "https://test.pro",
        },
        clear=True,
    )
    def test_environment_variables_take_precedence(self, load_dotenv_mock):
        def populate_dotenv_values(*args, **kwargs):
            # Simulate dotenv loading without overriding existing process values.
            os.environ.setdefault("TAPTOP_USERNAME", "dotenv-user")
            os.environ.setdefault("TAPTOP_PASSWORD", "dotenv-secret")

        load_dotenv_mock.side_effect = populate_dotenv_values

        settings = load_settings(env_file=".env")

        self.assertEqual(settings.username, "environment-user")
        self.assertEqual(settings.password, "environment-secret")
        load_dotenv_mock.assert_called_once_with(dotenv_path=".env", override=False)

    @patch("app.downloader.current.config.load_dotenv")
    @patch.dict(
        os.environ,
        {
            "TAPTOP_SHOP_ID": "1234",
            "TAPTOP_USERNAME": "user",
            "TAPTOP_DESIGN_ID": "4321",
            "TAPTOP_VER_ID": "12345678",
            "TAPTOP_PASSWORD": "secret",
            "TAPTOP_ACCESS": "u;12345678",
            "TAPTOP_CMS_URL": "https://test.pro",
            "TAPTOP_BASE_URL": "https://dashboard.test.pro",
        },
        clear=True,
    )
    def test_default_dotenv_path_is_project_root(self, load_dotenv_mock):
        load_settings()

        expected_path = Path(__file__).resolve().parents[4] / ".env"
        load_dotenv_mock.assert_called_once_with(
            dotenv_path=expected_path,
            override=False,
        )

    @patch.dict(
        os.environ,
        {
            "TAPTOP_BASE_URL": "test.pro",
            "TAPTOP_USERNAME": "user",
            "TAPTOP_PASSWORD": "secret",
            "TAPTOP_SHOP_ID": "1234",
            "TAPTOP_VER_ID": "12345678",
            "TAPTOP_ACCESS": "u;12345678",
            "TAPTOP_DESIGN_ID": "4321",
            "TAPTOP_CMS_URL": "https://test.pro",
        },
        clear=True,
    )
    def test_rejects_base_url_without_http_scheme(self):
        with self.assertRaisesRegex(ValueError, "TAPTOP_BASE_URL must start"):
            load_settings(env_file="/path/that/does/not/exist")
