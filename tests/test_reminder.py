"""Tests for the reminder module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from caltrack.reminder import check_logging_status


class TestReminder:
    """Tests for the food logging reminder."""

    @patch("caltrack.reminder.get_daily_intake")
    def test_no_entries_triggers_reminder(self, mock_intake: MagicMock) -> None:
        """Test that zero entries triggers a reminder."""
        mock_intake.return_value = {
            "total_calories": 0,
            "entries": [],
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
            "fiber_g": 0.0,
        }

        msg = check_logging_status()
        assert msg is not None
        assert "haven't logged" in msg

    @patch("caltrack.reminder.get_daily_intake")
    def test_three_entries_no_reminder(self, mock_intake: MagicMock) -> None:
        """Test that 3+ entries suppresses the reminder."""
        mock_intake.return_value = {
            "total_calories": 1200,
            "entries": [{}, {}, {}],
            "protein_g": 60.0,
            "carbs_g": 100.0,
            "fat_g": 40.0,
            "fiber_g": 15.0,
        }

        msg = check_logging_status()
        assert msg is None

    @patch("caltrack.reminder.get_daily_intake")
    def test_one_entry_triggers_reminder(self, mock_intake: MagicMock) -> None:
        """Test that 1-2 entries triggers a gentle reminder."""
        mock_intake.return_value = {
            "total_calories": 400,
            "entries": [{}],
            "protein_g": 20.0,
            "carbs_g": 30.0,
            "fat_g": 15.0,
            "fiber_g": 5.0,
        }

        msg = check_logging_status()
        assert msg is not None
        assert "1 entry" in msg
        assert "400" in msg
