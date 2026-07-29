"""Garmin Connect sync via remote API.

Calls the garmin-sync-service. The service holds the Garmin credentials
and exposes a REST API. This module only needs the service URL and API
key — never the Garmin password.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

import httpx

from caltrack.db import ExpenditureRecord, upsert_expenditure

logger = logging.getLogger(__name__)

DEFAULT_SERVICE_URL = "http://localhost:8700"


def _get_service_url() -> str:
    """Get the garmin-sync-service URL from environment."""
    return os.environ.get("GARMIN_SYNC_URL", DEFAULT_SERVICE_URL)


def _get_api_key() -> str:
    """Get the API key for the garmin-sync-service."""
    key = os.environ.get("GARMIN_SYNC_API_KEY", "")
    if not key:
        raise RuntimeError("GARMIN_SYNC_API_KEY not set — get it from the service .env")
    return key


def _get_headers() -> dict[str, str]:
    """Return auth headers for the API."""
    return {"X-API-Key": _get_api_key()}


def check_service_health() -> bool:
    """Check if the garmin-sync-service is reachable.

    Returns:
        True if the service responds with 200 on /health.
    """
    try:
        resp = httpx.get(f"{_get_service_url()}/health", timeout=5)
        return bool(resp.status_code == 200)
    except Exception:
        logger.warning("Garmin sync service not reachable")
        return False


def sync_garmin_day(conn: Any, day: str | None = None) -> ExpenditureRecord | None:
    """Sync a single day's expenditure data from the remote Garmin service.

    Args:
        conn: SQLite database connection.
        day: Date string YYYY-MM-DD. Defaults to today.

    Returns:
        ExpenditureRecord if data was synced, None if no data available.
    """
    if day is None:
        day = date.today().isoformat()

    url = f"{_get_service_url()}/calories/{day}"
    try:
        resp = httpx.get(url, headers=_get_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            "Garmin API returned %d for %s: %s", e.response.status_code, day, e
        )
        return None
    except Exception:
        logger.exception("Failed to call Garmin sync service for %s", day)
        return None

    if not data.get("available", False):
        logger.info("No Garmin data for %s", day)
        return None

    rec = ExpenditureRecord(
        date=day,
        active_calories=data["active_calories"],
        bmr_calories=data["bmr_calories"],
        total_calories=data["total_calories"],
        steps=data.get("steps", 0),
        floors=data.get("floors", 0),
        intensity_minutes=data.get("intensity_minutes", 0),
        resting_hr=data.get("resting_hr"),
    )
    upsert_expenditure(conn, rec)
    logger.info(
        "Synced %s: %d active + %d BMR = %d total cal",
        day,
        rec.active_calories,
        rec.bmr_calories,
        rec.total_calories,
    )
    return rec


def sync_garmin_range(
    conn: Any, start_date: str, end_date: str
) -> list[ExpenditureRecord]:
    """Sync a range of days from the remote Garmin service.

    Args:
        conn: SQLite database connection.
        start_date: Start date YYYY-MM-DD.
        end_date: End date YYYY-MM-DD.

    Returns:
        List of synced ExpenditureRecords.
    """
    url = f"{_get_service_url()}/calories"
    try:
        resp = httpx.get(
            url,
            headers=_get_headers(),
            params={"start": start_date, "end": end_date},
            timeout=30,
        )
        resp.raise_for_status()
        data_list = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Garmin API returned %d: %s", e.response.status_code, e)
        return []
    except Exception:
        logger.exception("Failed to call Garmin sync service")
        return []

    records: list[ExpenditureRecord] = []
    for data in data_list:
        if not data.get("available", False):
            continue
        rec = ExpenditureRecord(
            date=data["date"],
            active_calories=data["active_calories"],
            bmr_calories=data["bmr_calories"],
            total_calories=data["total_calories"],
            steps=data.get("steps", 0),
            floors=data.get("floors", 0),
            intensity_minutes=data.get("intensity_minutes", 0),
        )
        upsert_expenditure(conn, rec)
        records.append(rec)
        logger.info("Synced %s: %d total cal", rec.date, rec.total_calories)

    return records


def refresh_auth() -> bool:
    """Force the remote service to re-authenticate with Garmin.

    Returns:
        True if refresh succeeded.
    """
    url = f"{_get_service_url()}/auth/refresh"
    try:
        resp = httpx.post(url, headers=_get_headers(), timeout=30)
        resp.raise_for_status()
        logger.info("Garmin auth refreshed on remote service")
        return True
    except Exception:
        logger.exception("Failed to refresh Garmin auth")
        return False
