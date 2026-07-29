"""SQLite database layer for calorie tracking.

Handles schema creation, expenditure logging (Garmin), intake logging
(food), body composition, and daily summary computation.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenditure (
    date TEXT PRIMARY KEY,
    active_calories INTEGER,
    bmr_calories INTEGER,
    total_calories INTEGER,
    steps INTEGER,
    floors INTEGER,
    intensity_minutes INTEGER,
    resting_hr INTEGER,
    sleep_hours REAL,
    stress_avg INTEGER,
    body_battery_max INTEGER
);

CREATE TABLE IF NOT EXISTS intake (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    meal_name TEXT,
    food_description TEXT,
    calories INTEGER,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    fiber_g REAL,
    source TEXT,
    source_id TEXT,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS body_composition (
    date TEXT PRIMARY KEY,
    weight_kg REAL,
    body_fat_pct REAL,
    muscle_mass_kg REAL,
    bone_mass_kg REAL,
    bmi REAL,
    body_water_pct REAL
);

CREATE TABLE IF NOT EXISTS daily_summary (
    date TEXT PRIMARY KEY,
    total_intake INTEGER,
    total_expenditure INTEGER,
    energy_balance INTEGER,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    weight_kg REAL,
    rolling_weight_kg REAL
);

CREATE INDEX IF NOT EXISTS idx_intake_date ON intake(date);
"""

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "caltrack" / "caltrack.db"


def get_db_path(config_path: Path | None = None) -> Path:
    """Return the database path, creating parent dirs if needed.

    Args:
        config_path: Override path. If None, uses default location.

    Returns:
        Path to the SQLite database file.
    """
    path = config_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Get a SQLite connection with schema initialized.

    Args:
        db_path: Path to database file. Uses default if None.

    Returns:
        SQLite connection with row factory and schema initialized.
    """
    path = db_path or get_db_path()
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@dataclass(frozen=True)
class ExpenditureRecord:
    """Daily calorie expenditure data from Garmin."""

    date: str
    active_calories: int
    bmr_calories: int
    total_calories: int
    steps: int = 0
    floors: int = 0
    intensity_minutes: int = 0
    resting_hr: int | None = None
    sleep_hours: float | None = None
    stress_avg: int | None = None
    body_battery_max: int | None = None


@dataclass(frozen=True)
class IntakeRecord:
    """A single food intake entry."""

    date: str
    meal_name: str
    food_description: str
    calories: int
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0
    source: str = "manual"
    source_id: str | None = None


@dataclass(frozen=True)
class BodyCompositionRecord:
    """Body composition data from Garmin Index scale."""

    date: str
    weight_kg: float
    body_fat_pct: float | None = None
    muscle_mass_kg: float | None = None
    bone_mass_kg: float | None = None
    bmi: float | None = None
    body_water_pct: float | None = None


def upsert_expenditure(conn: sqlite3.Connection, rec: ExpenditureRecord) -> None:
    """Insert or replace a daily expenditure record.

    Args:
        conn: Active database connection.
        rec: Expenditure record to store.
    """
    conn.execute(
        """INSERT OR REPLACE INTO expenditure
           (date, active_calories, bmr_calories, total_calories,
            steps, floors, intensity_minutes, resting_hr,
            sleep_hours, stress_avg, body_battery_max)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rec.date,
            rec.active_calories,
            rec.bmr_calories,
            rec.total_calories,
            rec.steps,
            rec.floors,
            rec.intensity_minutes,
            rec.resting_hr,
            rec.sleep_hours,
            rec.stress_avg,
            rec.body_battery_max,
        ),
    )
    conn.commit()


def add_intake(conn: sqlite3.Connection, rec: IntakeRecord) -> int:
    """Add a food intake record.

    Args:
        conn: Active database connection.
        rec: Intake record to add.

    Returns:
        The rowid of the inserted record.
    """
    cursor = conn.execute(
        """INSERT INTO intake
           (date, meal_name, food_description, calories,
            protein_g, carbs_g, fat_g, fiber_g, source, source_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            rec.date,
            rec.meal_name,
            rec.food_description,
            rec.calories,
            rec.protein_g,
            rec.carbs_g,
            rec.fat_g,
            rec.fiber_g,
            rec.source,
            rec.source_id,
        ),
    )
    conn.commit()
    rowid = cursor.lastrowid
    return int(rowid) if rowid is not None else -1


def upsert_body_composition(
    conn: sqlite3.Connection, rec: BodyCompositionRecord
) -> None:
    """Insert or replace a body composition record.

    Args:
        conn: Active database connection.
        rec: Body composition record to store.
    """
    conn.execute(
        """INSERT OR REPLACE INTO body_composition
           (date, weight_kg, body_fat_pct, muscle_mass_kg,
            bone_mass_kg, bmi, body_water_pct)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            rec.date,
            rec.weight_kg,
            rec.body_fat_pct,
            rec.muscle_mass_kg,
            rec.bone_mass_kg,
            rec.bmi,
            rec.body_water_pct,
        ),
    )
    conn.commit()


