#!/usr/bin/env python3
"""Reminder script for food logging.

Checks today's intake log and outputs a reminder message if no food
has been logged recently. Designed to be called by a Hermes cron job.

Exit codes:
  0 — silent (nothing to report)
  1 — reminder output printed to stdout
"""

from __future__ import annotations

import sys
from datetime import datetime

from caltrack.db import get_connection, get_daily_intake, today_str


def check_logging_status() -> str | None:
    """Check if the user needs a food logging reminder.

    Returns:
        Reminder message if needed, None if silent.
    """
    day = today_str()
    conn = get_connection()

    intake = get_daily_intake(conn, day)

    now = datetime.now()
    hour = now.hour

    # If user has already logged 3+ entries today, no reminder needed
    if len(intake["entries"]) >= 3:
        return None

    # If it's late (past 9 PM) and they've logged at least 1 entry, no nag
    if hour >= 21 and len(intake["entries"]) >= 1:
        return None

    # Build reminder message
    entries_count = len(intake["entries"])
    logged_calories = intake["total_calories"]

    if entries_count == 0:
        if hour < 12:
            time_context = "morning"
        elif hour < 17:
            time_context = "afternoon"
        else:
            time_context = "evening"
        return (
            f"🍽️ {time_context.capitalize()} check-in: "
            f"You haven't logged any food yet today.\n"
            f"Tell me what you've eaten and I'll log it."
        )

    return (
        f"🍽️ Reminder: You've logged {entries_count} "
        f"{'entry' if entries_count == 1 else 'entries'} "
        f"({logged_calories} cal) so far today.\n"
        f"Log anything else you've eaten?"
    )


def main() -> None:
    """Entry point for reminder script."""
    msg = check_logging_status()
    if msg:
        print(msg)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
