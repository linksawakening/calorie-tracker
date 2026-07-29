"""FastAPI service exposing Garmin Connect health data.

Holds Garmin credentials in .env (on the host filesystem, which the
calorie-tracker client cannot read). Exposes a simple REST API that the
client calls with a shared API key.

Security model:
  - Garmin credentials live only in the service .env (mode 0600)
  - API key shared between this service and the client
  - Client has the API key but NOT the Garmin credentials
  - API key grants access to health DATA only, never credentials

Data types are configurable via the GARMIN_DATA_TYPES env var.
See DATA_TYPES below for available types.
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

# ---------------------------------------------------------------------------
# Configurable data types
# ---------------------------------------------------------------------------
# Each entry maps a short name (used in env var and URL path) to:
#   label   — human-readable name for /config endpoint
#   methods — list of Garmin client methods to call (in order)
#   parser  — function that transforms raw Garmin response(s) into clean dict

DATA_TYPES: dict[str, dict[str, Any]] = {
    "summary": {
        "label": "Daily summary (calories, steps, HR, stress, body battery)",
        "methods": ["get_stats"],
        "parser": "_parse_summary",
    },
    "body_composition": {
        "label": "Weight, BMI, body fat %, muscle mass",
        "methods": ["get_body_composition"],
        "parser": "_parse_body_composition",
    },
    "sleep": {
        "label": "Sleep stages, duration, score",
        "methods": ["get_sleep_data"],
        "parser": "_parse_sleep",
    },
    "activities": {
        "label": "Individual workout activities with sport-specific calories",
        "methods": ["get_activities_by_date"],
        "parser": "_parse_activities",
    },
    "hrv": {
        "label": "Heart Rate Variability",
        "methods": ["get_hrv_data"],
        "parser": "_parse_hrv",
    },
    "training_readiness": {
        "label": "Training readiness score and factors",
        "methods": ["get_training_readiness"],
        "parser": "_parse_training_readiness",
    },
    "stress": {
        "label": "Stress levels throughout the day",
        "methods": ["get_stress_data"],
        "parser": "_parse_stress",
    },
    "heart_rates": {
        "label": "Heart rate zones and time-in-zone",
        "methods": ["get_heart_rates"],
        "parser": "_parse_heart_rates",
    },
    "respiration": {
        "label": "Respiration rate",
        "methods": ["get_respiration_data"],
        "parser": "_parse_respiration",
    },
    "spo2": {
        "label": "Blood oxygen saturation",
        "methods": ["get_spo2_data"],
        "parser": "_parse_spo2",
    },
    "hydration": {
        "label": "Hydration data (water intake)",
        "methods": ["get_hydration_data"],
        "parser": "_parse_hydration",
    },
    "body_battery": {
        "label": "Body battery (energy levels)",
        "methods": ["get_body_battery"],
        "parser": "_parse_body_battery",
    },
    "max_metrics": {
        "label": "VO2 max and other max metrics",
        "methods": ["get_max_metrics"],
        "parser": "_parse_max_metrics",
    },
    "training_status": {
        "label": "Training status (productive, recovery, etc.)",
        "methods": ["get_training_status"],
        "parser": "_parse_training_status",
    },
}

# All types enabled by default. Restrict via GARMIN_DATA_TYPES=summary,sleep,activities
DEFAULT_ENABLED = ",".join(DATA_TYPES.keys())


def _get_enabled_types() -> set[str]:
    """Return the set of enabled data types from env var."""
    raw = os.environ.get("GARMIN_DATA_TYPES", DEFAULT_ENABLED)
    requested = {t.strip() for t in raw.split(",") if t.strip()}
    return requested & set(DATA_TYPES.keys())


# ---------------------------------------------------------------------------
# Parsers — transform raw Garmin API responses into clean, consistent dicts
# ---------------------------------------------------------------------------


def _parse_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Parse get_stats / get_user_summary response."""
    total = int(data.get("totalKilocalories", 0))
    bmr = int(data.get("bmrKilocalories", 0))
    active = max(0, total - bmr)
    return {
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
        "stress_avg": int(data.get("averageStressLevel", 0)) or None,
        "body_battery_max": int(data.get("bodyBatteryChargedValue", 0)) or None,
        "body_battery_end": int(data.get("bodyBatteryDrainedValue", 0)) or None,
    }