def get_daily_intake(conn: sqlite3.Connection, day: str) -> dict[str, Any]:
    """Get aggregated intake for a specific date.

    Args:
        conn: Active database connection.
        day: Date string in YYYY-MM-DD format.

    Returns:
        Dictionary with total_calories, protein_g, carbs_g, fat_g, fiber_g,
        and entries list.
    """
    rows = conn.execute(
        "SELECT * FROM intake WHERE date = ? ORDER BY logged_at", (day,)
    ).fetchall()

    if not rows:
        return {
            "total_calories": 0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
            "fiber_g": 0.0,
            "entries": [],
        }

    return {
        "total_calories": sum(r["calories"] for r in rows),
        "protein_g": round(sum(r["protein_g"] for r in rows), 1),
        "carbs_g": round(sum(r["carbs_g"] for r in rows), 1),
        "fat_g": round(sum(r["fat_g"] for r in rows), 1),
        "fiber_g": round(sum(r["fiber_g"] for r in rows), 1),
        "entries": [dict(r) for r in rows],
    }


def get_expenditure(conn: sqlite3.Connection, day: str) -> ExpenditureRecord | None:
    """Get expenditure data for a specific date.

    Args:
        conn: Active database connection.
        day: Date string in YYYY-MM-DD format.

    Returns:
        ExpenditureRecord if found, None otherwise.
    """
    row = conn.execute("SELECT * FROM expenditure WHERE date = ?", (day,)).fetchone()

    if row is None:
        return None

    return ExpenditureRecord(
        date=row["date"],
        active_calories=row["active_calories"],
        bmr_calories=row["bmr_calories"],
        total_calories=row["total_calories"],
        steps=row["steps"],
        floors=row["floors"],
        intensity_minutes=row["intensity_minutes"],
        resting_hr=row["resting_hr"],
        sleep_hours=row["sleep_hours"],
        stress_avg=row["stress_avg"],
        body_battery_max=row["body_battery_max"],
    )


def get_weight(conn: sqlite3.Connection, day: str) -> float | None:
    """Get weight for a specific date from body composition.

    Args:
        conn: Active database connection.
        day: Date string in YYYY-MM-DD format.

    Returns:
        Weight in kg if found, None otherwise.
    """
    row = conn.execute(
        "SELECT weight_kg FROM body_composition WHERE date = ?", (day,)
    ).fetchone()
    return float(row["weight_kg"]) if row else None


def get_rolling_weight(
    conn: sqlite3.Connection, day: str, window: int = 7
) -> float | None:
    """Get N-day rolling average weight ending on a date.

    Args:
        conn: Active database connection.
        day: End date in YYYY-MM-DD format.
        window: Number of days to average (default 7).

    Returns:
        Average weight in kg if data exists, None otherwise.
    """
    rows = conn.execute(
        """SELECT weight_kg FROM body_composition
           WHERE date <= ? AND date >= date(?, ?)
           ORDER BY date DESC""",
        (day, day, f"-{window - 1} days"),
    ).fetchall()

    weights = [r["weight_kg"] for r in rows if r["weight_kg"] is not None]
    if not weights:
        return None
    return round(sum(weights) / len(weights), 2)  # type: ignore[no-any-return]


def compute_daily_summary(conn: sqlite3.Connection, day: str) -> dict[str, Any]:
    """Compute and store daily summary for a date.

    Args:
        conn: Active database connection.
        day: Date string in YYYY-MM-DD format.

    Returns:
        Dictionary with the computed summary fields.
    """
    intake = get_daily_intake(conn, day)
    exp = get_expenditure(conn, day)
    weight = get_weight(conn, day)
    rolling_weight = get_rolling_weight(conn, day)

    total_expenditure = exp.total_calories if exp else 0
    total_intake = intake["total_calories"]
    energy_balance = total_intake - total_expenditure

    conn.execute(
        """INSERT OR REPLACE INTO daily_summary
           (date, total_intake, total_expenditure, energy_balance,
            protein_g, carbs_g, fat_g, weight_kg, rolling_weight_kg)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            day,
            total_intake,
            total_expenditure,
            energy_balance,
            intake["protein_g"],
            intake["carbs_g"],
            intake["fat_g"],
            weight,
            rolling_weight,
        ),
    )
    conn.commit()

    return {
        "date": day,
        "total_intake": total_intake,
        "total_expenditure": total_expenditure,
        "energy_balance": energy_balance,
        "protein_g": intake["protein_g"],
        "carbs_g": intake["carbs_g"],
        "fat_g": intake["fat_g"],
        "weight_kg": weight,
        "rolling_weight_kg": rolling_weight,
    }


def get_date_range_summary(
    conn: sqlite3.Connection, start: str, end: str
) -> list[dict[str, Any]]:
    """Get daily summaries for a date range.

    Args:
        conn: Active database connection.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.

    Returns:
        List of summary dictionaries.
    """
    rows = conn.execute(
        """SELECT * FROM daily_summary WHERE date >= ? AND date <= ? ORDER BY date""",
        (start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def today_str() -> str:
    """Return today's date as YYYY-MM-DD string."""
    return date.today().isoformat()


def now_iso() -> str:
    """Return current timestamp as ISO string."""
    return datetime.now().isoformat()
