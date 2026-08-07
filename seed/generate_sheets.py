"""
Generate the two workbooks the calculator expects.

The tool takes a **cost sheet** (one row per item, carrying the whole cost
build-up from vendor invoice to selling price) and an **export sheet** (the
ERP's product list, which is what actually gets repriced). Neither is
something a reader would have, so this writes a synthetic pair with the exact
column names `validate_columns` requires.

Usage:
    python -m seed.generate_sheets
    python -m seed.generate_sheets --items 120 --seed 3
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from costing.formulas import (
    DEFAULT_BASE_MARGIN,
    DEFAULT_LIST_MARGIN,
    build_cost_stack,
    get_freight_cost,
)

DEFAULT_SEED = 613
DEFAULT_ITEMS = 90
OUT_DIR = Path("sample_data")
COST_SHEET = "Cost Sheet"
EXPORT_SHEET = "AllProducts"

VENDORS = (
    "Inbound Consolidator",
    "Local Pickup",
    "Alberta LTL",
    "Ontario/Quebec Freight",
    "Local Pickup",
    "Inbound Consolidator",
)

PROTEINS = ("Beef", "Pork", "Poultry", "Lamb", "Seafood", "Charcuterie")
CUTS = {
    "Beef": ("Ribeye", "Striploin", "Brisket", "Short Rib", "Chuck Roll"),
    "Pork": ("Belly", "Loin", "Back Rib", "Shoulder Butt"),
    "Poultry": ("Breast", "Thigh", "Wing", "Whole Bird"),
    "Lamb": ("Rack", "Leg", "Shoulder", "Shank"),
    "Seafood": ("Salmon Fillet", "Halibut Fillet", "Spot Prawn"),
    "Charcuterie": ("Prosciutto", "Coppa", "Pancetta"),
}
SUPPLIERS = (
    "Cascade Meats", "Fraser Provisions", "Ridgeline Packing Co",
    "Silverbrook Farms", "Kootenay Seafoods", "Alderwood Curing House",
)


def build_cost_sheet(rng: np.random.Generator, n: int) -> pd.DataFrame:
    rows = []
    for i in range(n):
        protein = PROTEINS[rng.integers(len(PROTEINS))]
        cut = CUTS[protein][rng.integers(len(CUTS[protein]))]
        vendor = VENDORS[rng.integers(len(VENDORS))]

        lb_per_uom = float(np.clip(rng.normal(11.0, 4.0), 2.0, 40.0))
        cost_per_lb = float(np.clip(rng.lognormal(np.log(7.0), 0.45), 1.5, 40.0))
        invoice_price = cost_per_lb * lb_per_uom
        adj = float(rng.normal(0.0, 0.15))
        # Whole-muscle primals lose most to trimming; ready-to-eat items barely
        # lose anything, which is why recovery has to be per item.
        recovery = float(np.clip(rng.normal(0.72 if protein != "Charcuterie" else 0.95, 0.10), 0.45, 0.99))
        labour = float(np.clip(rng.normal(0.35, 0.18), 0.0, 1.6))
        sticker = 0.05 if rng.random() < 0.4 else 0.0
        trim_pct = float(np.clip(rng.normal(0.08, 0.05), 0.0, 0.30))
        trim_cost_lb = cost_per_lb * float(rng.uniform(0.15, 0.45))

        stack = build_cost_stack(
            vendor_invoice_price=invoice_price,
            lb_per_billing_uom=lb_per_uom,
            adj=adj,
            vendor=vendor,
            recovery=recovery,
            labour_per_lb=labour,
            sticker_per_lb=sticker,
            base_margin=DEFAULT_BASE_MARGIN,
            list_margin=DEFAULT_LIST_MARGIN,
        )

        raw_material_per_lb = stack["recovery_input"]
        waste_output = raw_material_per_lb - stack["landed_cost"]

        row = {
            "Item Code": str(20000 + i),
            "Description": f"{cut} {protein}",
            "lb Per Billling UOM": round(lb_per_uom, 3),
            "Supplier S Name": SUPPLIERS[rng.integers(len(SUPPLIERS))],
            "Vendor Invoice Price": round(invoice_price, 4),
            "Actual Inv Cost(lb)": round(stack["actual_inv_cost"], 4),
            "Adj": round(adj, 4),
            "Market Cost": round(stack["market_cost"], 4),
            "Freight": round(get_freight_cost(vendor), 4),
            "Landed Cost": round(stack["landed_cost"], 4),
            "Recovery %": round(recovery * 100, 2),
            "Recovery Input": round(stack["recovery_input"], 4),
            "Raw Material Input Qty": round(1.0 / recovery, 4),
            "Raw Material Per LB Cost": round(raw_material_per_lb, 4),
            "Trim %": round(trim_pct * 100, 2),
            "Trim Cost/LB": round(trim_cost_lb, 4),
            "Recovery": round(trim_cost_lb * trim_pct / recovery, 4),
            "Input Cost": round(raw_material_per_lb, 4),
            "Waste Output $": round(waste_output, 4),
            "Net Input Cost": round(raw_material_per_lb, 4),
            "Labour $": round(labour, 4),
            "Normal Sticker": round(sticker, 4),
            "Material + Labour": round(raw_material_per_lb + labour, 4),
            "New Final Cost (Lb)": round(stack["final_cost"], 4),
            "Column1": "",
            "Billling UOM Cost": round(stack["final_cost"] - sticker, 4),
            "Priced Sticker": round(sticker, 4),
            "Final Cost": round(stack["final_cost"], 4),
            "Base Margin %": DEFAULT_BASE_MARGIN,
            "Margin $": round(stack["base_margin_dollars"], 4),
            "Base Price": round(stack["base_price"], 4),
            "List Price": round(stack["list_price"], 4),
            "List Margin %": DEFAULT_LIST_MARGIN,
        }
        # Four raw-material input slots; most items use one or two.
        used = int(rng.integers(1, 4))
        for slot in range(1, 5):
            if slot <= used:
                qty = round(float(rng.uniform(0.2, 1.0)), 3)
                unit = round(cost_per_lb * float(rng.uniform(0.8, 1.2)), 4)
            else:
                qty, unit = 0.0, 0.0
            row[f"Item-{slot}"] = f"{cut} input {slot}" if slot <= used else ""
            row[f"Qty-{slot}"] = qty
            row[f"Unit $-{slot}"] = unit
            row[f"Total $-{slot}"] = round(qty * unit, 4)
        rows.append(row)
    return pd.DataFrame(rows)


def build_export_sheet(cost_df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """
    The ERP product list. Deliberately not a perfect mirror of the cost sheet:
    it holds a few codes the cost sheet has never seen, and its prices are
    stale, which is the whole reason the tool exists.
    """
    export = pd.DataFrame(
        {
            "Product Code": cost_df["Item Code"],
            "Description": cost_df["Description"],
            "Cost Price": (cost_df["Final Cost"] * rng.uniform(0.9, 1.05, len(cost_df))).round(4),
            "Base Price": (cost_df["Base Price"] * rng.uniform(0.92, 1.04, len(cost_df))).round(4),
            "Suggested Price": (cost_df["List Price"] * rng.uniform(0.95, 1.02, len(cost_df))).round(4),
        }
    )
    orphans = pd.DataFrame(
        {
            "Product Code": [str(90000 + i) for i in range(5)],
            "Description": [f"Discontinued line {i}" for i in range(5)],
            "Cost Price": np.round(rng.uniform(4, 20, 5), 4),
            "Base Price": np.round(rng.uniform(6, 28, 5), 4),
            "Suggested Price": np.round(rng.uniform(7, 32, 5), 4),
        }
    )
    return pd.concat([export, orphans], ignore_index=True)


def generate(*, seed: int = DEFAULT_SEED, items: int = DEFAULT_ITEMS):
    rng = np.random.default_rng(seed)
    cost_df = build_cost_sheet(rng, items)
    export_df = build_export_sheet(cost_df, rng)
    return cost_df, export_df


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--items", type=int, default=DEFAULT_ITEMS)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)

    cost_df, export_df = generate(seed=args.seed, items=args.items)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    cost_path = args.out_dir / "cost_sheet.xlsx"
    export_path = args.out_dir / "export_sheet.xlsx"
    with pd.ExcelWriter(cost_path, engine="openpyxl") as writer:
        cost_df.to_excel(writer, sheet_name=COST_SHEET, index=False)
    with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
        export_df.to_excel(writer, sheet_name=EXPORT_SHEET, index=False)

    print(f"wrote {cost_path}   ({len(cost_df)} items x {len(cost_df.columns)} cols, sheet '{COST_SHEET}')")
    print(f"wrote {export_path} ({len(export_df)} rows x {len(export_df.columns)} cols, sheet '{EXPORT_SHEET}')")
    print()
    print(f"  median final cost : ${cost_df['Final Cost'].median():.2f}/lb")
    print(f"  median base price : ${cost_df['Base Price'].median():.2f}/lb")
    print(f"  median recovery   : {cost_df['Recovery %'].median():.1f}%")
    print(f"  codes not in cost sheet: {len(export_df) - len(cost_df)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
