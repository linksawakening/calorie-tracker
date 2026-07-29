"""Tests for the Garmin API client module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from caltrack.db import get_connection
from caltrack.garmin import sync_garmin_day

API_KEY_ENV = {"GARMIN_SYNC_API_KEY": "test-key-1234"}


class TestSyncGarminDay:
    """Tests for the API-based Garmin sync."""

    @patch("caltrack.garmin.httpx.get")
    @patch.dict("os.environ", API_KEY_ENV)
    def test_sync_success(self, mock_get: MagicMock, tmp_path) -> None:
        """Test successful sync from the remote service."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "date": "2026-07-28",
            "available": True,
            "active_calories": 450,
            "bmr_calories": 1850,
            "total_calories": 2300,
            "steps": 8000,
            "floors": 10,
            "intensity_minutes": 30,
            "resting_hr": 60,
        }
        mock_get.return_value = mock_resp

        conn = get_connection(tmp_path / "test.db")
        rec = sync_garmin_day(conn, "2026-07-28")

        assert rec is not None
        assert rec.active_calories == 450
        assert rec.bmr_calories == 1850
        assert rec.total_calories == 2300
        assert rec.steps == 8000

    @patch("caltrack.garmin.httpx.get")
    @patch.dict("os.environ", API_KEY_ENV)
    def test_sync_no_data(self, mock_get: MagicMock, tmp_path) -> None:
        """Test sync when no data is available for the day."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "date": "2026-07-28",
            "available": False,
        }
        mock_get.return_value = mock_resp

        conn = get_connection(tmp_path / "test.db")
        rec = sync_garmin_day(conn, "2026-07-28")
        assert rec is None

    @patch("caltrack.garmin.httpx.get")
    @patch.dict("os.environ", API_KEY_ENV)
    def test_sync_service_error(self, mock_get: MagicMock, tmp_path) -> None:
        """Test sync when the service returns an error."""
        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 502
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "502", request=MagicMock(), response=mock_resp
        )
        mock_get.return_value = mock_resp

        conn = get_connection(tmp_path / "test.db")
        rec = sync_garmin_day(conn, "2026-07-28")
        assert rec is None


class TestCheckServiceHealth:
    """Tests for the health check."""

    @patch("caltrack.garmin.httpx.get")
    def test_healthy(self, mock_get: MagicMock) -> None:
        """Test health check when service is up."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        from caltrack.garmin import check_service_health

        assert check_service_health() is True

    @patch("caltrack.garmin.httpx.get")
    def test_unhealthy(self, mock_get: MagicMock) -> None:
        """Test health check when service is down."""
        mock_get.side_effect = Exception("connection refused")

        from caltrack.garmin import check_service_health

        assert check_service_health() is False
