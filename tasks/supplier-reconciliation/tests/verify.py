#!/usr/bin/env python3
"""Private semantic verifier for supplier three-way reconciliation.

The verifier recomputes the financial result from pristine raw inputs (never from the
agent's audit narrative) and validates every field the task instruction defines. Free
text fields such as ``detail`` and ``policy`` are checked for presence, not matched
against a hidden answer.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from reference import compute

PAYABLE_FIELDS = [
    "invoice_id",
    "invoice_number",
    "canonical_supplier_id",
    "duplicate_of",
    "status",
    "gross_supported_inr",
    "credit_inr",
    "net_payable_inr",
    "unresolved_amount_inr",
    "reason_codes",
]
DISPUTE_FIELDS = [
    "invoice_id",
    "line_no",
    "reason_code",
    "disputed_qty_base",
    "disputed_amount_inr",
    "detail",
]
ALLOWED_STATUS = {"PAYABLE", "PARTIAL_DISPUTE", "DISPUTED", "CREDIT_EXHAUSTED", "DUPLICATE"}


def read_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != fields:
            raise ValueError(f"{path.name} header mismatch: {reader.fieldnames!r}")
        return list(reader)


def reason_set(value: str) -> set[str]:
    return {part for part in re.split(r"[;,|]", value) if part}


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
        required = ["payables.csv", "disputes.csv", "reconciliation.json", "audit.json"]
        missing = [name for name in required if not (output / name).is_file()]
        record("declared_artifacts_exist", not missing, "Missing artifacts: " + ", ".join(missing))
        if missing:
            raise ValueError("missing artifacts")

        payables = read_csv(output / "payables.csv", PAYABLE_FIELDS)
        disputes = read_csv(output / "disputes.csv", DISPUTE_FIELDS)
        reconciliation = json.loads((output / "reconciliation.json").read_text(encoding="utf-8"))
        audit = json.loads((output / "audit.json").read_text(encoding="utf-8"))
        expected_payables = {row["invoice_id"]: row for row in expected["payables"]}
        actual_payables = {row["invoice_id"]: row for row in payables}

        record(
            "invoice_decision_coverage",
            set(actual_payables) == set(expected_payables)
            and len(payables) == len(actual_payables),
            "Payables must contain exactly one row per invoice.",
        )
        record(
            "payables_sorted",
            [row["invoice_id"] for row in payables] == sorted(actual_payables),
            "Payables are not ordered by invoice_id.",
        )
        fields_ok = True
        for invoice_id, expected_row in expected_payables.items():
            actual_row = actual_payables.get(invoice_id)
            if actual_row is None:
                fields_ok = False
                diagnostics.append(f"Missing payable decision for {invoice_id}.")
                continue
            for field in PAYABLE_FIELDS:
                if field == "reason_codes":
                    continue
                if actual_row[field] != expected_row[field]:
                    fields_ok = False
                    diagnostics.append(
                        f"{invoice_id}.{field} expected {expected_row[field]!r}, "
                        f"got {actual_row[field]!r}."
                    )
            if reason_set(actual_row["reason_codes"]) != reason_set(expected_row["reason_codes"]):
                fields_ok = False
                diagnostics.append(f"{invoice_id}.reason_codes does not match the policy outcome.")
        record("payable_values_match_policy", fields_ok, "Payable values differ from policy.")

        status_ok = all(row["status"] in ALLOWED_STATUS for row in payables)
        record("status_vocabulary", status_ok, "Unknown payable status value.")
        balance_ok = True
        for row in payables:
            try:
                gross = Decimal(row["gross_supported_inr"])
                credit = Decimal(row["credit_inr"])
                net = Decimal(row["net_payable_inr"])
                unresolved = Decimal(row["unresolved_amount_inr"])
            except (ArithmeticError, ValueError):
                balance_ok = False
                diagnostics.append(f"{row['invoice_id']} has a non-decimal monetary value.")
                continue
            if gross < 0 or credit < 0 or net < 0 or unresolved < 0:
                balance_ok = False
                diagnostics.append(f"{row['invoice_id']} has a negative monetary value.")
            if gross - credit != net:
                balance_ok = False
                diagnostics.append(f"{row['invoice_id']} gross - credit != net.")
        record("monetary_balance", balance_ok, "Invoice monetary values do not balance.")

        expected_disputes = {
            (row["invoice_id"], row["line_no"], row["reason_code"]): row
            for row in expected["disputes"]
        }
        actual_disputes = {
            (row["invoice_id"], row["line_no"], row["reason_code"]): row for row in disputes
        }
        record(
            "dispute_coverage",
            set(actual_disputes) == set(expected_disputes)
            and len(disputes) == len(actual_disputes),
            "Dispute rows do not match the policy-required reasons.",
        )
        dispute_ok = True
        for key, expected_row in expected_disputes.items():
            actual_row = actual_disputes.get(key)
            if actual_row is None:
                dispute_ok = False
                continue
            for field in ("disputed_qty_base", "disputed_amount_inr"):
                if actual_row[field] != expected_row[field]:
                    dispute_ok = False
                    diagnostics.append(f"Dispute {key} field {field} differs.")
            if not actual_row["detail"].strip():
                dispute_ok = False
                diagnostics.append(f"Dispute {key} has an empty detail.")
        record("dispute_values_match_policy", dispute_ok, "Dispute values differ from policy.")
        record(
            "disputes_sorted",
            [(row["invoice_id"], row["line_no"], row["reason_code"]) for row in disputes]
            == sorted(actual_disputes),
            "Disputes are not ordered by invoice_id,line_no,reason_code.",
        )

        recon_fields = [
            "schema_version",
            "currency",
            "invoice_count",
            "duplicate_invoice_count",
            "gross_supported_inr",
            "credits_inr",
            "net_payable_inr",
            "unresolved_amount_inr",
            "payable_invoice_ids",
        ]
        recon_ok = all(field in reconciliation for field in recon_fields)
        for field in recon_fields:
            if field == "payable_invoice_ids":
                continue
            if reconciliation.get(field) != expected["reconciliation"][field]:
                recon_ok = False
                diagnostics.append(f"reconciliation.{field} differs from recomputation.")
        expected_ids = expected["reconciliation"]["payable_invoice_ids"]
        if reconciliation.get("payable_invoice_ids") != expected_ids:
            recon_ok = False
            diagnostics.append("reconciliation.payable_invoice_ids differs from recomputation.")
        record(
            "reconciliation_totals", recon_ok, "Reconciliation totals differ from recomputation."
        )

        audit_keys = {"schema_version", "policy", "invoice_decisions", "input_files"}
        audit_present = audit_keys <= set(audit)
        record("audit_shape", audit_present, "audit.json is missing required keys.")
        audit_ok = (
            audit_present and isinstance(audit.get("policy"), str) and bool(audit["policy"].strip())
        )
        decisions = {
            row.get("invoice_id"): row
            for row in audit.get("invoice_decisions", [])
            if isinstance(row, dict)
        }
        expected_decisions = {
            row["invoice_id"]: row for row in expected["audit"]["invoice_decisions"]
        }
        audit_ok = audit_ok and set(decisions) == set(expected_decisions)
        for invoice_id, expected_row in expected_decisions.items():
            actual_row = decisions.get(invoice_id)
            if not isinstance(actual_row, dict):
                continue
            for field in (
                "canonical_supplier_id",
                "duplicate_of",
                "receipt_supported_qty_base",
                "applied_credit_inr",
            ):
                if actual_row.get(field) != expected_row[field]:
                    audit_ok = False
                    diagnostics.append(f"audit decision {invoice_id}.{field} differs.")
        input_files = audit.get("input_files")
        if not isinstance(input_files, list) or not input_files:
            audit_ok = False
            diagnostics.append("audit.input_files must be a non-empty list.")
        elif not all(
            isinstance(name, str) and (args.private_root / name).is_file() for name in input_files
        ):
            audit_ok = False
            diagnostics.append("audit.input_files names a file that is not a raw input.")
        record(
            "audit_decision_evidence", audit_ok, "Audit decisions are incomplete or inconsistent."
        )

        payable_ids = sorted(
            row["invoice_id"] for row in payables if Decimal(row["net_payable_inr"]) > 0
        )
        record(
            "payable_ids_consistent",
            payable_ids == expected_ids,
            "Reconciliation payable_invoice_ids disagree with payables.csv.",
        )
    except Exception as exc:  # diagnostics must survive malformed agent output
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
