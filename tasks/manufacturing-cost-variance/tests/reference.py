#!/usr/bin/env python3
"""Decimal-safe reference cost variance calculation."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

CENT = Decimal("0.01")
FACTORS = (
    "purchase_price",
    "fx",
    "material_yield_scrap",
    "labor_rate",
    "labor_efficiency",
    "machine_rate",
    "machine_utilization",
    "overhead_spending",
    "overhead_absorption",
    "volume",
)


def d(v: Any) -> Decimal:
    return Decimal(str(v))


def m(v: Decimal) -> str:
    return format(v.quantize(CENT, rounding=ROUND_HALF_UP), "f")


def read(root: Path, name: str) -> list[dict[str, str]]:
    with (root / name).open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def select_standard(rows: list[dict[str, str]], order: dict[str, str]) -> dict[str, str]:
    matches = [
        x
        for x in rows
        if x["product_id"] == order["product_id"]
        and x["effective_from"] <= order["release_date"] <= x["effective_to"]
    ]
    if len(matches) != 1:
        raise ValueError(f"standard selection failed for {order['work_order_id']}")
    return matches[0]


def compute(data: Path) -> dict[str, Any]:
    standards = read(data, "standards.csv")
    orders = sorted(read(data, "work_orders.csv"), key=lambda x: x["work_order_id"])
    materials = defaultdict(list)
    labor = defaultdict(list)
    machines = defaultdict(list)
    overhead = defaultdict(list)
    for row in read(data, "actual_materials.csv"):
        materials[row["work_order_id"]].append(row)
    for row in read(data, "labor_entries.csv"):
        labor[row["work_order_id"]].append(row)
    for row in read(data, "machine_logs.csv"):
        machines[row["work_order_id"]].append(row)
    for row in read(data, "overhead_actuals.csv"):
        overhead[row["work_order_id"]].append(row)
    out = []
    raw_factors: dict[str, Decimal] = defaultdict(Decimal)
    findings = []
    for order in orders:
        wo = order["work_order_id"]
        std = select_standard(standards, order)
        good = d(order["actual_good_qty"])
        planned = d(order["planned_good_qty"])
        material_rows = materials[wo]
        labor_rows = labor[wo]
        machine_rows = machines[wo]
        overhead_rows = overhead[wo]
        material_qty = sum((d(x["qty"]) for x in material_rows), Decimal())
        material_actual = sum(
            (d(x["qty"]) * d(x["foreign_unit_price"]) * d(x["fx_rate_inr"]) for x in material_rows),
            Decimal(),
        )
        std_foreign = d(std["standard_foreign_price"])
        budget_fx = d(std["budget_fx_inr"])
        std_mat_price = std_foreign * budget_fx
        purchase = sum(
            (
                d(x["qty"]) * (d(x["foreign_unit_price"]) - std_foreign) * d(x["fx_rate_inr"])
                for x in material_rows
            ),
            Decimal(),
        )
        fx = sum(
            (d(x["qty"]) * std_foreign * (d(x["fx_rate_inr"]) - budget_fx) for x in material_rows),
            Decimal(),
        )
        material_yield = std_mat_price * (material_qty - d(std["material_qty_per_good"]) * good)
        labor_hours = sum((d(x["hours"]) for x in labor_rows), Decimal())
        labor_actual = sum((d(x["hours"]) * d(x["actual_rate_inr"]) for x in labor_rows), Decimal())
        std_labor_rate = d(std["standard_labor_rate_inr"])
        labor_rate = sum(
            (d(x["hours"]) * (d(x["actual_rate_inr"]) - std_labor_rate) for x in labor_rows),
            Decimal(),
        )
        labor_eff = std_labor_rate * (labor_hours - d(std["standard_labor_hours_per_good"]) * good)
        machine_hours = sum((d(x["hours"]) for x in machine_rows), Decimal())
        machine_actual = sum(
            (d(x["hours"]) * d(x["actual_rate_inr"]) for x in machine_rows), Decimal()
        )
        std_machine_rate = d(std["standard_machine_rate_inr"])
        machine_rate = sum(
            (d(x["hours"]) * (d(x["actual_rate_inr"]) - std_machine_rate) for x in machine_rows),
            Decimal(),
        )
        machine_util = std_machine_rate * (
            machine_hours - d(std["standard_machine_hours_per_good"]) * good
        )
        actual_oh = sum((d(x["actual_overhead_inr"]) for x in overhead_rows), Decimal())
        std_oh_rate = d(std["standard_overhead_rate_inr"])
        oh_spend = actual_oh - std_oh_rate * machine_hours
        oh_absorb = std_oh_rate * (machine_hours - d(std["standard_machine_hours_per_good"]) * good)
        standard_unit = (
            std_mat_price * d(std["material_qty_per_good"])
            + std_labor_rate * d(std["standard_labor_hours_per_good"])
            + std_machine_rate * d(std["standard_machine_hours_per_good"])
            + std_oh_rate * d(std["standard_machine_hours_per_good"])
        )
        volume = standard_unit * (good - planned)
        factors = {
            "purchase_price": purchase,
            "fx": fx,
            "material_yield_scrap": material_yield,
            "labor_rate": labor_rate,
            "labor_efficiency": labor_eff,
            "machine_rate": machine_rate,
            "machine_utilization": machine_util,
            "overhead_spending": oh_spend,
            "overhead_absorption": oh_absorb,
            "volume": volume,
        }
        actual = material_actual + labor_actual + machine_actual + actual_oh
        planned_cost = standard_unit * planned
        total = actual - planned_cost
        factor_sum = sum(factors.values(), Decimal())
        diff = total - factor_sum
        row = {
            "work_order_id": wo,
            "period": order["period"],
            "actual_cost_inr": m(actual),
            "planned_standard_cost_inr": m(planned_cost),
            "total_variance_inr": m(total),
            "purchase_price_variance_inr": m(purchase),
            "fx_variance_inr": m(fx),
            "material_yield_scrap_variance_inr": m(material_yield),
            "labor_rate_variance_inr": m(labor_rate),
            "labor_efficiency_variance_inr": m(labor_eff),
            "machine_rate_variance_inr": m(machine_rate),
            "machine_utilization_variance_inr": m(machine_util),
            "overhead_spending_variance_inr": m(oh_spend),
            "overhead_absorption_variance_inr": m(oh_absorb),
            "volume_variance_inr": m(volume),
            "reconciliation_difference_inr": m(diff),
        }
        out.append(row)
        for name, value in factors.items():
            raw_factors[name] += value
            if abs(value) >= Decimal("1000"):
                evidence = {
                    "purchase_price": [x["material_txn_id"] for x in material_rows],
                    "fx": [x["material_txn_id"] for x in material_rows],
                    "material_yield_scrap": [x["material_txn_id"] for x in material_rows],
                    "labor_rate": [x["labor_entry_id"] for x in labor_rows],
                    "labor_efficiency": [x["labor_entry_id"] for x in labor_rows],
                    "machine_rate": [x["machine_log_id"] for x in machine_rows],
                    "machine_utilization": [x["machine_log_id"] for x in machine_rows],
                    "overhead_spending": [x["overhead_entry_id"] for x in overhead_rows],
                    "overhead_absorption": [x["overhead_entry_id"] for x in overhead_rows],
                    "volume": [wo],
                }[name]
                findings.append(
                    {
                        "work_order_id": wo,
                        "factor": name,
                        "variance_inr": m(value),
                        "evidence_ids": evidence,
                    }
                )
    summary_unranked = [
        {
            "factor": name,
            "variance_inr": m(raw_factors[name]),
            "absolute_variance_inr": m(abs(raw_factors[name])),
        }
        for name in FACTORS
    ]
    summary_unranked.sort(key=lambda x: (-d(x["absolute_variance_inr"]), x["factor"]))
    summary = [
        {**row, "materiality_rank": str(index + 1)} for index, row in enumerate(summary_unranked)
    ]
    actual_total = sum((d(row["actual_cost_inr"]) for row in out), Decimal())
    planned_total = sum((d(row["planned_standard_cost_inr"]) for row in out), Decimal())
    variance_total = sum((d(row["total_variance_inr"]) for row in out), Decimal())
    factor_total = sum((d(row["variance_inr"]) for row in summary), Decimal())
    report = {
        "schema_version": "1.0",
        "currency": "INR",
        "rounding_policy": "Decimal ROUND_HALF_UP to 0.01 after each final factor and total",
        "order_count": len(out),
        "actual_cost_inr": m(actual_total),
        "planned_standard_cost_inr": m(planned_total),
        "total_variance_inr": m(variance_total),
        "factor_total_inr": m(factor_total),
        "reconciliation_difference_inr": m(variance_total - factor_total),
        "material_factors": [
            row["factor"] for row in summary if d(row["absolute_variance_inr"]) >= Decimal("1000")
        ],
    }
    findings.sort(key=lambda x: (x["work_order_id"], x["factor"]))
    investigation = {
        "schema_version": "1.0",
        "findings": findings,
        "accounting_policies": [
            "standards selected by inclusive work-order release date",
            "unfavorable variance is positive",
            "findings include absolute unrounded factor variance of at least INR 1000",
        ],
    }
    return {"orders": out, "summary": summary, "report": report, "investigation": investigation}


def write_outputs(value: dict[str, Any], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    mappings = [
        (
            "order_variances.csv",
            value["orders"],
            [
                "work_order_id",
                "period",
                "actual_cost_inr",
                "planned_standard_cost_inr",
                "total_variance_inr",
                "purchase_price_variance_inr",
                "fx_variance_inr",
                "material_yield_scrap_variance_inr",
                "labor_rate_variance_inr",
                "labor_efficiency_variance_inr",
                "machine_rate_variance_inr",
                "machine_utilization_variance_inr",
                "overhead_spending_variance_inr",
                "overhead_absorption_variance_inr",
                "volume_variance_inr",
                "reconciliation_difference_inr",
            ],
        ),
        (
            "factor_summary.csv",
            value["summary"],
            ["factor", "variance_inr", "absolute_variance_inr", "materiality_rank"],
        ),
    ]
    for name, rows, fields in mappings:
        with (out / name).open("w", newline="", encoding="utf-8") as h:
            w = csv.DictWriter(h, fieldnames=fields, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    (out / "variance_report.json").write_text(
        json.dumps(value["report"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "investigation_findings.json").write_text(
        json.dumps(value["investigation"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    write_outputs(compute(a.data), a.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
