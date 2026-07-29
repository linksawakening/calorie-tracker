"""Tests for the Garmin sync service (FastAPI app).

Tests use FastAPI's TestClient with mocked Garmin client to avoid
requiring real Garmin credentials.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

# Import after app so the module is loaded
import garmin_sync.app as app_module
import pytest
from fastapi.testclient import TestClient
from garmin_sync.app import app

API_KEY = "test-key-1234"
API_HEADERS = {"X-API-Key": API_KEY}


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Create a test client with API key configured."""
    with patch.dict(
        "os.environ",
        {
            "GARMIN_SYNC_API_KEY": API_KEY,
            "GARMIN_EMAIL": "test@example.com",
            "GARMIN_PASSWORD": "test-pass",
        },
    ):
        # Clear any cached client
        app_module._client = None
        app_module._get_client.cache_clear()
        yield TestClient(app)
    app_module._client = None
    app_module._get_client.cache_clear()


@pytest.fixture
def mock_garmin(client: TestClient) -> Generator[MagicMock, None, None]:
    """Mock the Garmin client so no real API calls are made."""
    mock = MagicMock()
    with patch.object(app_module, "_get_client", return_value=mock):
        yield mock


class TestHealth:
    """Health check endpoint."""

    def test_health_no_auth(self, client: TestClient) -> None:
        """Health check should work without API key."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestConfig:
    """Config endpoint."""

    def test_config_shows_all_types(
        self, client: TestClient, mock_garmin: MagicMock
    ) -> None:
        """Config should list all available data types."""
        resp = client.get("/config", headers=API_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "available_types" in data
        assert "enabled_types" in data
        assert "summary" in data["available_types"]
        assert "sleep" in data["available_types"]
        assert "activities" in data["available_types"]
        assert len(data["available_types"]) == 14

    def test_config_requires_auth(
        self, client: TestClient, mock_garmin: MagicMock
    ) -> None:
        """Config should require API key."""
        resp = client.get("/config")
        assert resp.status_code == 401

    def test_config_respects_env_var(
        self, client: TestClient, mock_garmin: MagicMock
    ) -> None:
        """Config should show only enabled types when env var is set."""
        with patch.dict("os.environ", {"GARMIN_DATA_TYPES": "summary,sleep"}):
            resp = client.get("/config", headers=API_HEADERS)
            assert resp.status_code == 200
            data = resp.json()
            assert set(data["enabled_types"]) == {"summary", "sleep"}


class TestGetDataByType:
    """Single data type endpoint."""

    def test_get_summary(self, client: TestClient, mock_garmin: MagicMock) -> None:
        """Test fetching summary data type."""
        mock_garmin.get_stats.return_value = {
            "totalKilocalories": 2300,
            "bmrKilocalories": 1850,
            "totalSteps": 8000,
            "floorsAscended": 10,
            "moderateIntensityMinutes": 20,
            "vigorousIntensityMinutes": 10,
            "restingHeartRate": 60,
            "averageStressLevel": 35,
            "bodyBatteryChargedValue": 85,
            "bodyBatteryDrainedValue": 45,
        }
        resp = client.get("/data/summary/2026-07-28", headers=API_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["active_calories"] == 450
        assert data["bmr_calories"] == 1850
        assert data["total_calories"] == 2300
        assert data["steps"] == 8000
        assert data["resting_hr"] == 60
        assert data["stress_avg"] == 35
        assert data["body_battery_max"] == 85
        assert data["data_type"] == "summary"
        assert data["date"] == "2026-07-28"

    def test_get_sleep(self, client: TestClient, mock_garmin: MagicMock) -> None:
        """Test fetching sleep data type."""
        mock_garmin.get_sleep_data.return_value = {
            "dailySleepDTO": {
                "sleepTimeSeconds": 28800,
                "deepSleepSeconds": 7200,
                "lightSleepSeconds": 14400,
                "remSleepSeconds": 5400,
                "awakeSleepSeconds": 1800,
                "sleepScore": 82,
            }
        }
        resp = client.get("/data/sleep/2026-07-28", headers=API_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["sleep_time_seconds"] == 28800
        assert data["deep_sleep_seconds"] == 7200
        assert data["sleep_score"] == 82

    def test_get_activities(self, client: TestClient, mock_garmin: MagicMock) -> None:
        """Test fetching activities data type."""
        mock_garmin.get_activities_by_date.return_value = [
            {
                "activityId": 12345,
                "activityName": "Morning Run",
                "activityType": {"typeKey": "running"},
                "startTimeLocal": "2026-07-28 07:00:00",
                "duration": 1800,
                "calories": 350,
                "distance": 5.0,
                "averageHR": 150,
                "maxHR": 165,
            }
        ]
        resp = client.get("/data/activities/2026-07-28", headers=API_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert len(data["activities"]) == 1
        act = data["activities"][0]
        assert act["name"] == "Morning Run"
        assert act["type"] == "running"
        assert act["calories"] == 350
        assert act["average_hr"] == 150

    def test_unknown_data_type(
        self, client: TestClient, mock_garmin: MagicMock
    ) -> None:
        """Unknown data type should return 404."""
        resp = client.get("/data/nonexistent/2026-07-28", headers=API_HEADERS)
        assert resp.status_code == 404

    def test_disabled_data_type(
        self, client: TestClient, mock_garmin: MagicMock
    ) -> None:
        """Disabled data type should return 404."""
        with patch.dict("os.environ", {"GARMIN_DATA_TYPES": "summary"}):
            resp = client.get("/data/sleep/2026-07-28", headers=API_HEADERS)
            assert resp.status_code == 404
            assert "not enabled" in resp.json()["detail"]

    def test_requires_auth(self, client: TestClient, mock_garmin: MagicMock) -> None:
        """Data endpoint should require API key."""
        resp = client.get("/data/summary/2026-07-28")
        assert resp.status_code == 401

    def test_invalid_date(self, client: TestClient, mock_garmin: MagicMock) -> None:
        """Invalid date format should return 400."""
        resp = client.get("/data/summary/not-a-date", headers=API_HEADERS)
        assert resp.status_code == 400


class TestGetAllData:
    """Combined endpoint for all data types."""

    def test_get_all_data(self, client: TestClient, mock_garmin: MagicMock) -> None:
        """Test fetching all enabled data types in one call."""
        mock_garmin.get_stats.return_value = {
            "totalKilocalories": 2300,
            "bmrKilocalories": 1850,
            "totalSteps": 8000,
        }
        mock_garmin.get_body_composition.return_value = {
            "totalAverage": {"weight": 85.9, "bmi": 27.1}
        }
        mock_garmin.get_sleep_data.return_value = {
            "dailySleepDTO": {"sleepTimeSeconds": 28800, "sleepScore": 82}
        }
        mock_garmin.get_activities_by_date.return_value = []
        mock_garmin.get_hrv_data.return_value = None
        mock_garmin.get_training_readiness.return_value = []
        mock_garmin.get_stress_data.return_value = {"avgStressLevel": 35}
        mock_garmin.get_heart_rates.return_value = {"restingHeartRate": 60}
        mock_garmin.get_respiration_data.return_value = {"avgRespirationValue": 14.5}
        mock_garmin.get_spo2_data.return_value = {"averageSpO2": 97.5}
        mock_garmin.get_hydration_data.return_value = {"valueInML": 2000}
        mock_garmin.get_body_battery.return_value = [{"charged": 85, "drained": 45}]
        mock_garmin.get_max_metrics.return_value = {"vo2Max": 50.0}
        mock_garmin.get_training_status.return_value = {"trainingStatus": "productive"}

        with patch.dict(
            "os.environ",
            {
                "GARMIN_DATA_TYPES": "summary,sleep,activities",
            },
        ):
            resp = client.get("/day/2026-07-28", headers=API_HEADERS)
            assert resp.status_code == 200
            data = resp.json()
            assert data["date"] == "2026-07-28"
            assert "summary" in data
            assert "sleep" in data
            assert "activities" in data
            # Should not include types not enabled
            assert "hrv" not in data

    def test_get_all_data_handles_errors(
        self, client: TestClient, mock_garmin: MagicMock
    ) -> None:
        """Individual data type errors should not fail the whole request."""
        mock_garmin.get_stats.return_value = {
            "totalKilocalories": 2300,
            "bmrKilocalories": 1850,
        }
        mock_garmin.get_sleep_data.side_effect = Exception("API error")

        with patch.dict(
            "os.environ",
            {
                "GARMIN_DATA_TYPES": "summary,sleep",
            },
        ):
            resp = client.get("/day/2026-07-28", headers=API_HEADERS)
            assert resp.status_code == 200
            data = resp.json()
            assert data["summary"]["available"] is True
            assert data["sleep"]["available"] is False
            assert "error" in data["sleep"]


class TestLegacyEndpoints:
    """Backward-compatible endpoints."""

    def test_calories_endpoint(
        self, client: TestClient, mock_garmin: MagicMock
    ) -> None:
        """Legacy /calories/{day} should still work."""
        mock_garmin.get_stats.return_value = {
            "totalKilocalories": 2300,
            "bmrKilocalories": 1850,
            "totalSteps": 8000,
        }
        resp = client.get("/calories/2026-07-28", headers=API_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_calories"] == 450
        assert data["bmr_calories"] == 1850
        assert data["total_calories"] == 2300
        assert data["steps"] == 8000
        assert data["date"] == "2026-07-28"

    def test_calories_range(self, client: TestClient, mock_garmin: MagicMock) -> None:
        """Legacy /calories range endpoint should still work."""
        mock_garmin.get_stats.return_value = {
            "totalKilocalories": 2300,
            "bmrKilocalories": 1850,
            "totalSteps": 8000,
        }
        resp = client.get(
            "/calories?start=2026-07-28&end=2026-07-28", headers=API_HEADERS
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["active_calories"] == 450

    def test_weight_endpoint(self, client: TestClient, mock_garmin: MagicMock) -> None:
        """Legacy /weight/{day} should still work."""
        mock_garmin.get_body_composition.return_value = {
            "totalAverage": {"weight": 85.9, "bmi": 27.1, "bodyFat": 18.5}
        }
        resp = client.get("/weight/2026-07-28", headers=API_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["weight_kg"] == 85.9
        assert data["bmi"] == 27.1

    def test_calories_range_max_30_days(
        self, client: TestClient, mock_garmin: MagicMock
    ) -> None:
        """Range endpoint should reject > 30 days."""
        resp = client.get(
            "/calories?start=2026-06-01&end=2026-07-28", headers=API_HEADERS
        )
        assert resp.status_code == 400
