"""Small pure service helpers for the first V2 slice."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from drova_bot.domain.formatters import product_problem_flags
from drova_bot.domain.models import StationProduct


def collect_problem_products(
    products_by_station: Mapping[str, Iterable[StationProduct]],
) -> dict[str, list[StationProduct]]:
    """Return only station products that have at least one user-visible problem flag."""
    result: dict[str, list[StationProduct]] = {}
    for station_id, products in products_by_station.items():
        problem_products = [product for product in products if product_problem_flags(product)]
        if problem_products:
            result[station_id] = problem_products
    return result

