"""
The costing and pricing maths, with no Streamlit in sight.

These functions used to live inside the Streamlit script, which meant the
pricing arithmetic could not be tested without booting a UI. They are pure
functions of their arguments now, so `tests/` can assert on them directly.

Vocabulary, because two of these are routinely confused:

- **recovery** (also called yield) is the fraction of raw material that
  survives processing. A 100 lb primal that trims down to 68 lb of saleable
  product has a recovery of 0.68. Costs are *divided* by recovery, because you
  have to buy 1/0.68 lb of raw material for every saleable pound.
- **margin** is profit as a fraction of *price*, not of cost. Price is
  therefore `cost / (1 - margin)`, not `cost * (1 + margin)`. The second is
  markup, and using it where margin is meant understates price.
"""

from __future__ import annotations

import math
from typing import Any

# Freight per lb by inbound lane.
FREIGHT_RATES: dict[str, float] = {
    "Inbound Consolidator": 0.07,
    "Local Pickup": 0.11,
    "Alberta": 0.205,
    "Ontario/Quebec": 0.25,
}

DEFAULT_FREIGHT = 0.0
DEFAULT_RECOVERY = 1.0
DEFAULT_BASE_MARGIN = 0.17
DEFAULT_LIST_MARGIN = 0.25


def safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce to float, returning `default` for None, NaN and junk."""
    try:
        if value is None:
            return default
        result = float(value)
        if math.isnan(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def clean_item_code(code: Any) -> str:
    """
    Normalise an item code that may have arrived from Excel as a number.

    Excel turns a code like 13667 into the float 13667.0, and a code with a
    thousands separator into "13,667". Both have to land on the same string or
    the two uploaded sheets will not join.
    """
    text = str(code).strip()
    try:
        value = float(text.replace(",", ""))
        return str(int(value)) if value.is_integer() else str(value)
    except (TypeError, ValueError):
        return text.replace(",", "")


def normalize_recovery(value: Any, default: float = DEFAULT_RECOVERY) -> float:
    """
    Accept recovery as either a percentage (85) or a fraction (0.85).

    Spreadsheets carry it both ways, so the single source of truth for the
    convention lives here rather than being re-implemented at each call site.
    Anything above 1 is read as a percentage. Exactly 1.0 is read as 100%,
    which is the reading that matters: a 1% recovery is not a real process.
    """
    recovery = safe_float(value, default)
    if recovery <= 0:
        return 0.0
    return recovery / 100.0 if recovery > 1 else recovery


def get_freight_cost(vendor: Any) -> float:
    """Freight per lb for an inbound lane, matched loosely on the vendor text."""
    text = str(vendor or "").strip()
    if not text:
        return DEFAULT_FREIGHT
    if "Consolidator" in text:
        return FREIGHT_RATES["Inbound Consolidator"]
    if "Local" in text or "Pickup" in text:
        return FREIGHT_RATES["Local Pickup"]
    if "Alberta" in text:
        return FREIGHT_RATES["Alberta"]
    if "Ontario" in text or "Quebec" in text:
        return FREIGHT_RATES["Ontario/Quebec"]
    return DEFAULT_FREIGHT


def calculate_actual_inv_cost(vendor_invoice_price: float, lb_per_billing_uom: float) -> float:
    """Invoice price converted to a per-pound cost."""
    if lb_per_billing_uom == 0:
        return vendor_invoice_price
    return vendor_invoice_price / lb_per_billing_uom


def calculate_market_cost(actual_inv_cost: float, adj: float) -> float:
    return actual_inv_cost + adj


def calculate_landed_cost(market_cost: float, freight: float) -> float:
    return market_cost + freight


def calculate_recovery_input(market_cost: float, freight: float, recovery: Any) -> float:
    """
    Landed cost grossed up for processing loss.

    `recovery` is normalised here, so passing 85 and passing 0.85 give the same
    answer. They previously did not: this function divided by the raw value
    while the spreadsheet auto-fill path divided by the normalised one, so the
    same input produced two different costs depending on which path ran.
    """
    rate = normalize_recovery(recovery)
    if rate == 0:
        return 0.0
    return (market_cost + freight) / rate


def calculate_waste_output(raw_material_cost: float, recovery: Any) -> float:
    """The cost of the material lost to trim and shrink."""
    rate = normalize_recovery(recovery)
    if rate == 0:
        return 0.0
    return (raw_material_cost / rate) - raw_material_cost


def calculate_trim_recovery(trim_cost_lb: float, trim_percent: Any, recovery: Any) -> float:
    """Credit for trim that is sold on rather than thrown away."""
    rate = normalize_recovery(recovery)
    if rate == 0:
        return 0.0
    trim = normalize_recovery(trim_percent, default=0.0)
    return (trim_cost_lb * trim) / rate


def calculate_price_from_margin(cost: float, margin: Any) -> float:
    """
    Price that yields `margin` as a fraction of price.

    A margin at or above 100% has no finite price, so the cost is returned
    unchanged rather than dividing by zero or going negative.
    """
    rate = safe_float(margin, 0.0)
    if rate > 1:
        rate = rate / 100.0
    if rate >= 1:
        return cost
    if rate <= 0:
        return cost
    return cost / (1 - rate)


def calculate_margin_dollars(base_price: float, final_cost: float) -> float:
    return base_price - final_cost


def calculate_margin_percent(price: float, cost: float) -> float:
    """Realised margin as a fraction of price. Zero price has no margin."""
    if price == 0:
        return 0.0
    return (price - cost) / price


def build_cost_stack(
    *,
    vendor_invoice_price: float,
    lb_per_billing_uom: float,
    adj: float = 0.0,
    vendor: str = "",
    recovery: Any = DEFAULT_RECOVERY,
    labour_per_lb: float = 0.0,
    sticker_per_lb: float = 0.0,
    base_margin: Any = DEFAULT_BASE_MARGIN,
    list_margin: Any = DEFAULT_LIST_MARGIN,
) -> dict[str, float]:
    """
    Walk one item from vendor invoice to selling price.

    Returns every intermediate step, because when a price looks wrong the
    question is always *which* step moved.
    """
    actual_inv_cost = calculate_actual_inv_cost(vendor_invoice_price, lb_per_billing_uom)
    market_cost = calculate_market_cost(actual_inv_cost, adj)
    freight = get_freight_cost(vendor)
    landed_cost = calculate_landed_cost(market_cost, freight)
    recovery_input = calculate_recovery_input(market_cost, freight, recovery)
    final_cost = recovery_input + labour_per_lb + sticker_per_lb
    base_price = calculate_price_from_margin(final_cost, base_margin)
    list_price = calculate_price_from_margin(final_cost, list_margin)
    return {
        "actual_inv_cost": actual_inv_cost,
        "market_cost": market_cost,
        "freight": freight,
        "landed_cost": landed_cost,
        "recovery_input": recovery_input,
        "final_cost": final_cost,
        "base_price": base_price,
        "list_price": list_price,
        "base_margin_dollars": calculate_margin_dollars(base_price, final_cost),
        "realised_base_margin": calculate_margin_percent(base_price, final_cost),
    }
