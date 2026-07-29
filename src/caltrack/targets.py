"""TDEE and daily target computation.

Computes TDEE from Garmin data (measured) or Mifflin-St Jeor (estimate),
then applies the user's deficit target to produce a daily calorie ceiling.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from caltrack.db import ExpenditureRecord, get_expenditure

DEFAULT_DEFICIT = -300  # moderate cut for recomp
FALLBACK_BMR = 1850  # pre-Garmin estimate (placeholder until height confirmed)

# Body weight for macro computation — set via env or profile.toml
# Profile is read from secrets/profile.toml at runtime, not committed
_BODY_WEIGHT_LBS = float(os.environ.get("CALTRACK_BODY_WEIGHT_LBS", "189.3"))


@dataclass(frozen=True)
class DailyTargets:
    """Computed daily calorie and macro targets."""

    date: str
    tdee: int
    target_calories: int
    deficit: int
    active_calories: int
    bmr_calories: int
    source: str  # "garmin" or "estimate"

    # Macro targets (recomp-friendly: high protein)
    target_protein_g: int = 0
    target_carbs_g: int = 0
    target_fat_g: int = 0


def compute_targets_from_expenditure(
    exp: ExpenditureRecord,
    deficit: int = DEFAULT_DEFICIT,
) -> DailyTargets:
    """Compute daily targets from measured Garmin expenditure.

    Args:
        exp: Expenditure record for the day.
        deficit: Calorie deficit target (negative = cut).

    Returns:
        DailyTargets with measured TDEE and deficit-adjusted target.
    """
    tdee = exp.total_calories
    target = tdee + deficit

    # Recomp macros: 1g protein per lb body weight,
    # 25% of remaining cal from fat, rest carbs
    protein_g = int(_BODY_WEIGHT_LBS)  # ~1g/lb
    protein_cal = protein_g * 4
    fat_cal = int((target - protein_cal) * 0.25)
    fat_g = fat_cal // 9
    carbs_cal = target - protein_cal - fat_cal
    carbs_g = carbs_cal // 4

    return DailyTargets(
        date=exp.date,
        tdee=tdee,
        target_calories=target,
        deficit=deficit,
        active_calories=exp.active_calories,
        bmr_calories=exp.bmr_calories,
        source="garmin",
        target_protein_g=protein_g,
        target_carbs_g=carbs_g,
        target_fat_g=fat_g,
    )


def compute_estimated_targets(
    day: str,
    deficit: int = DEFAULT_DEFICIT,
    bmr: int = FALLBACK_BMR,
    active_calories: int = 450,
) -> DailyTargets:
    """Compute targets from estimated BMR + average activity.

    Used before Garmin data is available, or as fallback.

    Args:
        day: Date string YYYY-MM-DD.
        deficit: Calorie deficit target.
        bmr: Estimated BMR in calories.
        active_calories: Estimated daily active calories.

    Returns:
        DailyTargets with estimated TDEE.
    """
    tdee = bmr + active_calories
    target = tdee + deficit

    protein_g = int(_BODY_WEIGHT_LBS)
    protein_cal = protein_g * 4
    fat_cal = int((target - protein_cal) * 0.25)
    fat_g = fat_cal // 9
    carbs_cal = target - protein_cal - fat_cal
    carbs_g = carbs_cal // 4

    return DailyTargets(
        date=day,
        tdee=tdee,
        target_calories=target,
        deficit=deficit,
        active_calories=active_calories,
        bmr_calories=bmr,
        source="estimate",
        target_protein_g=protein_g,
        target_carbs_g=carbs_g,
        target_fat_g=fat_g,
    )


def get_daily_targets(
    conn: sqlite3.Connection,
    day: str,
    deficit: int = DEFAULT_DEFICIT,
) -> DailyTargets:
    """Get daily targets, preferring Garmin data over estimates.

    Args:
        conn: SQLite database connection.
        day: Date string YYYY-MM-DD.
        deficit: Calorie deficit target.

    Returns:
        DailyTargets from Garmin data if available, else estimated.
    """
    exp = get_expenditure(conn, day)
    if exp:
        return compute_targets_from_expenditure(exp, deficit)
    return compute_estimated_targets(day, deficit)


def format_targets(targets: DailyTargets) -> str:
    """Format daily targets for display.

    Args:
        targets: DailyTargets object.

    Returns:
        Human-readable summary string.
    """
    source_label = (
        " Garmin (measured)" if targets.source == "garmin" else " (estimated)"
    )
    return (
        f"📊 Daily Targets for {targets.date}\n"
        f"TDEE: {targets.tdee} cal{source_label}\n"
        f"  BMR: {targets.bmr_calories} cal | Active: {targets.active_calories} cal\n"
        f"Target: {targets.target_calories} cal ({targets.deficit:+d} deficit)\n"
        f"Macros: P:{targets.target_protein_g}g "
        f"C:{targets.target_carbs_g}g F:{targets.target_fat_g}g"
    )
