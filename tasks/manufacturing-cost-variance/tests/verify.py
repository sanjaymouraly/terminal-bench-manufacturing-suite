#!/usr/bin/env python3
"""Private semantic verifier for manufacturing cost variance.

Core financial fields are compared with an independent Decimal recomputation. The
investigation narrative fields have no hidden expected prose: structured finding
identity, signed variance, and evidence provenance are validated instead.
"""

from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from reference import compute

ORDER_FIELDS = [
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
]
SUMMARY_FIELDS = ["factor", "variance_inr", "absolute_variance_inr", "materiality_rank"]
MONEY_FIELDS = ORDER_FIELDS[2:]


def read_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != fields:
            raise ValueError(f"{path.name} header mismatch: {reader.fieldnames!r}")
        return list(reader)


def money(value: str) -> Decimal:
    return Decimal(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    checks: list[dict[str, Any]] = []
    diagnostics: list[str] = []

    def record(name: str, passed: bool, message: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed)})
        if not passed and message:
            diagnostics.append(message)

    try:
        expected = compute(args.private_root)
        output = args.artifact_root / "output"
        names = [
            "order_variances.csv",
            "factor_summary.csv",
            "variance_report.json",
            "investigation_findings.json",
        ]
        missing = [name for name in names if not (output / name).is_file()]
        record("declared_artifacts_exist", not missing, "Missing artifacts: " + ", ".join(missing))
        if missing:
            raise ValueError("missing artifacts")

        orders = read_csv(output / "order_variances.csv", ORDER_FIELDS)
        summary = read_csv(output / "factor_summary.csv", SUMMARY_FIELDS)
        report = json.loads((output / "variance_report.json").read_text(encoding="utf-8"))
        investigation = json.loads(
            (output / "investigation_findings.json").read_text(encoding="utf-8")
        )

        record(
            "order_coverage",
            [row["work_order_id"] for row in orders]
            == [row["work_order_id"] for row in expected["orders"]],
            "order_variances.csv must contain exactly one row per work order, ordered by ID.",
        )
        order_ok = len(orders) == len(expected["orders"])
        for actual_row, expected_row in zip(orders, expected["orders"], strict=False):
            for field in ORDER_FIELDS:
                if actual_row[field] != expected_row[field]:
                    order_ok = False
                    diagnostics.append(
                        f"{actual_row.get('work_order_id', '?')}.{field} expected "
                        f"{expected_row[field]!r}, got {actual_row[field]!r}."
                    )
        record(
            "order_variance_values", order_ok, "Order variance decomposition differs from policy."
        )

        factor_ok = len(summary) == len(expected["summary"])
        for actual_row, expected_row in zip(summary, expected["summary"], strict=False):
            for field in SUMMARY_FIELDS:
                if actual_row[field] != expected_row[field]:
                    factor_ok = False
                    diagnostics.append(
                        f"factor_summary {actual_row.get('factor', '?')}.{field} differs."
                    )
        record("factor_summary_values", factor_ok, "Factor summary or materiality ranking differs.")

        report_fields = [
            "schema_version",
            "currency",
            "order_count",
            "actual_cost_inr",
            "planned_standard_cost_inr",
            "total_variance_inr",
            "factor_total_inr",
            "reconciliation_difference_inr",
            "material_factors",
        ]
        report_ok = all(field in report for field in report_fields)
        for field in report_fields:
            if report.get(field) != expected["report"][field]:
                report_ok = False
                diagnostics.append(f"variance_report.{field} differs from recomputation.")
        if (
            not isinstance(report.get("rounding_policy"), str)
            or not report.get("rounding_policy", "").strip()
        ):
            report_ok = False
            diagnostics.append("variance_report.rounding_policy must be non-empty.")
        record("variance_report_values", report_ok, "Variance report differs from recomputation.")

        recon_ok = True
        for row in orders:
            try:
                difference = abs(money(row["reconciliation_difference_inr"]))
                component_sum = sum(
                    (
                        money(row[field])
                        for field in MONEY_FIELDS
                        if field
                        not in {
                            "actual_cost_inr",
                            "planned_standard_cost_inr",
                            "total_variance_inr",
                            "reconciliation_difference_inr",
                        }
                    ),
                    Decimal("0"),
                )
                expected_difference = money(row["total_variance_inr"]) - component_sum
            except (ArithmeticError, ValueError):
                recon_ok = False
                continue
            if difference > Decimal("0.01") or abs(difference - expected_difference) > Decimal(
                "0.01"
            ):
                recon_ok = False
                diagnostics.append(f"{row['work_order_id']} variance factors do not reconcile.")
        record("variance_reconciliation", recon_ok, "A work-order variance sum does not reconcile.")

        investigation_ok = isinstance(investigation.get("findings"), list)
        policies = investigation.get("accounting_policies")
        if (
            not isinstance(policies, list)
            or not policies
            or not all(isinstance(item, str) and item.strip() for item in policies)
        ):
            investigation_ok = False
            diagnostics.append("accounting_policies must be a non-empty string list.")

        expected_findings = {
            (row["work_order_id"], row["factor"]): row
            for row in expected["investigation"]["findings"]
        }
        actual_findings: dict[tuple[str, str], dict[str, Any]] = {}
        for item in investigation.get("findings", []):
            if not isinstance(item, dict):
                investigation_ok = False
                continue
            key = (str(item.get("work_order_id", "")), str(item.get("factor", "")))
            if key in actual_findings:
                investigation_ok = False
                diagnostics.append(f"Duplicate investigation finding {key}.")
            actual_findings[key] = item
        if set(actual_findings) != set(expected_findings):
            investigation_ok = False
            diagnostics.append(
                "Investigation findings must cover exactly the order/factor pairs at or above "
                "the materiality threshold."
            )
        for key, expected_row in expected_findings.items():
            finding_row = actual_findings.get(key)
            if finding_row is None:
                continue
            if finding_row.get("variance_inr") != expected_row["variance_inr"]:
                investigation_ok = False
                diagnostics.append(f"Finding {key} variance_inr differs.")
            evidence = finding_row.get("evidence_ids")
            if not isinstance(evidence, list) or not evidence:
                investigation_ok = False
                diagnostics.append(f"Finding {key} has no evidence_ids.")
            elif not set(map(str, evidence)) <= set(map(str, expected_row["evidence_ids"])):
                investigation_ok = False
                diagnostics.append(f"Finding {key} cites evidence outside the relevant records.")
        record("investigation_findings", investigation_ok, "Investigation findings are incomplete.")

        summary_total = sum((money(row["variance_inr"]) for row in summary), Decimal("0"))
        total_ok = abs(summary_total - money(report["factor_total_inr"])) <= Decimal("0.01")
        record(
            "factor_total_consistency", total_ok, "Factor summary does not sum to factor_total_inr."
        )
    except Exception as exc:
        diagnostics.append(f"Verifier parse/calculation error: {exc}")

    passed = bool(checks) and all(check["passed"] for check in checks)
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(
        json.dumps(
            {"reward": 1.0 if passed else 0.0, "checks": checks, "diagnostics": diagnostics},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
