"""FastAPI service exposing Garmin Connect calorie data.

Holds Garmin credentials in .env (on the host filesystem, which the
calorie-tracker client cannot read). Exposes a simple REST API that the
client calls with a shared API key.

Security model:
  - Garmin credentials live only in the service .env (mode 0600)
  - API key shared between this service and the client
  - Client has the API key but NOT the Garmin credentials
  - API key grants access to calorie DATA only, never credentials
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

app = FastAPI(
    title="Garmin Sync Service",
    description="Exposes Garmin Connect calorie expenditure data via REST",
    version="0.1.0",
)

_client: Any = None


def _get_expected_key() -> str:
    """Get the expected API key from environment."""
    key = os.environ.get("GARMIN_SYNC_API_KEY", "")
    if not key:
        raise RuntimeError("GARMIN_SYNC_API_KEY not set — cannot authenticate requests")
    return key


async def verify_api_key(api_key: str = Depends(API_KEY_HEADER)) -> str:
    """Verify the X-API-Key header against the expected key."""
    if api_key != _get_expected_key():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return api_key


@lru_cache(maxsize=1)
def _get_client() -> Any:
    """Create and authenticate the Garmin client (singleton)."""
    global _client
    if _client is not None:
        return _client

    from pathlib import Path

    from garminconnect import Garmin

    email = os.environ.get("GARMIN_EMAIL", "")
    password = os.environ.get("GARMIN_PASSWORD", "")
    tokenstore = os.environ.get(
        "GARMIN_TOKENSTORE",
        str(Path.home() / ".garminconnect" / "garmin_tokens.json"),
    )

    if not email or not password:
        raise RuntimeError("GARMIN_EMAIL and GARMIN_PASSWORD must be set")

    client = Garmin(email, password)
    client.login(tokenstore)
    logger.info("Garmin client authenticated")
    _client = client
    return _client


def _reset_client() -> None:
    """Reset the cached client (forces re-auth on next request)."""
    global _client
    _client = None
    _get_client.cache_clear()


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint (no auth required)."""
    return {"status": "ok"}


@app.get("/calories/{day}", dependencies=[Depends(verify_api_key)])
async def get_calories(day: str) -> dict[str, Any]:
    """Get calorie expenditure data for a specific date.

    Args:
        day: Date in YYYY-MM-DD format.

    Returns:
        Dictionary with active_calories, bmr_calories, total_calories,
        steps, and other available health metrics.
    """
    try:
        _validate_date(day)
        client = _get_client()
        data = client.get_full_day_data(day)

        if not data:
            return {"date": day, "available": False}

        total = int(data.get("totalKilocalories", 0))
        bmr = int(data.get("bmrKilocalories", 0))
        active = max(0, total - bmr)

        return {
            "date": day,
            "available": True,
            "active_calories": active,
            "bmr_calories": bmr,
            "total_calories": total,
            "steps": int(data.get("totalSteps", 0)),
            "floors": int(data.get("floorsAscended", 0)),
            "intensity_minutes": (
                int(data.get("moderateIntensityMinutes", 0))
                + int(data.get("vigorousIntensityMinutes", 0))
            ),
            "resting_hr": int(data.get("restingHeartRate", 0)) or None,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to get Garmin data for %s", day)
        _reset_client()
        raise HTTPException(
            status_code=502,
            detail=f"Garmin API error: {e!s}",
        ) from e


@app.get("/calories", dependencies=[Depends(verify_api_key)])
async def get_calories_range(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> list[dict[str, Any]]:
    """Get calorie data for a date range (max 30 days).

    Args:
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.

    Returns:
        List of daily calorie summaries.
    """
    _validate_date(start)
    _validate_date(end)

    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    if end_date < start_date:
        raise HTTPException(400, "end must be >= start")
    if (end_date - start_date).days > 30:
        raise HTTPException(400, "range must be <= 30 days")

    try:
        client = _get_client()
        results: list[dict[str, Any]] = []
        current = start_date
        while current <= end_date:
            day_str = current.isoformat()
            data = client.get_full_day_data(day_str)

            if data:
                total = int(data.get("totalKilocalories", 0))
                bmr = int(data.get("bmrKilocalories", 0))
                active = max(0, total - bmr)

                results.append(
                    {
                        "date": day_str,
                        "available": True,
                        "active_calories": active,
                        "bmr_calories": bmr,
                        "total_calories": total,
                        "steps": int(data.get("totalSteps", 0)),
                    }
                )
            else:
                results.append({"date": day_str, "available": False})

            current += timedelta(days=1)

        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get Garmin range %s-%s", start, end)
        _reset_client()
        raise HTTPException(
            status_code=502,
            detail=f"Garmin API error: {e!s}",
        ) from e


@app.get("/weight/{day}", dependencies=[Depends(verify_api_key)])
async def get_weight(day: str) -> dict[str, Any]:
    """Get body composition / weight for a specific date.

    Args:
        day: Date in YYYY-MM-DD format.

    Returns:
        Dictionary with weight and body composition if available.
    """
    try:
        _validate_date(day)
        client = _get_client()
        data = client.get_body_composition(day)

        if not data:
            return {"date": day, "available": False}

        # Response structure varies — extract what we can
        return {"date": day, "available": True, "raw": data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to get weight for %s", day)
        _reset_client()
        raise HTTPException(
            status_code=502,
            detail=f"Garmin API error: {e!s}",
        ) from e


@app.post("/auth/refresh", dependencies=[Depends(verify_api_key)])
async def refresh_auth() -> dict[str, str]:
    """Force a re-authentication with Garmin.

    Call this if the cached token has expired or become invalid.
    """
    _reset_client()
    _get_client()
    return {"status": "refreshed"}


def _validate_date(day: str) -> None:
    """Validate a date string is YYYY-MM-DD format."""
    try:
        date.fromisoformat(day)
    except ValueError as e:
        raise ValueError(f"Invalid date format: {day} (expected YYYY-MM-DD)") from e
