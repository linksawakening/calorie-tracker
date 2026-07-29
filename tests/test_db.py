"""Tests for the database module."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from caltrack.db import (
    BodyCompositionRecord,
    ExpenditureRecord,
    IntakeRecord,
    add_intake,
    compute_daily_summary,
    get_connection,
    get_daily_intake,
    get_expenditure,
    get_rolling_weight,
    get_weight,
    upsert_body_composition,
    upsert_expenditure,
)


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    """In-memory database connection for testing."""
    db_path = tmp_path / "test.db"
    return get_connection(db_path)


class TestExpenditure:
    """Tests for expenditure table operations."""

    def test_upsert_and_get(self, conn: sqlite3.Connection) -> None:
        """Test inserting and retrieving expenditure data."""
        rec = ExpenditureRecord(
            date="2026-07-28",
            active_calories=450,
            bmr_calories=1850,
            total_calories=2300,
            steps=8000,
            floors=10,
            intensity_minutes=30,
        )
        upsert_expenditure(conn, rec)

        result = get_expenditure(conn, "2026-07-28")
        assert result is not None
        assert result.active_calories == 450
        assert result.bmr_calories == 1850
        assert result.total_calories == 2300
        assert result.steps == 8000

    def test_upsert_replaces_existing(self, conn: sqlite3.Connection) -> None:
        """Test that upsert replaces existing records."""
        rec1 = ExpenditureRecord(
            date="2026-07-28",
            active_calories=100,
            bmr_calories=1850,
            total_calories=1950,
        )
        upsert_expenditure(conn, rec1)

        rec2 = ExpenditureRecord(
            date="2026-07-28",
            active_calories=1600,
            bmr_calories=1850,
            total_calories=3450,
        )
        upsert_expenditure(conn, rec2)

        result = get_expenditure(conn, "2026-07-28")
        assert result is not None
        assert result.active_calories == 1600
        assert result.total_calories == 3450

    def test_get_nonexistent(self, conn: sqlite3.Connection) -> None:
        """Test getting expenditure for a date with no data."""
        assert get_expenditure(conn, "1999-01-01") is None


class TestIntake:
    """Tests for intake table operations."""

    def test_add_and_get(self, conn: sqlite3.Connection) -> None:
        """Test adding and retrieving intake records."""
        rec = IntakeRecord(
            date="2026-07-28",
            meal_name="breakfast",
            food_description="2 eggs, toast",
            calories=350,
            protein_g=18.0,
            carbs_g=30.0,
            fat_g=15.0,
        )
        row_id = add_intake(conn, rec)
        assert row_id > 0

        result = get_daily_intake(conn, "2026-07-28")
        assert result["total_calories"] == 350
        assert result["protein_g"] == 18.0
        assert result["carbs_g"] == 30.0
        assert result["fat_g"] == 15.0
        assert len(result["entries"]) == 1

    def test_multiple_entries_sum(self, conn: sqlite3.Connection) -> None:
        """Test that multiple intake entries are summed correctly."""
        for i, cal in enumerate([400, 600, 200]):
            add_intake(
                conn,
                IntakeRecord(
                    date="2026-07-28",
                    meal_name=f"meal_{i}",
                    food_description=f"food_{i}",
                    calories=cal,
                    protein_g=float(cal) // 10,
                ),
            )

        result = get_daily_intake(conn, "2026-07-28")
        assert result["total_calories"] == 1200
        assert len(result["entries"]) == 3

    def test_empty_day(self, conn: sqlite3.Connection) -> None:
        """Test getting intake for a day with no entries."""
        result = get_daily_intake(conn, "1999-01-01")
        assert result["total_calories"] == 0
        assert result["entries"] == []


class TestBodyComposition:
    """Tests for body composition table operations."""

    def test_upsert_and_get_weight(self, conn: sqlite3.Connection) -> None:
        """Test storing and retrieving weight."""
        rec = BodyCompositionRecord(
            date="2026-07-28",
            weight_kg=85.9,
            body_fat_pct=22.0,
            bmi=27.5,
        )
        upsert_body_composition(conn, rec)

        weight = get_weight(conn, "2026-07-28")
        assert weight is not None
        assert abs(weight - 85.9) < 0.01

    def test_rolling_weight(self, conn: sqlite3.Connection) -> None:
        """Test 7-day rolling average weight."""
        for i in range(7):
            upsert_body_composition(
                conn,
                BodyCompositionRecord(
                    date=f"2026-07-2{i}",
                    weight_kg=85.0 + i * 0.1,
                ),
            )

        rolling = get_rolling_weight(conn, "2026-07-26", window=7)
        assert rolling is not None
        expected = sum(85.0 + i * 0.1 for i in range(5)) / 5
        assert abs(rolling - expected) < 0.1

    def test_rolling_weight_no_data(self, conn: sqlite3.Connection) -> None:
        """Test rolling weight with no data."""
        assert get_rolling_weight(conn, "1999-01-01") is None


class TestDailySummary:
    """Tests for daily summary computation."""

    def test_compute_summary_with_data(self, conn: sqlite3.Connection) -> None:
        """Test summary computation with both intake and expenditure."""
        upsert_expenditure(
            conn,
            ExpenditureRecord(
                date="2026-07-28",
                active_calories=450,
                bmr_calories=1850,
                total_calories=2300,
            ),
        )
        add_intake(
            conn,
            IntakeRecord(
                date="2026-07-28",
                meal_name="dinner",
                food_description="chicken and rice",
                calories=800,
                protein_g=50.0,
                carbs_g=60.0,
                fat_g=20.0,
            ),
        )

        summary = compute_daily_summary(conn, "2026-07-28")
        assert summary["total_intake"] == 800
        assert summary["total_expenditure"] == 2300
        assert summary["energy_balance"] == -1500
        assert summary["protein_g"] == 50.0

    def test_compute_summary_empty_day(self, conn: sqlite3.Connection) -> None:
        """Test summary for a day with no data."""
        summary = compute_daily_summary(conn, "2026-07-28")
        assert summary["total_intake"] == 0
        assert summary["total_expenditure"] == 0
        assert summary["energy_balance"] == 0