def _parse_body_composition(data: dict[str, Any]) -> dict[str, Any]:
    """Parse get_body_composition response."""
    total_average = data.get("totalAverage") or {}
    if not isinstance(total_average, dict):
        return {"available": False}
    return {
        "available": True,
        "weight_kg": float(total_average.get("weight", 0)) or None,
        "bmi": float(total_average.get("bmi", 0)) or None,
        "body_fat_pct": float(total_average.get("bodyFat", 0)) or None,
        "muscle_mass_kg": float(total_average.get("muscleMass", 0)) or None,
        "bone_mass_kg": float(total_average.get("boneMass", 0)) or None,
        "body_water_pct": float(total_average.get("bodyWater", 0)) or None,
    }


def _parse_sleep(data: dict[str, Any]) -> dict[str, Any]:
    """Parse get_sleep_data response."""
    daily = data.get("dailySleepDTO") or {}
    if not isinstance(daily, dict):
        daily = {}
    return {
        "available": True,
        "sleep_time_seconds": int(daily.get("sleepTimeSeconds", 0)) or None,
        "deep_sleep_seconds": int(daily.get("deepSleepSeconds", 0)) or None,
        "light_sleep_seconds": int(daily.get("lightSleepSeconds", 0)) or None,
        "rem_sleep_seconds": int(daily.get("remSleepSeconds", 0)) or None,
        "awake_sleep_seconds": int(daily.get("awakeSleepSeconds", 0)) or None,
        "sleep_score": int(daily.get("sleepScore", 0)) or None,
    }


