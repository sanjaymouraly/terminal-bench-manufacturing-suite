#!/usr/bin/env python3
"""Reference event-sourcing recovery for the inventory task."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

QTY = Decimal("0.001")


def d(value: Any) -> Decimal:
    return Decimal(str(value))


def q(value: Decimal) -> str:
    return format(value.quantize(QTY, rounding=ROUND_HALF_UP).normalize(), "f")


def csv_rows(root: Path, name: str) -> list[dict[str, str]]:
    with (root / name).open(newline="", encoding="utf-8") as h:
        return list(csv.DictReader(h))


def jsonl_rows(root: Path, name: str) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in (root / name).read_text(encoding="utf-8").splitlines() if line
    ]


def compute(data: Path) -> dict[str, Any]:
    lots = {row["lot_id"]: row for row in csv_rows(data, "lots.csv")}
    factors = {
        (row["item_id"], row["uom"]): d(row["factor_to_base"])
        for row in csv_rows(data, "uom_conversions.csv")
    }
    raw = jsonl_rows(data, "stock_events.jsonl")
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in raw:
        by_id[event["event_id"]].append(event)
    retained: list[dict[str, Any]] = []
    dropped: list[str] = []
    quarantined: list[str] = []
    business_keys = (
        "effective_ts",
        "operation",
        "warehouse",
        "lot_id",
        "qty",
        "uom",
        "transfer_id",
        "source",
    )
    for event_id, candidates in by_id.items():
        candidates.sort(key=lambda item: item["recorded_ts"])
        first = candidates[0]
        retained.append(first)
        if len(candidates) > 1:
            first_key = tuple(first[key] for key in business_keys)
            if all(
                tuple(item[key] for key in business_keys) == first_key for item in candidates[1:]
            ):
                dropped.append(event_id)
            else:
                quarantined.append(event_id)
    for evidence in csv_rows(data, "recovery_evidence.csv"):
        retained.append(
            {
                "event_id": evidence["recovery_id"],
                "effective_ts": evidence["effective_ts"],
                "recorded_ts": evidence["effective_ts"],
                "operation": evidence["operation"],
                "warehouse": evidence["warehouse"],
                "lot_id": evidence["lot_id"],
                "qty": evidence["qty"],
                "uom": evidence["uom"],
                "transfer_id": "",
                "source": "RECOVERY_EVIDENCE",
            }
        )
    ledger: list[dict[str, str]] = []
    for event in retained:
        lot = lots[event["lot_id"]]
        item = lot["item_id"]
        qty = d(event["qty"]) * factors[(item, event["uom"])]
        ledger.append(
            {
                "event_id": event["event_id"],
                "effective_ts": event["effective_ts"],
                "operation": event["operation"],
                "warehouse": event["warehouse"],
                "lot_id": event["lot_id"],
                "qty_base": q(qty),
                "base_uom": lot["base_uom"],
                "transfer_id": event["transfer_id"],
                "provenance": "RECOVERY_EVIDENCE"
                if event["source"] == "RECOVERY_EVIDENCE"
                else "SOURCE",
                "idempotency_key": event["event_id"],
            }
        )
    ledger.sort(key=lambda item: (item["effective_ts"], item["event_id"]))
    on_hand: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    reserved: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    sent: dict[str, Decimal] = defaultdict(Decimal)
    received: dict[str, Decimal] = defaultdict(Decimal)
    for event in ledger:
        key = (event["warehouse"], event["lot_id"])
        qty = d(event["qty_base"])
        op = event["operation"]
        if op in {"RECEIPT", "ADJUSTMENT", "TRANSFER_IN"}:
            on_hand[key] += qty
        elif op in {"ISSUE", "TRANSFER_OUT"}:
            on_hand[key] -= qty
        elif op == "RESERVE":
            reserved[key] += qty
        elif op == "RELEASE":
            reserved[key] -= qty
        else:
            raise ValueError(f"Unsupported operation {op}")
        if op == "TRANSFER_OUT":
            sent[event["transfer_id"]] += qty
        if op == "TRANSFER_IN":
            received[event["transfer_id"]] += qty
    keys = sorted(set(on_hand) | set(reserved))
    balances = [
        {
            "warehouse": warehouse,
            "lot_id": lot_id,
            "item_id": lots[lot_id]["item_id"],
            "base_uom": lots[lot_id]["base_uom"],
            "on_hand_qty": q(on_hand[(warehouse, lot_id)]),
            "reserved_qty": q(reserved[(warehouse, lot_id)]),
            "available_qty": q(on_hand[(warehouse, lot_id)] - reserved[(warehouse, lot_id)]),
        }
        for warehouse, lot_id in keys
    ]
    transfers: list[dict[str, str]] = []
    for row in sorted(csv_rows(data, "transfer_orders.csv"), key=lambda item: item["transfer_id"]):
        factor = factors[(lots[row["lot_id"]]["item_id"], row["uom"])]
        expected = d(row["expected_qty"]) * factor
        out = sent[row["transfer_id"]]
        incoming = received[row["transfer_id"]]
        transit = max(out - incoming, Decimal("0"))
        status = (
            "COMPLETE"
            if out == expected and incoming == expected
            else "IN_TRANSIT"
            if out > incoming
            else "EXCEPTION"
        )
        transfers.append(
            {
                "transfer_id": row["transfer_id"],
                "lot_id": row["lot_id"],
                "dispatched_qty_base": q(out),
                "received_qty_base": q(incoming),
                "in_transit_qty_base": q(transit),
                "status": status,
            }
        )
    snapshot_findings = [
        {
            "snapshot_id": row["snapshot_id"],
            "checksum_status": row["checksum_status"],
            "action": "NOT_USED_AS_REPLAY_AUTHORITY",
        }
        for row in sorted(
            csv_rows(data, "stock_snapshots.csv"), key=lambda item: item["snapshot_id"]
        )
        if row["checksum_status"] != "OK"
    ]
    expected_reserved: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for reservation in csv_rows(data, "reservations.csv"):
        if reservation["status"] != "ACTIVE":
            continue
        lot = lots[reservation["lot_id"]]
        expected_reserved[(reservation["warehouse"], reservation["lot_id"])] += (
            d(reservation["reserved_qty"]) * factors[(lot["item_id"], reservation["uom"])]
        )
    reservation_matches = all(
        reserved[key] == value for key, value in expected_reserved.items()
    ) and all(key in expected_reserved or value == 0 for key, value in reserved.items())
    digest_source = "\n".join(
        "|".join(
            event[key]
            for key in (
                "event_id",
                "effective_ts",
                "operation",
                "warehouse",
                "lot_id",
                "qty_base",
                "provenance",
            )
        )
        for event in ledger
    )
    audit = {
        "schema_version": "1.0",
        "ledger_digest": hashlib.sha256(digest_source.encode()).hexdigest(),
        "accepted_event_ids": [event["event_id"] for event in ledger],
        "dropped_exact_duplicate_ids": sorted(dropped),
        "quarantined_conflict_ids": sorted(quarantined),
        "synthetic_recovery_event_ids": sorted(
            event["event_id"] for event in ledger if event["provenance"] == "RECOVERY_EVIDENCE"
        ),
        "snapshot_findings": snapshot_findings,
        "invariants": {
            "nonnegative_on_hand": all(d(row["on_hand_qty"]) >= 0 for row in balances),
            "nonnegative_reserved": all(d(row["reserved_qty"]) >= 0 for row in balances),
            "unique_idempotency_keys": len({row["idempotency_key"] for row in ledger})
            == len(ledger),
            "active_reservation_evidence_matches": reservation_matches,
        },
    }
    return {"ledger": ledger, "balances": balances, "transfers": transfers, "audit": audit}


def write_outputs(value: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "recovered_ledger.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in value["ledger"]
        ),
        encoding="utf-8",
    )
    for filename, rows, fields in [
        (
            "inventory_balances.csv",
            value["balances"],
            [
                "warehouse",
                "lot_id",
                "item_id",
                "base_uom",
                "on_hand_qty",
                "reserved_qty",
                "available_qty",
            ],
        ),
        (
            "transfer_reconciliation.csv",
            value["transfers"],
            [
                "transfer_id",
                "lot_id",
                "dispatched_qty_base",
                "received_qty_base",
                "in_transit_qty_base",
                "status",
            ],
        ),
    ]:
        with (output / filename).open("w", newline="", encoding="utf-8") as h:
            writer = csv.DictWriter(h, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (output / "recovery_audit.json").write_text(
        json.dumps(value["audit"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_outputs(compute(args.data), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
