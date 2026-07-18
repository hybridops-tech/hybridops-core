"""Provider-neutral cloud cost summaries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CostEstimate:
    """A point-in-time estimate for active blueprint resources."""

    available: bool
    hourly: Decimal = Decimal("0")
    currency: str = "USD"
    basis: str = ""
    detail: str = ""

    def amount_for_seconds(self, seconds: int) -> Decimal:
        duration = Decimal(max(0, int(seconds))) / Decimal(3600)
        return (self.hourly * duration).quantize(Decimal("0.01"))


def format_money(amount: Decimal, currency: str) -> str:
    """Format a monetary amount without implying accounting precision."""

    return f"{str(currency or 'USD').upper()} {amount.quantize(Decimal('0.01'))}"
