"""Tests for the nutrition module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from caltrack.nutrition import (
    FoodResult,
    format_results,
    scale_to_portion,
    search_usda,
)


class TestScaleToPortion:
    """Tests for portion scaling."""

    def test_scale_200g(self) -> None:
        """Test scaling 100g values to 200g portion."""
        base = FoodResult(
            name="Chicken Breast",
            calories=165,
            protein_g=31.0,
            carbs_g=0.0,
            fat_g=3.6,
            fiber_g=0.0,
            source="usda",
            source_id="12345",
        )
        scaled = scale_to_portion(base, 200)
        assert scaled.calories == 330
        assert scaled.protein_g == 62.0
        assert scaled.fat_g == 7.2
        assert "200g" in scaled.name

    def test_scale_50g(self) -> None:
        """Test scaling to a smaller portion."""
        base = FoodResult(
            name="Almonds",
            calories=579,
            protein_g=21.2,
            carbs_g=21.6,
            fat_g=49.9,
            fiber_g=12.5,
            source="usda",
            source_id="12345",
        )
        scaled = scale_to_portion(base, 50)
        assert scaled.calories == 290
        assert scaled.protein_g == 10.6

    def test_scale_zero_grams(self) -> None:
        """Test scaling to 0 grams."""
        base = FoodResult(
            name="Rice",
            calories=130,
            protein_g=2.7,
            carbs_g=28.0,
            fat_g=0.3,
            fiber_g=0.4,
            source="usda",
            source_id="12345",
        )
        scaled = scale_to_portion(base, 0)
        assert scaled.calories == 0
        assert scaled.protein_g == 0.0


class TestFormatResults:
    """Tests for result formatting."""

    def test_format_multiple(self) -> None:
        """Test formatting multiple results."""
        results = [
            FoodResult(
                name="Chicken Breast",
                calories=165,
                protein_g=31.0,
                carbs_g=0.0,
                fat_g=3.6,
                fiber_g=0.0,
                source="usda",
                source_id="1",
            ),
            FoodResult(
                name="Brown Rice",
                calories=123,
                protein_g=2.6,
                carbs_g=26.0,
                fat_g=1.0,
                fiber_g=1.8,
                source="usda",
                source_id="2",
            ),
        ]
        text = format_results(results)
        assert "[1]" in text
        assert "[2]" in text
        assert "Chicken Breast" in text
        assert "Brown Rice" in text

    def test_format_empty(self) -> None:
        """Test formatting empty results."""
        text = format_results([])
        assert "No foods found" in text


class TestSearchUsda:
    """Tests for USDA search (mocked HTTP)."""

    @patch("caltrack.nutrition.httpx.Client")
    def test_search_success(self, mock_client_cls: MagicMock) -> None:
        """Test USDA search with mocked response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "foods": [
                {
                    "description": "Chicken, broiled",
                    "fdcId": 12345,
                    "foodNutrients": [
                        {"nutrientNumber": "208", "value": 165},
                        {"nutrientNumber": "203", "value": 31.0},
                        {"nutrientNumber": "205", "value": 0.0},
                        {"nutrientNumber": "204", "value": 3.6},
                        {"nutrientNumber": "291", "value": 0.0},
                    ],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        results = search_usda("chicken breast", "test_key")
        assert len(results) == 1
        assert results[0].name == "Chicken, broiled"
        assert results[0].calories == 165
        assert results[0].protein_g == 31.0
        assert results[0].source == "usda"
        assert results[0].source_id == "12345"

    @patch("caltrack.nutrition.httpx.Client")
    def test_search_empty(self, mock_client_cls: MagicMock) -> None:
        """Test USDA search with no results."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"foods": []}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        results = search_usda("nonexistent food", "test_key")
        assert len(results) == 0
