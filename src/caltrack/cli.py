"""CLI entry point for calorie tracker.

Subcommands:
  log      — Add a food intake entry (manual calories or USDA search)
  sync     — Pull expenditure data from Garmin Connect
  status   — Show today's intake, expenditure, and balance
  targets  — Show computed daily calorie/macro targets
  summary  — Show 7-day or N-day rolling summary
  search   — Search USDA for a food and show nutrition
  barcode  — Look up a product by barcode via Open Food Facts
"""

from __future__ import annotations

import os
import sys

import click

from caltrack.db import (
    IntakeRecord,
    add_intake,
    compute_daily_summary,
    get_connection,
    get_daily_intake,
    get_date_range_summary,
    get_expenditure,
    today_str,
)
from caltrack.nutrition import (
    format_results,
    scale_to_portion,
    search_openfoodfacts,
    search_usda,
)
from caltrack.targets import format_targets, get_daily_targets


def get_usda_key() -> str:
    """Get USDA API key from environment."""
    key = os.environ.get("USDA_API_KEY", "")
    if not key:
        click.echo(
            "Error: USDA_API_KEY not set. Get a free key at "
            "https://fdc.nal.usda.gov/api-key-signup",
            err=True,
        )
        sys.exit(1)
    return key


@click.group()
def main() -> None:
    """Calorie tracker with Garmin integration."""


@main.command()
@click.option("--calories", type=int, help="Manual calorie count")
@click.option("--protein", type=float, default=0.0, help="Protein in grams")
@click.option("--carbs", type=float, default=0.0, help="Carbs in grams")
@click.option("--fat", type=float, default=0.0, help="Fat in grams")
@click.option("--fiber", type=float, default=0.0, help="Fiber in grams")
@click.option(
    "--name",
    default="snack",
    help="Meal name (breakfast/lunch/dinner/snack)",
)
@click.option("--date", "day", default=None, help="Date YYYY-MM-DD (default: today)")
@click.argument("food_description", required=False)
def log(
    calories: int | None,
    protein: float,
    carbs: float,
    fat: float,
    fiber: float,
    name: str,
    day: str | None,
    food_description: str | None,
) -> None:
    """Log a food intake entry.

    Either provide manual calories with --calories, or pass a food
    description to search USDA. If no USDA_API_KEY is set, manual mode
    is required.

    Examples:
      caltrack log --calories 350 --protein 30 --name dinner "chicken and rice"
      caltrack log --name breakfast "2 eggs and toast"
    """
    day = day or today_str()
    conn = get_connection()

    if calories is not None:
        rec = IntakeRecord(
            date=day,
            meal_name=name,
            food_description=food_description or "manual entry",
            calories=calories,
            protein_g=protein,
            carbs_g=carbs,
            fat_g=fat,
            fiber_g=fiber,
            source="manual",
        )
        row_id = add_intake(conn, rec)
        click.echo(f"✅ Logged: {rec.food_description} — {calories} cal ({name})")
        click.echo(f"   Row ID: {row_id}")
    elif food_description:
        key = get_usda_key()
        results = search_usda(food_description, key)
        click.echo(format_results(results))
        if not results:
            click.echo("Use --calories to log manually.")
        else:
            click.echo("\nUse: caltrack add-by-id <fdc_id> <grams> --name <meal>")
    else:
        click.echo("Provide --calories or a food description to search.", err=True)
        sys.exit(1)

    intake = get_daily_intake(conn, day)
    click.echo(f"\n📊 Today's total: {intake['total_calories']} cal")


