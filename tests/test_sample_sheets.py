"""
The generated sample sheets must satisfy the app's own column validation.

Without this the README's "generate the sheets and upload them" instruction
can rot silently: someone adds a required column to the app and the sample
data stops loading, which nobody notices until a reader tries it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from costing.formulas import calculate_margin_percent
from seed.generate_sheets import generate

# Mirrors the `cost_required` set the Streamlit app validates against.
COST_REQUIRED = {
    "Item Code", "lb Per Billling UOM", "Supplier S Name", "Vendor Invoice Price",
    "Actual Inv Cost(lb)", "Adj", "Market Cost", "Freight", "Landed Cost",
    "Recovery %", "Recovery Input", "Raw Material Input Qty", "Raw Material Per LB Cost",
    "Trim %", "Trim Cost/LB", "Recovery", "Input Cost", "Waste Output $",
    "Net Input Cost", "Labour $", "Normal Sticker", "Material + Labour",
    "New Final Cost (Lb)", "Column1", "Billling UOM Cost", "Priced Sticker", "Final Cost",
    "Base Margin %", "Margin $", "Base Price", "List Price", "List Margin %",
} | {f"{prefix}-{i}" for i in range(1, 5) for prefix in ("Item", "Qty", "Unit $", "Total $")}

EXPORT_REQUIRED = {"Product Code", "Cost Price", "Base Price", "Suggested Price"}


@pytest.fixture(scope="module")
def sheets():
    return generate(items=40)


def test_cost_sheet_has_every_required_column(sheets):
    cost_df, _ = sheets
    missing = COST_REQUIRED - set(cost_df.columns)
    assert not missing, f"cost sheet is missing {sorted(missing)}"


def test_export_sheet_has_every_required_column(sheets):
    _, export_df = sheets
    missing = EXPORT_REQUIRED - set(export_df.columns)
    assert not missing, f"export sheet is missing {sorted(missing)}"


def test_the_cost_build_up_is_internally_consistent(sheets):
    cost_df, _ = sheets
    # Each step of the stack has to be at least the one before it.
    landed = cost_df["Market Cost"] + cost_df["Freight"]
    assert np.allclose(landed, cost_df["Landed Cost"], atol=1e-3)
    assert (cost_df["Recovery Input"] >= cost_df["Landed Cost"] - 1e-3).all()
    assert (cost_df["Final Cost"] >= cost_df["Recovery Input"] - 1e-3).all()
    assert (cost_df["Base Price"] > cost_df["Final Cost"]).all()
    assert (cost_df["List Price"] > cost_df["Base Price"]).all()


def test_prices_realise_the_margin_they_claim(sheets):
    cost_df, _ = sheets
    realised = (cost_df["Base Price"] - cost_df["Final Cost"]) / cost_df["Base Price"]
    assert np.allclose(realised, cost_df["Base Margin %"], atol=1e-3)
    # And the scalar helper agrees with the vectorised check above.
    first = cost_df.iloc[0]
    assert calculate_margin_percent(first["Base Price"], first["Final Cost"]) == pytest.approx(
        first["Base Margin %"], abs=1e-3
    )


def test_recovery_is_a_plausible_yield(sheets):
    cost_df, _ = sheets
    assert cost_df["Recovery %"].between(40, 100).all()


def test_export_sheet_contains_codes_the_cost_sheet_does_not(sheets):
    """
    The tool's job includes reporting codes it could not price, so the sample
    data has to contain some or that path is never exercised.
    """
    cost_df, export_df = sheets
    orphans = set(export_df["Product Code"]) - set(cost_df["Item Code"])
    assert orphans, "export sheet should hold codes absent from the cost sheet"


def test_generation_is_deterministic():
    first, _ = generate(items=20, seed=7)
    second, _ = generate(items=20, seed=7)
    pd.testing.assert_frame_equal(first, second)