def _parse_activities(data: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
    """Parse get_activities_by_date response."""
    # get_activities_by_date returns a list
    activities = data if isinstance(data, list) else []
    parsed = []
    for a in activities:
        parsed.append(
            {
                "id": str(a.get("activityId", "")),
                "name": a.get("activityName", "Unknown"),
                "type": a.get("activityType", {}).get("typeKey", "unknown"),
                "start_time": a.get("startTimeLocal", ""),
                "duration_seconds": int(a.get("duration", 0)) or None,
                "calories": int(a.get("calories", 0)) or None,
                "distance_km": float(a.get("distance", 0)) or None,
                "average_hr": int(a.get("averageHR", 0)) or None,
                "max_hr": int(a.get("maxHR", 0)) or None,
            }
        )
    return {"available": True, "activities": parsed}


def _parse_hrv(data: dict[str, Any] | None) -> dict[str, Any]:
    """Parse get_hrv_data response."""
    if not data:
        return {"available": False}
    hrv_summary = data.get("hrvSummary") or {}
    if not isinstance(hrv_summary, dict):
        hrv_summary = {}
    return {
        "available": True,
        "hrv_avg": int(hrv_summary.get("avgHRV", 0)) or None,
        "hrv_status": hrv_summary.get("hrvStatus", ""),
    }


def _parse_training_readiness(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse get_training_readiness response."""
    if not data or not isinstance(data, list) or len(data) == 0:
        return {"available": False}
    entry = data[0] if isinstance(data[0], dict) else {}
    return {
        "available": True,
        "score": int(entry.get("score", 0)) or None,
        "status": entry.get("status", ""),
    }


def _parse_stress(data: dict[str, Any]) -> dict[str, Any]:
    """Parse get_stress_data response."""
    return {
        "available": True,
        "avg_stress": int(data.get("avgStressLevel", 0)) or None,
        "max_stress": int(data.get("maxStressLevel", 0)) or None,
        "stress_duration_seconds": int(data.get("stressDuration", 0)) or None,
        "rest_stress_duration_seconds": int(data.get("restStressDuration", 0)) or None,
    }


def _parse_heart_rates(data: dict[str, Any]) -> dict[str, Any]:
    """Parse get_heart_rates response."""
    return {
        "available": True,
        "min_hr": int(data.get("minHeartRate", 0)) or None,
        "max_hr": int(data.get("maxHeartRate", 0)) or None,
        "resting_hr": int(data.get("restingHeartRate", 0)) or None,
        "avg_hr": int(data.get("averageHeartRate", 0)) or None,
    }


def _parse_respiration(data: dict[str, Any]) -> dict[str, Any]:
    """Parse get_respiration_data response."""
    return {
        "available": True,
        "avg_respiration": float(data.get("avgRespirationValue", 0)) or None,
        "min_respiration": float(data.get("minRespirationValue", 0)) or None,
        "max_respiration": float(data.get("maxRespirationValue", 0)) or None,
    }


def _parse_spo2(data: dict[str, Any]) -> dict[str, Any]:
    """Parse get_spo2_data response."""
    return {
        "available": True,
        "avg_spo2": float(data.get("averageSpO2", 0)) or None,
        "min_spo2": float(data.get("minSpO2", 0)) or None,
        "max_spo2": float(data.get("maxSpO2", 0)) or None,
    }


def _parse_hydration(data: dict[str, Any]) -> dict[str, Any]:
    """Parse get_hydration_data response."""
    return {
        "available": True,
        "hydration_ml": float(data.get("valueInML", 0)) or None,
        "goal_ml": float(data.get("goalInML", 0)) or None,
    }


def _parse_body_battery(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse get_body_battery response."""
    if not data or not isinstance(data, list) or len(data) == 0:
        return {"available": False}
    entry = data[0] if isinstance(data[0], dict) else {}
    return {
        "available": True,
        "charged": int(entry.get("charged", 0)) or None,
        "drained": int(entry.get("drained", 0)) or None,
        "max": int(entry.get("max", 0)) or None,
        "end": int(entry.get("end", 0)) or None,
    }


def _parse_max_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """Parse get_max_metrics response."""
    metrics = []
    for key, value in data.items():
        if isinstance(value, (int, float)) and value:
            metrics.append({"metric": key, "value": float(value)})
    return {"available": bool(metrics), "metrics": metrics}


def _parse_training_status(data: dict[str, Any]) -> dict[str, Any]:
    """Parse get_training_status response."""
    return {
        "available": True,
        "status": data.get("trainingStatus", ""),
        "status_message": data.get("trainingStatusMessage", ""),
    }


PARSER_FUNCTIONS: dict[str, Any] = {
    "_parse_summary": _parse_summary,
    "_parse_body_composition": _parse_body_composition,
    "_parse_sleep": _parse_sleep,
    "_parse_activities": _parse_activities,
    "_parse_hrv": _parse_hrv,
    "_parse_training_readiness": _parse_training_readiness,
    "_parse_stress": _parse_stress,
    "_parse_heart_rates": _parse_heart_rates,
    "_parse_respiration": _parse_respiration,
    "_parse_spo2": _parse_spo2,
    "_parse_hydration": _parse_hydration,
    "_parse_body_battery": _parse_body_battery,
    "_parse_max_metrics": _parse_max_metrics,
    "_parse_training_status": _parse_training_status,
}


app = FastAPI(
    title="Garmin Sync Service",
    description="Exposes Garmin Connect health data via REST",
    version="0.2.0",
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


def _call_garmin_method(client: Any, method_name: str, day: str) -> Any:
    """Call a Garmin client method by name with the appropriate date arg.

    Some methods take a single date, others take a date range (start, end).
    This handles both patterns.
    """
    method = getattr(client, method_name)
    # Body composition and body_battery take (startdate, enddate)
    if method_name in ("get_body_composition", "get_body_battery"):
        return method(day, day)
    # Activities takes (startdate, enddate) and returns a list
    if method_name == "get_activities_by_date":
        return method(day, day)
    # Everything else takes a single cdate
    return method(day)


def _fetch_data_type(data_type: str, day: str) -> dict[str, Any]:
    """Fetch a single data type for a given day.

    Args:
        data_type: Key from DATA_TYPES (e.g. "summary", "sleep").
        day: Date in YYYY-MM-DD format.

    Returns:
        Parsed data dict with at least {"available": bool}.
    """
    spec = DATA_TYPES[data_type]
    parser_name = spec["parser"]
    parser = PARSER_FUNCTIONS[parser_name]

    client = _get_client()
    raw_results: list[Any] = []
    for method_name in spec["methods"]:
        raw = _call_garmin_method(client, method_name, day)
        raw_results.append(raw)

    # Single-method types: pass single result
    if len(raw_results) == 1:
        result: dict[str, Any] = parser(raw_results[0])
    else:
        result = parser(*raw_results)

    result["data_type"] = data_type
    result["date"] = day
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint (no auth required)."""
    return {"status": "ok"}


@app.get("/config", dependencies=[Depends(verify_api_key)])
async def get_config() -> dict[str, Any]:
    """Show available and enabled data types."""
    enabled = _get_enabled_types()
    return {
        "available_types": {k: v["label"] for k, v in DATA_TYPES.items()},
        "enabled_types": sorted(enabled),
        "version": "0.2.0",
    }


@app.get("/data/{data_type}/{day}", dependencies=[Depends(verify_api_key)])
async def get_data_type(data_type: str, day: str) -> dict[str, Any]:
    """Get a specific health data type for a given date.

    Args:
        data_type: One of the types listed in /config.
        day: Date in YYYY-MM-DD format.

    Returns:
        Parsed health data for the requested type and date.
    """
    if data_type not in DATA_TYPES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown data type: {data_type}. See /config for available types.",
        )
    if data_type not in _get_enabled_types():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Data type '{data_type}' is not enabled. "
                "Set GARMIN_DATA_TYPES to include it."
            ),
        )

    try:
        _validate_date(day)
        return _fetch_data_type(data_type, day)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to get %s for %s", data_type, day)
        _reset_client()
        raise HTTPException(
            status_code=502,
            detail=f"Garmin API error: {e!s}",
        ) from e


@app.get("/day/{day}", dependencies=[Depends(verify_api_key)])
async def get_all_data(day: str) -> dict[str, Any]:
    """Get all enabled data types for a given date in a single call.

    Args:
        day: Date in YYYY-MM-DD format.

    Returns:
        Dict mapping each enabled data_type to its parsed data.
    """
    try:
        _validate_date(day)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    enabled = _get_enabled_types()
    result: dict[str, Any] = {"date": day}
    errors: list[dict[str, str]] = []

    for data_type in sorted(enabled):
        try:
            result[data_type] = _fetch_data_type(data_type, day)
        except Exception as e:
            logger.warning("Failed to fetch %s for %s: %s", data_type, day, e)
            result[data_type] = {"available": False, "error": str(e)}
            errors.append({"data_type": data_type, "error": str(e)})

    if errors:
        result["_errors"] = errors
    return result


# ---------------------------------------------------------------------------
# Backward-compatible endpoints (v0.1 API)
# ---------------------------------------------------------------------------


@app.get("/calories/{day}", dependencies=[Depends(verify_api_key)])
async def get_calories(day: str) -> dict[str, Any]:
    """Get calorie expenditure data for a specific date (legacy endpoint).

    Uses the 'summary' data type under the hood.
    """
    try:
        _validate_date(day)
        data = _fetch_data_type("summary", day)
        # Preserve the old response shape for backward compat
        data["date"] = day
        return data
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
    """Get calorie data for a date range (max 30 days)."""
    _validate_date(start)
    _validate_date(end)

    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)

    if end_date < start_date:
        raise HTTPException(400, "end must be >= start")
    if (end_date - start_date).days > 30:
        raise HTTPException(400, "range must be <= 30 days")

    try:
        results: list[dict[str, Any]] = []
        current = start_date
        while current <= end_date:
            day_str = current.isoformat()
            try:
                data = _fetch_data_type("summary", day_str)
                data["date"] = day_str
                results.append(data)
            except Exception as e:
                logger.warning("Failed to get data for %s: %s", day_str, e)
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
    """Get body composition / weight for a specific date."""
    try:
        _validate_date(day)
        return _fetch_data_type("body_composition", day)
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
    """Force a re-authentication with Garmin."""
    _reset_client()
    _get_client()
    return {"status": "refreshed"}


def _validate_date(day: str) -> None:
    """Validate a date string is YYYY-MM-DD format."""
    try:
        date.fromisoformat(day)
    except ValueError as e:
        raise ValueError(f"Invalid date format: {day} (expected YYYY-MM-DD)") from e