@main.command()
@click.option("--date", "day", default=None, help="Date YYYY-MM-DD (default: today)")
def status(day: str | None) -> None:
    """Show today's calorie balance."""
    day = day or today_str()
    conn = get_connection()

    intake = get_daily_intake(conn, day)
    exp = get_expenditure(conn, day)
    targets = get_daily_targets(conn, day)

    click.echo(f"📊 Status for {day}\n")
    click.echo(f"Intake:   {intake['total_calories']} cal")
    if exp:
        click.echo(
            f"Burned:   {exp.total_calories} cal "
            f"(BMR: {exp.bmr_calories}, Active: {exp.active_calories})"
        )
    else:
        click.echo("Burned:   (no Garmin data — using estimate)")

    balance = intake["total_calories"] - (exp.total_calories if exp else targets.tdee)
    remaining = targets.target_calories - intake["total_calories"]

    click.echo(
        f"\nTarget:   {targets.target_calories} cal (deficit: {targets.deficit:+d})"
    )
    click.echo(f"Balance:  {balance:+d} cal vs TDEE")
    click.echo(f"Remaining: {remaining} cal left for today")

    if intake["total_calories"] > 0:
        click.echo(
            f"\nMacros:   P:{intake['protein_g']}g "
            f"C:{intake['carbs_g']}g F:{intake['fat_g']}g"
        )

    if remaining < 0:
        click.echo(f"\n⚠️  Over target by {-remaining} cal")
    elif remaining < 200:
        click.echo(f"\n⚠️  Only {remaining} cal left today")


@main.command()
@click.option("--date", "day", default=None, help="Date YYYY-MM-DD (default: today)")
def targets(day: str | None) -> None:
    """Show computed daily targets."""
    day = day or today_str()
    conn = get_connection()
    t = get_daily_targets(conn, day)
    click.echo(format_targets(t))


@main.command()
@click.option("--days", default=7, help="Number of days to summarize")
def summary(days: int) -> None:
    """Show rolling N-day summary."""
    conn = get_connection()
    from datetime import date, timedelta

    end = date.fromisoformat(today_str())
    start = end - timedelta(days=days - 1)
    start_str = start.isoformat()
    end_str = end.isoformat()

    summaries = get_date_range_summary(conn, start_str, end_str)

    if not summaries:
        click.echo(f"No data for last {days} days. Run `caltrack sync` first.")
        return

    click.echo(f"📊 {days}-Day Summary ({start_str} to {end_str})\n")
    click.echo(f"{'Date':<12} {'Intake':>7} {'Burned':>7} {'Balance':>8} {'Weight':>8}")
    click.echo("-" * 48)

    total_intake = 0
    total_expenditure = 0
    count = 0

    for s in summaries:
        weight_str = f"{s['weight_kg']:.1f}kg" if s.get("weight_kg") else "—"
        click.echo(
            f"{s['date']:<12} {s['total_intake']:>7} "
            f"{s['total_expenditure']:>7} {s['energy_balance']:>+8} "
            f"{weight_str:>8}"
        )
        total_intake += s["total_intake"] or 0
        total_expenditure += s["total_expenditure"] or 0
        count += 1

    if count:
        click.echo("-" * 48)
        avg_intake = total_intake // count
        avg_exp = total_expenditure // count
        avg_balance = avg_intake - avg_exp
        click.echo(f"{'Average':<12} {avg_intake:>7} {avg_exp:>7} {avg_balance:>+8}")


@main.command()
@click.argument("query")
@click.option("--limit", default=5, help="Max results")
def search(query: str, limit: int) -> None:
    """Search USDA for a food item."""
    key = get_usda_key()
    results = search_usda(query, key, page_size=limit)
    click.echo(format_results(results))


@main.command()
@click.argument("barcode")
def barcode(barcode: str) -> None:
    """Look up a product by barcode via Open Food Facts."""
    result = search_openfoodfacts(barcode)
    if result:
        click.echo(
            f"📦 {result.name}\n"
            f"   {result.calories} cal/100g "
            f"(P:{result.protein_g}g C:{result.carbs_g}g F:{result.fat_g}g)"
        )
    else:
        click.echo(f"Product not found for barcode {barcode}")


