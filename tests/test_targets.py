"""Tests for the targets module."""

from __future__ import annotations

from caltrack.db import ExpenditureRecord
from caltrack.targets import (
    DEFAULT_DEFICIT,
    compute_estimated_targets,
    compute_targets_from_expenditure,
    format_targets,
)

# Use a fixed test weight so macro assertions are deterministic
TEST_WEIGHT_LBS = 180.0


class TestTargetsFromExpenditure:
    """Tests for Garmin-based target computation."""

    def test_average_day(self) -> None:
        """Test targets for an average activity day."""
        exp = ExpenditureRecord(
            date="2026-07-28",
            active_calories=450,
            bmr_calories=1850,
            total_calories=2300,
        )
        targets = compute_targets_from_expenditure(exp, body_weight_lbs=TEST_WEIGHT_LBS)
        assert targets.tdee == 2300
        assert targets.target_calories == 2300 + DEFAULT_DEFICIT
        assert targets.source == "garmin"
        assert targets.deficit == -300
        # Protein ~1g/lb body weight
        assert targets.target_protein_g == 180

    def test_good_day(self) -> None:
        """Test targets for a high-activity day."""
        exp = ExpenditureRecord(
            date="2026-07-28",
            active_calories=1600,
            bmr_calories=1850,
            total_calories=3450,
        )
        targets = compute_targets_from_expenditure(exp, body_weight_lbs=TEST_WEIGHT_LBS)
        assert targets.tdee == 3450
        assert targets.target_calories == 3150

    def test_sedentary_day(self) -> None:
        """Test targets for a low-activity day."""
        exp = ExpenditureRecord(
            date="2026-07-28",
            active_calories=100,
            bmr_calories=1850,
            total_calories=1950,
        )
        targets = compute_targets_from_expenditure(exp, body_weight_lbs=TEST_WEIGHT_LBS)
        assert targets.tdee == 1950
        assert targets.target_calories == 1650


class TestEstimatedTargets:
    """Tests for estimated (pre-Garmin) target computation."""

    def test_estimate_defaults(self) -> None:
        """Test estimated targets with default values."""
        targets = compute_estimated_targets(
            "2026-07-28", body_weight_lbs=TEST_WEIGHT_LBS
        )
        assert targets.tdee == 1850 + 450
        assert targets.target_calories == 2300 + DEFAULT_DEFICIT
        assert targets.source == "estimate"

    def test_custom_deficit(self) -> None:
        """Test with a custom deficit."""
        targets = compute_estimated_targets(
            "2026-07-28", deficit=-500, body_weight_lbs=TEST_WEIGHT_LBS
        )
        assert targets.deficit == -500
        assert targets.target_calories == 2300 - 500


class TestFormatTargets:
    """Tests for target formatting."""

    def test_format_garmin(self) -> None:
        """Test formatting with Garmin source."""
        exp = ExpenditureRecord(
            date="2026-07-28",
            active_calories=450,
            bmr_calories=1850,
            total_calories=2300,
        )
        targets = compute_targets_from_expenditure(exp, body_weight_lbs=TEST_WEIGHT_LBS)
        text = format_targets(targets)
        assert "2026-07-28" in text
        assert "2300" in text
        assert "garmin" in text.lower()

    def test_format_estimate(self) -> None:
        """Test formatting with estimated source."""
        targets = compute_estimated_targets(
            "2026-07-28", body_weight_lbs=TEST_WEIGHT_LBS
        )
        text = format_targets(targets)
        assert "estimated" in text.lower()
