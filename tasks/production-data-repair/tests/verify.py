#!/usr/bin/env python3
"""Private semantic verifier for MES/ERP/PLC/QMS production repair.

The verifier independently replays the raw source evidence, then reviews the
declared history, genealogy, accounting, dispositions, and repair audit. No audit
narrative is trusted as proof of the underlying calculation.
"""

from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from reference import compute

GENEALOGY_FIELDS = [
    "output_batch_id",
    "work_order_id",
    "input_lot_id",
    "consumed_qty",
    "consumed_uom",
    "good_output_qty",
    "scrap_qty",
    "traceability_status",
]
ACCOUNTING_FIELDS = [
    "work_order_id",
    "good_qty",
    "scrap_qty",
    "total_accounted_qty",
    "input_qty",
    "input_uom",
    "yield_pct",
    "status",
]
QUALITY_FIELDS = [
    "batch_id",
    "inspection_id",
    "result",
    "disposition",
    "utc_ts",
    "repair_ref",
]
HISTORY_FIELDS = {
    "event_id",
    "utc_ts",
    "authority_rank",
    "event_type",
    "machine_id",
    "work_order_id",
    "batch_id",
    "lot_id",
    "qty",
    "uom",
    "provenance",
    "repair_ref",
}


def read_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != fields:
            raise ValueError(f"{path.name} header mismatch: {reader.fieldnames!r}")
        return list(reader)


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
            "reconstructed_history.jsonl",
            "batch_genealogy.csv",
            "production_accounting.csv",
            "quality_dispositions.csv",
            "repair_audit.json",
        ]
        missing = [name for name in names if not (output / name).is_file()]
        record("declared_artifacts_exist", not missing, "Missing artifacts: " + ", ".join(missing))
        if missing:
            raise ValueError("missing artifacts")

        history = [
            json.loads(line)
            for line in (output / "reconstructed_history.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        ]
        genealogy = read_csv(output / "batch_genealogy.csv", GENEALOGY_FIELDS)
        accounting = read_csv(output / "production_accounting.csv", ACCOUNTING_FIELDS)
        quality = read_csv(output / "quality_dispositions.csv", QUALITY_FIELDS)
        audit = json.loads((output / "repair_audit.json").read_text(encoding="utf-8"))

        record(
            "history_shape",
            all(isinstance(row, dict) and set(row) >= HISTORY_FIELDS for row in history),
            "A history row is missing required fields.",
        )
        record(
            "history_reconstruction",
            history == expected["history"],
            "Reconstructed history differs from the private source reconciliation.",
        )
        record(
            "history_sorted",
            [
                (row.get("utc_ts", ""), row.get("authority_rank", ""), row.get("event_id", ""))
                for row in history
            ]
            == sorted(
                (row.get("utc_ts", ""), row.get("authority_rank", ""), row.get("event_id", ""))
                for row in history
            ),
            "History is not sorted by utc_ts,authority_rank,event_id.",
        )
        record(
            "genealogy_matches",
            genealogy == expected["genealogy"],
            "Batch genealogy differs from corrected material consumption.",
        )
        record(
            "production_accounting_matches",
            accounting == expected["accounting"],
            "Production accounting differs from ERP-authoritative quantities.",
        )
        record(
            "quality_dispositions_match",
            quality == expected["quality"],
            "Quality dispositions differ from corrected inspection evidence.",
        )

        conserved = True
        for row in accounting:
            try:
                if Decimal(row["good_qty"]) + Decimal(row["scrap_qty"]) != Decimal(
                    row["total_accounted_qty"]
                ):
                    conserved = False
            except (ArithmeticError, ValueError):
                conserved = False
        record("output_scrap_conservation", conserved, "good + scrap != total accounted quantity.")
        holds = all(row["disposition"] == "HOLD" for row in quality if row["result"] == "FAIL")
        record("failed_batch_hold", holds, "A failed inspection was not held.")

        audit_keys = {
            "schema_version",
            "clock_normalization",
            "dropped_duplicate_ids",
            "quarantined_conflict_ids",
            "state_conflicts_resolved",
            "material_reallocations",
            "batch_link_repairs",
            "invariants",
        }
        audit_ok = audit_keys <= set(audit)
        for field in (
            "clock_normalization",
            "dropped_duplicate_ids",
            "quarantined_conflict_ids",
            "state_conflicts_resolved",
            "material_reallocations",
            "batch_link_repairs",
        ):
            if audit.get(field) != expected["audit"][field]:
                audit_ok = False
                diagnostics.append(f"repair_audit.{field} differs from evidence.")
        invariants = audit.get("invariants")
        if not isinstance(invariants, dict):
            audit_ok = False
            diagnostics.append("invariants must be an object.")
        else:
            for key, value in expected["audit"]["invariants"].items():
                if invariants.get(key) is not value:
                    audit_ok = False
                    diagnostics.append(f"invariants.{key} is not the observed boolean value.")
        record("repair_audit_evidence", audit_ok, "Repair audit evidence is incomplete.")
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
