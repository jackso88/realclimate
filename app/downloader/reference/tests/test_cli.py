"""Unit tests for the CLI entry point."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.downloader.reference.cli import main


class TestMain:
    """Tests for :func:`main`."""

    def test_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "GOOGLE_SHEET_URL=https://docs.google.com/spreadsheets/d/sheet-id/edit",
                    "GOOGLE_SHEET_NAME=Data",
                    "GOOGLE_CREDENTIALS_FILE=creds.json",
                    "GOOGLE_TOKEN_FILE=token.json",
                    f"GOOGLE_OUTPUT_FILE={tmp_path / 'out.csv'}",
                ]
            ),
            encoding="utf-8",
        )
        for key in (
            "GOOGLE_SHEET_URL",
            "GOOGLE_SHEET_NAME",
            "GOOGLE_CREDENTIALS_FILE",
            "GOOGLE_TOKEN_FILE",
            "GOOGLE_OUTPUT_FILE",
        ):
            monkeypatch.delenv(key, raising=False)

        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = [
            ["col1", "col2"],
            ["a", "b"],
        ]
        mock_spreadsheet = MagicMock()
        mock_spreadsheet.worksheet.return_value = mock_worksheet
        mock_client = MagicMock()
        mock_client.open_by_key.return_value = mock_spreadsheet

        with (
            patch(
                "app.downloader.reference.cli.load_settings",
                return_value=MagicMock(
                    spreadsheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit",
                    sheet_name="Data",
                    credentials_file=tmp_path / "creds.json",
                    token_file=tmp_path / "token.json",
                    output_file=tmp_path / "out.csv",
                ),
            ),
            patch(
                "app.downloader.reference.cli.get_credentials",
                return_value=MagicMock(),
            ),
            patch(
                "app.downloader.reference.cli.gspread.authorize",
                return_value=mock_client,
            ),
            patch(
                "app.downloader.reference.cli.save_data_to_csv"
            ) as save_mock,
        ):
            exit_code = main()

        assert exit_code == 0
        mock_client.open_by_key.assert_called_once_with("sheet-id")
        mock_spreadsheet.worksheet.assert_called_once_with("Data")
        save_mock.assert_called_once()
        args, _ = save_mock.call_args
        assert args[1] == [["col1", "col2"], ["a", "b"]]

    def test_config_error_returns_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with patch(
            "app.downloader.reference.cli.load_settings",
            side_effect=FileNotFoundError(".env missing"),
        ):
            assert main() == 1

    def test_credentials_error_returns_1(self) -> None:
        with (
            patch(
                "app.downloader.reference.cli.load_settings",
                return_value=MagicMock(
                    spreadsheet_url="id",
                    sheet_name="S",
                    credentials_file=Path("missing.json"),
                    token_file=Path("token.json"),
                    output_file=Path("out.csv"),
                ),
            ),
            patch(
                "app.downloader.reference.cli.get_credentials",
                side_effect=FileNotFoundError("no creds"),
            ),
        ):
            assert main() == 1
