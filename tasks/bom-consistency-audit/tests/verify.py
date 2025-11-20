#!/usr/bin/env python3
"""Private semantic verifier for time-effective BOM repair.

The verifier recomputes the repaired timeline, substitute slices, cycle findings and
requirement explosion privately. Free-text evidence is required to be non-empty but is
not compared with hidden prose.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from reference import compute

BOM_LINE_FIELDS = {
    "assembly_id",
    "revision",
    "line_no",
    "source_component_id",
    "component_id",
    "qty_base",
    "base_uom",
    "effective_from",
    "effective_to",
    "repair_refs",
}
BOM_REVISION_FIELDS = {
    "assembly_id",
    "revision",
    "effective_from",
    "effective_to",
    "status",
    "configuration",
    "repair_refs",
}
REQUIREMENT_FIELDS = [
    "production_order_id",
    "assembly_id",
    "revision",
    "status",
    "component_id",
    "required_qty_base",
    "base_uom",
    "source_component_id",
]
REPAIR_FIELDS = [
    "repair_ref",
    "assembly_id",
    "revision",
    "line_no",
    "repair_type",
    "before_value",
    "after_value",
    "evidence",
]


def read_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != fields:
            raise ValueError(f"{path.name} header mismatch: {reader.fieldnames!r}")
        return list(reader)


def refs(value: str) -> set[str]:
    return {part for part in value.replace(",", ";").split(";") if part}


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
            "approved_bom.json",
            "production_requirements.csv",
            "repair_log.csv",
            "validation_report.json",
        ]
        missing = [name for name in names if not (output / name).is_file()]
        record("declared_artifacts_exist", not missing, "Missing artifacts: " + ", ".join(missing))
        if missing:
            raise ValueError("missing artifacts")

        bom = json.loads((output / "approved_bom.json").read_text(encoding="utf-8"))
        requirements = read_csv(output / "production_requirements.csv", REQUIREMENT_FIELDS)
        repairs = read_csv(output / "repair_log.csv", REPAIR_FIELDS)
        report = json.loads((output / "validation_report.json").read_text(encoding="utf-8"))

        bom_shape = (
            isinstance(bom, dict)
            and {"schema_version", "revisions", "lines"} <= set(bom)
            and all(isinstance(item, dict) for item in bom.get("revisions", []))
            and all(isinstance(item, dict) for item in bom.get("lines", []))
        )
        record("approved_bom_shape", bom_shape, "approved_bom.json has an invalid shape.")
        revision_ok = bom_shape
        actual_revisions = {
            (row.get("assembly_id"), row.get("revision")): row for row in bom.get("revisions", [])
        }
        expected_revisions = {
            (row["assembly_id"], row["revision"]): row for row in expected["bom"]["revisions"]
        }
        if set(actual_revisions) != set(expected_revisions):
            revision_ok = False
            diagnostics.append("Approved revision coverage differs from the repaired timeline.")
        for revision_key, expected_row in expected_revisions.items():
            row = actual_revisions.get(revision_key)
            if not isinstance(row, dict) or not set(row) >= BOM_REVISION_FIELDS:
                revision_ok = False
                continue
            for field in ("effective_from", "effective_to", "status", "configuration"):
                if row.get(field) != expected_row[field]:
                    revision_ok = False
                    diagnostics.append(f"Revision {revision_key}.{field} differs.")
            if refs(str(row.get("repair_refs", ""))) != refs(expected_row["repair_refs"]):
                revision_ok = False
                diagnostics.append(f"Revision {revision_key}.repair_refs differs.")
        record(
            "approved_revision_timeline", revision_ok, "Approved revision timeline is incorrect."
        )

        line_ok = bom_shape
        actual_lines = {
            (
                row.get("assembly_id"),
                row.get("revision"),
                row.get("line_no"),
                row.get("effective_from"),
                row.get("component_id"),
            ): row
            for row in bom.get("lines", [])
        }
        expected_lines = {
            (
                row["assembly_id"],
                row["revision"],
                row["line_no"],
                row["effective_from"],
                row["component_id"],
            ): row
            for row in expected["bom"]["lines"]
        }
        if set(actual_lines) != set(expected_lines):
            line_ok = False
            diagnostics.append("Approved BOM line slices differ from the repaired effectivity.")
        for line_key, expected_row in expected_lines.items():
            row = actual_lines.get(line_key)
            if not isinstance(row, dict) or not set(row) >= BOM_LINE_FIELDS:
                line_ok = False
                continue
            for field in (
                "source_component_id",
                "qty_base",
                "base_uom",
                "effective_to",
            ):
                if row.get(field) != expected_row[field]:
                    line_ok = False
                    diagnostics.append(f"BOM line {line_key}.{field} differs.")
            if refs(str(row.get("repair_refs", ""))) != refs(expected_row["repair_refs"]):
                line_ok = False
                diagnostics.append(f"BOM line {line_key}.repair_refs differs.")
        record("approved_bom_slices", line_ok, "Approved BOM line slices are incorrect.")

        record(
            "production_requirements_match",
            len(requirements) == len(expected["requirements"])
            and all(
                actual == wanted
                for actual, wanted in zip(requirements, expected["requirements"], strict=True)
            ),
            "Production requirements differ from safe explosion.",
        )
        blocked_rows = [row for row in requirements if row["status"] == "BLOCKED"]
        expected_blocked = expected["report"]["blocked_orders"]
        record(
            "blocked_orders_once",
            [row["production_order_id"] for row in blocked_rows] == sorted(expected_blocked),
            "Each blocked order must have exactly one BLOCKED requirement row.",
        )

        repair_ok = len(repairs) == len(expected["repairs"])
        for actual_row, expected_row in zip(repairs, expected["repairs"], strict=False):
            for field in REPAIR_FIELDS:
                if field == "evidence":
                    if not actual_row[field].strip():
                        repair_ok = False
                    continue
                if actual_row[field] != expected_row[field]:
                    repair_ok = False
                    diagnostics.append(
                        f"repair_log {expected_row['repair_type']} {expected_row['repair_ref']} "
                        f"field {field} differs."
                    )
        record("repair_log_complete", repair_ok, "Repair log is incomplete or incorrect.")

        report_shape = isinstance(report, dict) and {
            "schema_version",
            "findings",
            "blocked_orders",
            "cycle_findings",
            "historical_revision_checks",
        } <= set(report)
        record("validation_report_shape", report_shape, "validation_report.json is missing keys.")
        report_ok = report_shape
        if report_shape:
            if sorted(report.get("blocked_orders", [])) != sorted(expected_blocked):
                report_ok = False
                diagnostics.append("blocked_orders differs from the blocked requirement rows.")

            actual_findings: set[tuple[str, str, str, str, str]] = set()
            for item in report.get("findings", []):
                if not isinstance(item, dict) or not item.get("code"):
                    report_ok = False
                    continue
                actual_findings.add(
                    (
                        str(item.get("code", "")),
                        str(item.get("assembly_id", "")),
                        str(item.get("revision", "")),
                        str(item.get("production_order_id", "")),
                        str(item.get("repair_ref", "")),
                    )
                )
            expected_findings = {
                (
                    str(item.get("code", "")),
                    str(item.get("assembly_id", "")),
                    str(item.get("revision", "")),
                    str(item.get("production_order_id", "")),
                    str(item.get("repair_ref", "")),
                )
                for item in expected["report"]["findings"]
            }
            if actual_findings != expected_findings:
                report_ok = False
                diagnostics.append("Finding codes or identities differ from the supported defects.")

            actual_cycles = {
                (
                    str(item.get("assembly_id", "")),
                    str(item.get("revision", "")),
                    tuple(item.get("cycle_path", [])),
                    str(item.get("status", "")),
                )
                for item in report.get("cycle_findings", [])
                if isinstance(item, dict)
            }
            expected_cycles = {
                (
                    item["assembly_id"],
                    item["revision"],
                    tuple(item["cycle_path"]),
                    item["status"],
                )
                for item in expected["report"]["cycle_findings"]
            }
            if actual_cycles != expected_cycles:
                report_ok = False
                diagnostics.append("Cycle findings differ from the detected cycle set.")

            actual_history = {
                (
                    str(item.get("production_order_id", "")),
                    str(item.get("selected_revision", "")),
                    str(item.get("order_date", "")),
                    item.get("preserved"),
                )
                for item in report.get("historical_revision_checks", [])
                if isinstance(item, dict)
            }
            expected_history = {
                (
                    item["production_order_id"],
                    item["selected_revision"],
                    item["order_date"],
                    item["preserved"],
                )
                for item in expected["report"]["historical_revision_checks"]
            }
            if actual_history != expected_history:
                report_ok = False
                diagnostics.append("Historical revision checks differ from the repaired timeline.")
        record("validation_report_evidence", report_ok, "Validation report evidence is incorrect.")
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
