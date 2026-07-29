"""Daily nutrition report generation.

Syncs Garmin expenditure data, computes daily summaries, and formats
a rich Markdown report with meal breakdown, macros, calorie deficit,
weight-loss trajectory, and 7-day rolling trend.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from caltrack.db import (
    compute_daily_summary,
    get_date_range_summary,
    get_expenditure,
)
from caltrack.garmin import sync_garmin_day

# 3500 kcal ≈ 1 lb of body fat (standard approximation)
KCALS_PER_LB = 3500.0

# 1 kg ≈ 2.20462 lbs
KG_PER_LB = 0.453592


def _meal_order(meal: str) -> int:
    """Sort meals in canonical order."""
    order = {"breakfast": 0, "lunch": 1, "dinner": 2, "snack": 3}
    return order.get(meal.lower(), 4)


def _get_meal_breakdown(conn: sqlite3.Connection, day: str) -> list[dict[str, Any]]:
    """Get intake grouped by meal for a date, with individual food items.

    Args:
        conn: SQLite database connection.
        day: Date string YYYY-MM-DD.

    Returns:
        List of meal dicts, each containing:
        - meal_name, calories, protein_g, carbs_g, fat_g, fiber_g, items
        - foods: list of {description, calories, protein_g, carbs_g, fat_g}
    """
    rows = conn.execute(
        """SELECT meal_name, food_description, calories, protein_g,
                  carbs_g, fat_g, fiber_g
           FROM intake WHERE date = ? ORDER BY id""",
        (day,),
    ).fetchall()

    meals: dict[str, dict[str, Any]] = {}
    for r in rows:
        meal = r["meal_name"] or "snack"
        if meal not in meals:
            meals[meal] = {
                "meal_name": meal,
                "calories": 0,
                "protein_g": 0.0,
                "carbs_g": 0.0,
                "fat_g": 0.0,
                "fiber_g": 0.0,
                "items": 0,
                "foods": [],
            }
        m = meals[meal]
        m["calories"] += r["calories"] or 0
        m["protein_g"] += r["protein_g"] or 0.0
        m["carbs_g"] += r["carbs_g"] or 0.0
        m["fat_g"] += r["fat_g"] or 0.0
        m["fiber_g"] += r["fiber_g"] or 0.0
        m["items"] += 1
        m["foods"].append(
            {
                "description": r["food_description"] or "unknown",
                "calories": r["calories"] or 0,
                "protein_g": r["protein_g"] or 0.0,
                "carbs_g": r["carbs_g"] or 0.0,
                "fat_g": r["fat_g"] or 0.0,
            }
        )

    result = list(meals.values())
    result.sort(key=lambda m: _meal_order(m["meal_name"]))
    for m in result:
        m["protein_g"] = round(m["protein_g"], 1)
        m["carbs_g"] = round(m["carbs_g"], 1)
        m["fat_g"] = round(m["fat_g"], 1)
        m["fiber_g"] = round(m["fiber_g"], 1)
    return result


def _format_deficit_trajectory(deficit: float) -> str:
    """Format weight-loss trajectory from daily calorie deficit.

    Args:
        deficit: Daily energy balance (intake - expenditure).
            Negative = deficit (losing weight), positive = surplus.

    Returns:
        Human-readable trajectory string.
    """
    if deficit == 0:
        return "Maintenance — no projected weight change"

    daily_lbs = deficit / KCALS_PER_LB
    weekly_lbs = daily_lbs * 7
    weekly_kg = weekly_lbs * KG_PER_LB

    if deficit < 0:
        return (
            f"📉 At this rate: **{abs(weekly_lbs):.1f} lbs/week** "
            f"({abs(weekly_kg):.1f} kg/week) loss"
        )
    return (
        f"📈 At this rate: **{weekly_lbs:.1f} lbs/week** ({weekly_kg:.1f} kg/week) gain"
    )


def _format_rolling_trend(conn: sqlite3.Connection, end_date: str) -> str:
    """Format 7-day rolling trend from daily_summary table.

    Args:
        conn: SQLite database connection.
        end_date: End date YYYY-MM-DD for the rolling window.

    Returns:
        Formatted trend string, or a message if insufficient data.
    """
    end = date.fromisoformat(end_date)
    start = end - timedelta(days=6)
    summaries = get_date_range_summary(conn, start.isoformat(), end_date)

    # Only count days where food was actually logged — days with zero
    # intake (before tracking started) would skew the deficit average
    days_with_data = [s for s in summaries if (s["total_intake"] or 0) > 0]
    if len(days_with_data) < 2:
        return "_Insufficient data for trend (need 2+ days with food logs)_"

    # Show how many days had intake data out of the 7-day window
    tracked = len(days_with_data)
    untracked = len(summaries) - tracked

    total_intake = sum(s["total_intake"] or 0 for s in days_with_data)
    total_expenditure = sum(s["total_expenditure"] or 0 for s in days_with_data)
    count = len(days_with_data)

    avg_intake = total_intake // count
    avg_expenditure = total_expenditure // count
    avg_deficit = avg_intake - avg_expenditure

    # Weight trend if available
    weights = [
        s["rolling_weight_kg"] or s["weight_kg"]
        for s in days_with_data
        if (s["rolling_weight_kg"] or s["weight_kg"]) is not None
    ]
    weight_trend = ""
    if len(weights) >= 2:
        start_w = weights[0]
        end_w = weights[-1]
        delta = end_w - start_w
        direction = "↓" if delta < 0 else "↑" if delta > 0 else "→"
        weight_trend = (
            f"\nWeight trend: {start_w:.1f}kg → {end_w:.1f}kg "
            f"({direction}{abs(delta):.1f}kg)"
        )

    trajectory = _format_deficit_trajectory(avg_deficit)

    untracked_note = ""
    if untracked:
        plural = "s" if untracked != 1 else ""
        untracked_note = f" ({untracked} day{plural} no food logs)"
    lines = [
        f"**{count}-day avg** (of 7{untracked_note}): "
        f"{avg_intake} in / {avg_expenditure} out = "
        f"{avg_deficit:+d} cal/day",
        trajectory,
    ]
    if weight_trend:
        lines.append(weight_trend)

    return "\n".join(lines)


def generate_report(
    conn: sqlite3.Connection,
    day: str,
    sync_garmin: bool = True,
) -> str:
    """Generate a full daily nutrition report.

    Syncs Garmin expenditure, computes daily summary, and formats
    a Markdown report with meals, macros, deficit, and trend.

    Args:
        conn: SQLite database connection.
        day: Date string YYYY-MM-DD to report on.
        sync_garmin: If True, sync Garmin data before computing.

    Returns:
        Formatted Markdown report string.
    """
    # Sync Garmin expenditure data for the target date
    sync_status = ""
    if sync_garmin:
        rec = sync_garmin_day(conn, day)
        if rec:
            sync_status = (
                f"Garmin synced: {rec.active_calories} active + "
                f"{rec.bmr_calories} BMR = {rec.total_calories} total"
            )
        else:
            sync_status = "No Garmin data available for this date"
    else:
        sync_status = "Garmin sync skipped"

    # Compute and store the daily summary
    summary = compute_daily_summary(conn, day)
    exp = get_expenditure(conn, day)

    total_intake = summary["total_intake"]
    total_expenditure = summary["total_expenditure"]
    deficit = summary["energy_balance"]
    protein_g = summary["protein_g"]
    carbs_g = summary["carbs_g"]
    fat_g = summary["fat_g"]

    # Meal breakdown
    meals = _get_meal_breakdown(conn, day)

    # Build the report
    lines: list[str] = []
    lines.append(f"## 📊 Daily Report — {day}\n")

    # Sync status
    lines.append(f"_{sync_status}_\n")

    # Meal breakdown — show each food item with description, then subtotal
    if meals:
        lines.append("### Meals\n")
        for m in meals:
            lines.append(f"**{m['meal_name'].title()}** ({m['calories']} cal)")
            lines.append("")
            lines.append("| Item | Cal | Protein | Carbs | Fat |")
            lines.append("|------|-----|---------|-------|-----|")
            for food in m["foods"]:
                lines.append(
                    f"| {food['description']} | {food['calories']} | "
                    f"{food['protein_g']:.0f}g | "
                    f"{food['carbs_g']:.0f}g | "
                    f"{food['fat_g']:.0f}g |"
                )
            lines.append(
                f"| **Subtotal** | **{m['calories']}** | "
                f"**{m['protein_g']:.0f}g** | "
                f"**{m['carbs_g']:.0f}g** | "
                f"**{m['fat_g']:.0f}g** |"
            )
            lines.append("")

    # Daily totals
    lines.append("### Daily Totals\n")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| **Intake** | {total_intake} cal |")
    if exp:
        lines.append(
            f"| **Burned** | {total_expenditure} cal "
            f"(BMR: {exp.bmr_calories}, Active: {exp.active_calories}) |"
        )
    else:
        lines.append(f"| **Burned** | {total_expenditure} cal (no Garmin data) |")
    lines.append(f"| **Deficit** | {deficit:+d} cal |")
    lines.append(f"| **Macros** | P:{protein_g:.0f}g C:{carbs_g:.0f}g F:{fat_g:.0f}g |")
    lines.append("")

    # Weight loss trajectory
    lines.append("### Weight-Loss Trajectory\n")
    lines.append(_format_deficit_trajectory(deficit))
    lines.append("")

    # 7-day rolling trend
    lines.append("### 7-Day Rolling Trend\n")
    lines.append(_format_rolling_trend(conn, day))

    return "\n".join(lines)
