#!/usr/bin/env python3
"""Private semantic verifier for inventory corruption recovery.

The raw event log is replayed privately. The verifier checks the declared ledger,
balances, transfers and audit evidence, including digest and idempotency invariants.
"""

from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from reference import compute

BALANCE_FIELDS = [
    "warehouse",
    "lot_id",
    "item_id",
    "base_uom",
    "on_hand_qty",
    "reserved_qty",
    "available_qty",
]
TRANSFER_FIELDS = [
    "transfer_id",
    "lot_id",
    "dispatched_qty_base",
    "received_qty_base",
    "in_transit_qty_base",
    "status",
]
LEDGER_FIELDS = {
    "event_id",
    "effective_ts",
    "operation",
    "warehouse",
    "lot_id",
    "qty_base",
    "base_uom",
    "transfer_id",
    "provenance",
    "idempotency_key",
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
            "recovered_ledger.jsonl",
            "inventory_balances.csv",
            "transfer_reconciliation.csv",
            "recovery_audit.json",
        ]
        missing = [name for name in names if not (output / name).is_file()]
        record("declared_artifacts_exist", not missing, "Missing artifacts: " + ", ".join(missing))
        if missing:
            raise ValueError("missing artifacts")

        ledger = [
            json.loads(line)
            for line in (output / "recovered_ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        balances = read_csv(output / "inventory_balances.csv", BALANCE_FIELDS)
        transfers = read_csv(output / "transfer_reconciliation.csv", TRANSFER_FIELDS)
        audit = json.loads((output / "recovery_audit.json").read_text(encoding="utf-8"))

        shape_ok = all(isinstance(row, dict) and set(row) >= LEDGER_FIELDS for row in ledger)
        record("ledger_shape", shape_ok, "A ledger row is missing required fields.")
        ledger_ok = ledger == expected["ledger"]
        record(
            "ledger_replay_matches",
            ledger_ok,
            "Recovered ledger differs from the private deterministic replay.",
        )
        record(
            "ledger_sorted",
            [(row.get("effective_ts", ""), row.get("event_id", "")) for row in ledger]
            == sorted((row.get("effective_ts", ""), row.get("event_id", "")) for row in ledger),
            "Ledger is not sorted by effective_ts,event_id.",
        )
        record(
            "ledger_idempotent",
            len({row.get("idempotency_key") for row in ledger}) == len(ledger),
            "Ledger idempotency keys are not unique.",
        )

        record(
            "balances_match_replay",
            balances == expected["balances"],
            "Inventory balances differ from replay.",
        )
        available_ok = True
        nonnegative_ok = True
        for row in balances:
            try:
                on_hand = Decimal(row["on_hand_qty"])
                reserved = Decimal(row["reserved_qty"])
                available = Decimal(row["available_qty"])
            except (ArithmeticError, ValueError):
                available_ok = False
                continue
            if available != on_hand - reserved:
                available_ok = False
            if min(on_hand, reserved, available) < 0:
                nonnegative_ok = False
        record("available_identity", available_ok, "available_qty != on_hand_qty - reserved_qty.")
        record("nonnegative_inventory", nonnegative_ok, "A balance is negative.")

        record(
            "transfer_reconciliation_matches",
            transfers == expected["transfers"],
            "Transfer reconciliation differs from replay.",
        )

        audit_keys = {
            "schema_version",
            "ledger_digest",
            "accepted_event_ids",
            "dropped_exact_duplicate_ids",
            "quarantined_conflict_ids",
            "synthetic_recovery_event_ids",
            "snapshot_findings",
            "invariants",
        }
        audit_ok = audit_keys <= set(audit)
        for field in (
            "ledger_digest",
            "accepted_event_ids",
            "dropped_exact_duplicate_ids",
            "quarantined_conflict_ids",
            "synthetic_recovery_event_ids",
        ):
            if audit.get(field) != expected["audit"][field]:
                audit_ok = False
                diagnostics.append(f"recovery_audit.{field} differs from replay evidence.")
        if not isinstance(audit.get("snapshot_findings"), list):
            audit_ok = False
            diagnostics.append("snapshot_findings must be a list.")
        else:
            actual_snapshots = {
                row.get("snapshot_id"): row
                for row in audit["snapshot_findings"]
                if isinstance(row, dict)
            }
            expected_snapshots = {
                row["snapshot_id"]: row for row in expected["audit"]["snapshot_findings"]
            }
            if set(actual_snapshots) != set(expected_snapshots):
                audit_ok = False
                diagnostics.append("Snapshot findings must cover every stale/corrupt snapshot.")
            for snapshot_id, expected_row in expected_snapshots.items():
                snapshot_row = actual_snapshots.get(snapshot_id)
                if not isinstance(snapshot_row, dict):
                    continue
                if snapshot_row.get("checksum_status") != expected_row["checksum_status"]:
                    audit_ok = False
                    diagnostics.append(f"Snapshot {snapshot_id} checksum_status differs.")
                if not str(snapshot_row.get("action", "")).strip():
                    audit_ok = False
                    diagnostics.append(f"Snapshot {snapshot_id} has no documented action.")
        invariants = audit.get("invariants")
        if not isinstance(invariants, dict):
            audit_ok = False
            diagnostics.append("invariants must be an object.")
        else:
            for key, value in expected["audit"]["invariants"].items():
                if invariants.get(key) is not value:
                    audit_ok = False
                    diagnostics.append(f"invariants.{key} is not the observed boolean value.")
        record("audit_evidence", audit_ok, "Audit evidence is incomplete or inconsistent.")
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
