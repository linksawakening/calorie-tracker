"""Nutrition lookup via USDA FoodData Central and Open Food Facts.

USDA is primary for US reference data. Open Food Facts is used for
barcode lookup of packaged products worldwide.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

USDA_BASE = "https://api.nal.usda.gov/fdc/v1"
OFF_BASE = "https://world.openfoodfacts.org/api/v2"


@dataclass(frozen=True)
class FoodResult:
    """A nutrition lookup result."""

    name: str
    calories: int
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    source: str
    source_id: str
    serving_size: str | None = None


# USDA nutrient IDs for the macros we care about
# Foundation foods use 957/958 (Atwater) instead of 208 for energy
NUTRIENT_CALORIES = "208"
NUTRIENT_CALORIES_ALT = "957"
NUTRIENT_PROTEIN = "203"
NUTRIENT_CARB = "205"
NUTRIENT_FAT = "204"
NUTRIENT_FIBER = "291"


def search_usda(
    query: str,
    api_key: str,
    page_size: int = 5,
) -> list[FoodResult]:
    """Search USDA FoodData Central for foods.

    Args:
        query: Food search term.
        api_key: USDA FoodData Central API key.
        page_size: Max results to return.

    Returns:
        List of FoodResult objects with per-100g nutrients.
    """
    body = {
        "query": query,
        "pageSize": page_size,
        "dataType": ["SR Legacy", "Foundation"],
        "nutrients": [
            int(NUTRIENT_CALORIES),
            int(NUTRIENT_PROTEIN),
            int(NUTRIENT_CARB),
            int(NUTRIENT_FAT),
            int(NUTRIENT_FIBER),
        ],
    }

    with httpx.Client(timeout=15) as client:
        resp = client.post(
            f"{USDA_BASE}/foods/search",
            params={"api_key": api_key},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    results: list[FoodResult] = []
    for food in data.get("foods", []):
        nutrients = {
            n["nutrientNumber"]: n["value"] for n in food.get("foodNutrients", [])
        }

        calories = int(nutrients.get(NUTRIENT_CALORIES, 0))

        # Foundation foods omit 208 from search results; try the
        # details endpoint which has Atwater energy (957/958).
        if not calories and food.get("fdcId"):
            fdc_id = str(food["fdcId"])
            detailed = lookup_usda_by_id(fdc_id, api_key)
            if detailed and detailed.calories:
                calories = detailed.calories

        # Skip foods with no calories and no protein (incomplete USDA data)
        protein = round(float(nutrients.get(NUTRIENT_PROTEIN, 0)), 1)
        if not calories and protein == 0:
            continue

        results.append(
            FoodResult(
                name=food.get("description", "Unknown"),
                calories=calories,
                protein_g=protein,
                carbs_g=round(float(nutrients.get(NUTRIENT_CARB, 0)), 1),
                fat_g=round(float(nutrients.get(NUTRIENT_FAT, 0)), 1),
                fiber_g=round(float(nutrients.get(NUTRIENT_FIBER, 0)), 1),
                source="usda",
                source_id=str(food.get("fdcId", "")),
                serving_size="100g",
            )
        )

    return results


def lookup_usda_by_id(fdc_id: str, api_key: str) -> FoodResult | None:
    """Get detailed nutrition for a specific USDA FDC ID.

    Args:
        fdc_id: USDA FoodData Central ID.
        api_key: USDA API key.

    Returns:
        FoodResult with detailed nutrition, or None if not found.
    """
    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{USDA_BASE}/food/{fdc_id}", params={"api_key": api_key})
        resp.raise_for_status()
        food = resp.json()

    nutrients: dict[str, float] = {}
    for n in food.get("foodNutrients", []):
        nutrient = n.get("nutrient", {})
        number = nutrient.get("number", "")
        amount = n.get("amount", 0)
        if number:
            nutrients[number] = amount

    calories = int(
        nutrients.get(NUTRIENT_CALORIES, 0) or nutrients.get(NUTRIENT_CALORIES_ALT, 0)
    )
    return FoodResult(
        name=food.get("description", "Unknown"),
        calories=calories,
        protein_g=round(float(nutrients.get(NUTRIENT_PROTEIN, 0)), 1),
        carbs_g=round(float(nutrients.get(NUTRIENT_CARB, 0)), 1),
        fat_g=round(float(nutrients.get(NUTRIENT_FAT, 0)), 1),
        fiber_g=round(float(nutrients.get(NUTRIENT_FIBER, 0)), 1),
        source="usda",
        source_id=str(fdc_id),
        serving_size="100g",
    )


def search_openfoodfacts(barcode: str) -> FoodResult | None:
    """Look up a product by barcode via Open Food Facts.

    Args:
        barcode: Product barcode (EAN/UPC).

    Returns:
        FoodResult if found, None otherwise.
    """
    params = {
        "code": barcode,
        "fields": "product_name,energy_100g,proteins_100g,"
        "carbohydrates_100g,fat_100g,fiber_100g,nutris_grade",
    }

    with httpx.Client(timeout=15) as client:
        resp = client.get(f"{OFF_BASE}/product/{barcode}", params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != 1:
        return None

    product = data.get("product", {})
    # OFF always stores energy in kJ; convert to kcal
    energy_kj = product.get("energy_100g", 0)
    if energy_kj:
        energy_kcal = int(round(float(energy_kj) / 4.184))
    else:
        energy_kcal = 0

    return FoodResult(
        name=product.get("product_name", "Unknown Product"),
        calories=energy_kcal,
        protein_g=round(float(product.get("proteins_100g", 0)), 1),
        carbs_g=round(float(product.get("carbohydrates_100g", 0)), 1),
        fat_g=round(float(product.get("fat_100g", 0)), 1),
        fiber_g=round(float(product.get("fiber_100g", 0)), 1),
        source="off",
        source_id=barcode,
        serving_size="100g",
    )


def format_results(results: list[FoodResult]) -> str:
    """Format search results for display to user.

    Args:
        results: List of FoodResult objects.

    Returns:
        Formatted string with numbered results.
    """
    if not results:
        return "No foods found."

    lines: list[str] = []
    for i, r in enumerate(results, 1):
        macros = f"P:{r.protein_g}g C:{r.carbs_g}g F:{r.fat_g}g"
        lines.append(f"  [{i}] {r.name} — {r.calories} cal/100g ({macros})")

    return "\n".join(lines)


def scale_to_portion(
    result: FoodResult,
    grams: float,
) -> FoodResult:
    """Scale a per-100g FoodResult to a specific portion size.

    Args:
        result: FoodResult with per-100g values.
        grams: Portion size in grams.

    Returns:
        New FoodResult scaled to the specified grams.
    """
    ratio = grams / 100.0
    return FoodResult(
        name=f"{result.name} ({grams}g)",
        calories=int(round(result.calories * ratio)),
        protein_g=round(result.protein_g * ratio, 1),
        carbs_g=round(result.carbs_g * ratio, 1),
        fat_g=round(result.fat_g * ratio, 1),
        fiber_g=round(result.fiber_g * ratio, 1),
        source=result.source,
        source_id=result.source_id,
        serving_size=f"{grams}g",
    )
