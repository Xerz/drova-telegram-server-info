"""Product export boundary for the first V2 slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ProductExportService:
    """Placeholder for products and product-time workbooks."""

    def products_filename(self, now: datetime) -> str:
        return f"drova-products-{now.strftime('%Y%m%d-%H%M%S')}.xlsx"

    def product_time_filename(self, now: datetime) -> str:
        return f"drova-product-time-{now.strftime('%Y%m%d-%H%M%S')}.xlsx"