@main.command()
@click.argument("fdc_id")
@click.argument("grams", type=float)
@click.option("--name", default="snack", help="Meal name")
@click.option("--date", "day", default=None, help="Date YYYY-MM-DD")
def add_by_id(
    fdc_id: str,
    grams: float,
    name: str,
    day: str | None,
) -> None:
    """Add a food by USDA FDC ID and portion size in grams."""
    day = day or today_str()
    key = get_usda_key()
    conn = get_connection()

    from caltrack.nutrition import lookup_usda_by_id

    base = lookup_usda_by_id(fdc_id, key)
    if not base:
        click.echo(f"Food ID {fdc_id} not found.", err=True)
        sys.exit(1)

    scaled = scale_to_portion(base, grams)
    rec = IntakeRecord(
        date=day,
        meal_name=name,
        food_description=scaled.name,
        calories=scaled.calories,
        protein_g=scaled.protein_g,
        carbs_g=scaled.carbs_g,
        fat_g=scaled.fat_g,
        fiber_g=scaled.fiber_g,
        source="usda",
        source_id=fdc_id,
    )
    add_intake(conn, rec)
    click.echo(
        f"✅ Logged: {scaled.name} — {scaled.calories} cal "
        f"(P:{scaled.protein_g}g C:{scaled.carbs_g}g F:{scaled.fat_g}g)"
    )

    intake = get_daily_intake(conn, day)
    click.echo(f"   Today's total: {intake['total_calories']} cal")


@main.command()
@click.option("--date", "day", default=None, help="Date YYYY-MM-DD (default: today)")
def summarize(day: str | None) -> None:
    """Compute and store daily summary for a date."""
    day = day or today_str()
    conn = get_connection()
    summary = compute_daily_summary(conn, day)
    click.echo(f"✅ Summary for {day}:")
    click.echo(
        f"   Intake: {summary['total_intake']} cal | "
        f"Expenditure: {summary['total_expenditure']} cal | "
        f"Balance: {summary['energy_balance']:+d} cal"
    )
    if summary.get("weight_kg"):
        click.echo(f"   Weight: {summary['weight_kg']:.1f} kg")


@main.command()
@click.option("--date", "day", default=None, help="Date YYYY-MM-DD (default: today)")
@click.option("--no-sync", is_flag=True, help="Skip Garmin sync, use DB data only")
def report(day: str | None, no_sync: bool) -> None:
    """Generate a full daily nutrition report.

    Syncs Garmin expenditure, computes meal-by-meal breakdown with macros,
    shows deficit and weight-loss trajectory, plus a 7-day rolling trend.

    Examples:
      caltrack report                    # today's report with Garmin sync
      caltrack report --date 2026-07-28  # specific date
      caltrack report --no-sync          # skip Garmin sync
    """
    from caltrack.report import generate_report

    day = day or today_str()
    conn = get_connection()
    output = generate_report(conn, day, sync_garmin=not no_sync)
    click.echo(output)


@main.command()
@click.option("--date", "day", default=None, help="Date YYYY-MM-DD (default: today)")
@click.option("--range", "date_range", is_flag=True, help="Sync last 7 days")
@click.option("--check", is_flag=True, help="Check if service is reachable")
def sync(day: str | None, date_range: bool, check: bool) -> None:
    """Pull expenditure data from the Garmin sync service.

    Requires GARMIN_SYNC_API_KEY and GARMIN_SYNC_URL environment variables.
    The service holds the actual Garmin credentials.
    """
    from caltrack.garmin import (
        check_service_health,
        sync_garmin_day,
        sync_garmin_range,
    )

    if check:
        if check_service_health():
            click.echo("✅ Garmin sync service is reachable")
        else:
            click.echo("❌ Service not reachable. Is it running?")
        return

    conn = get_connection()

    if date_range:
        from datetime import date, timedelta

        end = date.fromisoformat(today_str())
        start = end - timedelta(days=6)
        records = sync_garmin_range(conn, start.isoformat(), end.isoformat())
        click.echo(f"✅ Synced {len(records)} days from Garmin")
    else:
        day = day or today_str()
        rec = sync_garmin_day(conn, day)
        if rec:
            click.echo(
                f"✅ Synced {day}: {rec.active_calories} active + "
                f"{rec.bmr_calories} BMR = {rec.total_calories} total cal"
            )
        else:
            click.echo(f"No Garmin data for {day}")


if __name__ == "__main__":
    main()
