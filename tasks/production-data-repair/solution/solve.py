#!/usr/bin/env python3
"""Reference multi-system production and traceability repair.

Every repair is derived from explicit evidence columns. No scenario identifiers are
hardcoded, so the same implementation applies to regenerated and scaled fixtures.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

Q = Decimal("0.001")


def d(value: Any) -> Decimal:
    return Decimal(str(value))


def q(value: Decimal) -> str:
    return format(value.quantize(Q, rounding=ROUND_HALF_UP).normalize(), "f")


def csvrows(root: Path, name: str) -> list[dict[str, str]]:
    with (root / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def jsonl(root: Path, name: str) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in (root / name).read_text(encoding="utf-8").splitlines() if line
    ]


def utc_from_local(value: str, offset: Decimal) -> str:
    moment = datetime.fromisoformat(value).replace(tzinfo=UTC) - timedelta(seconds=float(offset))
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_from_erp(value: str) -> str:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def business_signature(event: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(
        event.get(key, "")
        for key in (
            "source",
            "local_ts",
            "machine_id",
            "work_order_id",
            "event_type",
            "batch_id",
            "lot_id",
            "qty",
            "uom",
        )
    )


def compute(data: Path) -> dict[str, Any]:
    offsets = {
        row["source"]: (d(row["offset_seconds"]), row["authority_rank"])
        for row in csvrows(data, "clock_offsets.csv")
    }
    orders = {row["work_order_id"]: row for row in csvrows(data, "work_orders.csv")}
    raw_events = jsonl(data, "mes_events.jsonl")
    allocation = {row["event_id"]: row for row in csvrows(data, "allocation_evidence.csv")}
    links = {row["inspection_id"]: row for row in csvrows(data, "batch_link_evidence.csv")}
    maintenance = csvrows(data, "maintenance_events.csv")

    # 1. Resolve exact and conflicting duplicate IDs deterministically before using
    # any event as evidence. recorded_ts is the MES receipt clock, not the event clock.
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in raw_events:
        grouped[str(event["event_id"])].append(event)
    retained_events: list[dict[str, Any]] = []
    dropped: set[str] = set()
    quarantined: set[str] = set()
    for event_id, candidates in grouped.items():
        ordered = sorted(
            candidates,
            key=lambda row: (
                str(row.get("recorded_ts") or row.get("local_ts") or ""),
                str(row.get("local_ts") or ""),
            ),
        )
        retained = ordered[0]
        retained_events.append(retained)
        if len(candidates) > 1:
            first = business_signature(retained)
            if all(business_signature(item) == first for item in ordered[1:]):
                dropped.add(event_id)
            else:
                quarantined.add(event_id)

    # 2. Batch travellers come from retained non-material events. A misallocated
    # material event must never define a production order.
    batch_to_wo: dict[str, str] = {}
    for event in retained_events:
        if event["event_type"] != "MATERIAL_CONSUMED":
            batch_to_wo[str(event["batch_id"])] = str(event["work_order_id"])

    # 3. A maintenance record explicitly identifies stale and replacement PLC signals.
    stale = {
        row["stale_event_id"]: row for row in maintenance if row.get("stale_event_id", "").strip()
    }
    history: list[dict[str, Any]] = []
    state_conflicts: list[dict[str, str]] = []
    plc_events = {str(row["event_id"]): row for row in jsonl(data, "plc_logs.jsonl")}
    for event in retained_events:
        work_order = str(event["work_order_id"])
        repair_ref = ""
        if str(event["event_id"]) in allocation:
            work_order = allocation[str(event["event_id"])]["correct_work_order_id"]
            repair_ref = allocation[str(event["event_id"])]["evidence_id"]
        history.append(
            {
                "event_id": str(event["event_id"]),
                "utc_ts": utc_from_local(str(event["local_ts"]), offsets["MES"][0]),
                "authority_rank": offsets["MES"][1],
                "event_type": str(event["event_type"]),
                "machine_id": str(event["machine_id"]),
                "work_order_id": work_order,
                "batch_id": str(event["batch_id"]),
                "lot_id": str(event["lot_id"]),
                "qty": q(d(event["qty"])),
                "uom": str(event["uom"]),
                "provenance": "MES",
                "repair_ref": repair_ref,
            }
        )

    for event_id, event in sorted(plc_events.items()):
        if event_id in stale:
            resolution = stale[event_id]
            replacement = str(resolution.get("replacement_event_id", "")).strip()
            if replacement and replacement not in plc_events:
                raise ValueError(f"Maintenance record names missing replacement {replacement}")
            state_conflicts.append(
                {
                    "machine_id": str(event["machine_id"]),
                    "discarded_event_id": event_id,
                    "kept_event_id": replacement,
                    "maintenance_id": str(resolution["maintenance_id"]),
                }
            )
            continue
        work_order = batch_to_wo.get(str(event["batch_id"]), "")
        if not work_order:
            raise ValueError(f"PLC event {event_id} has no retained batch traveller")
        history.append(
            {
                "event_id": event_id,
                "utc_ts": utc_from_local(str(event["local_ts"]), offsets["PLC"][0]),
                "authority_rank": offsets["PLC"][1],
                "event_type": "PLC_" + str(event["state"]),
                "machine_id": str(event["machine_id"]),
                "work_order_id": work_order,
                "batch_id": str(event["batch_id"]),
                "lot_id": "",
                "qty": q(d(event["counter_good"]) + d(event["counter_scrap"])),
                "uom": "EA",
                "provenance": "PLC",
                "repair_ref": "",
            }
        )

    erp_rows = csvrows(data, "erp_movements.csv")
    for row in erp_rows:
        order = orders.get(row["work_order_id"])
        if order is None:
            raise ValueError(f"ERP movement {row['movement_id']} names unknown work order")
        history.append(
            {
                "event_id": row["movement_id"],
                "utc_ts": utc_from_erp(row["utc_ts"]),
                "authority_rank": offsets["ERP"][1],
                "event_type": row["movement_type"],
                "machine_id": order["machine_id"],
                "work_order_id": row["work_order_id"],
                "batch_id": row["batch_id"],
                "lot_id": row["lot_id"],
                "qty": q(d(row["qty"])),
                "uom": row["uom"],
                "provenance": "ERP",
                "repair_ref": "",
            }
        )
    for row in maintenance:
        history.append(
            {
                "event_id": row["maintenance_id"],
                "utc_ts": utc_from_erp(row["utc_ts"]),
                "authority_rank": "1",
                "event_type": "MAINTENANCE_" + row["state"],
                "machine_id": row["machine_id"],
                "work_order_id": "",
                "batch_id": "",
                "lot_id": "",
                "qty": "0",
                "uom": "EA",
                "provenance": "MAINTENANCE",
                "repair_ref": "",
            }
        )

    quality: list[dict[str, str]] = []
    for inspection in csvrows(data, "quality_inspections.csv"):
        batch = inspection["recorded_batch_id"]
        repair_ref = ""
        if inspection["inspection_id"] in links:
            batch = links[inspection["inspection_id"]]["correct_batch_id"]
            repair_ref = links[inspection["inspection_id"]]["evidence_id"]
        if batch not in batch_to_wo:
            raise ValueError(f"Inspection {inspection['inspection_id']} has unknown batch {batch}")
        utc = utc_from_local(inspection["local_ts"], offsets["QMS"][0])
        quality.append(
            {
                "batch_id": batch,
                "inspection_id": inspection["inspection_id"],
                "result": inspection["result"],
                "disposition": inspection["disposition"],
                "utc_ts": utc,
                "repair_ref": repair_ref,
            }
        )
        history.append(
            {
                "event_id": inspection["inspection_id"],
                "utc_ts": utc,
                "authority_rank": offsets["QMS"][1],
                "event_type": "QUALITY_" + inspection["disposition"],
                "machine_id": "",
                "work_order_id": batch_to_wo[batch],
                "batch_id": batch,
                "lot_id": "",
                "qty": "0",
                "uom": "EA",
                "provenance": "QMS",
                "repair_ref": repair_ref,
            }
        )

    # 4. Recover only accounting outcomes absent from retained MES evidence. ERP is
    # authoritative for quantities; the synthetic event remains ERP-provenanced.
    mes_types = {
        (row["work_order_id"], row["event_type"]) for row in history if row["provenance"] == "MES"
    }
    for row in erp_rows:
        desired = "COMPLETE" if row["movement_type"] == "OUTPUT_RECEIPT" else "SCRAP"
        if (row["work_order_id"], desired) in mes_types:
            continue
        history.append(
            {
                "event_id": "RECOVERED-" + desired + "-" + row["movement_id"],
                "utc_ts": utc_from_erp(row["utc_ts"]),
                "authority_rank": "3",
                "event_type": "RECOVERED_" + desired,
                "machine_id": orders[row["work_order_id"]]["machine_id"],
                "work_order_id": row["work_order_id"],
                "batch_id": row["batch_id"],
                "lot_id": "",
                "qty": q(d(row["qty"])),
                "uom": row["uom"],
                "provenance": "ERP",
                "repair_ref": row["movement_id"],
            }
        )

    history.sort(key=lambda row: (row["utc_ts"], int(row["authority_rank"]), row["event_id"]))
    if len({row["event_id"] for row in history}) != len(history):
        raise ValueError("Reconstructed history contains duplicate event IDs")

    output_by_wo: defaultdict[str, Decimal] = defaultdict(Decimal)
    scrap_by_wo: defaultdict[str, Decimal] = defaultdict(Decimal)
    for row in erp_rows:
        target = output_by_wo if row["movement_type"] == "OUTPUT_RECEIPT" else scrap_by_wo
        target[row["work_order_id"]] += d(row["qty"])

    consumption: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in history:
        if event["event_type"] == "MATERIAL_CONSUMED":
            consumption[event["work_order_id"]].append(event)

    # Latest inspection by UTC timestamp governs the batch disposition; a HOLD wins ties.
    disposition_by_batch: dict[str, str] = {}
    for row in sorted(quality, key=lambda item: (item["utc_ts"], item["inspection_id"])):
        disposition_by_batch[row["batch_id"]] = row["disposition"]

    batch_by_wo: dict[str, str] = {}
    for event in history:
        if event["provenance"] == "MES" and event["batch_id"]:
            batch_by_wo.setdefault(event["work_order_id"], event["batch_id"])
    for work_order, _order in orders.items():
        if work_order not in batch_by_wo:
            batch_by_wo[work_order] = next(
                (
                    row["batch_id"]
                    for row in erp_rows
                    if row["work_order_id"] == work_order and row["batch_id"]
                ),
                "",
            )

    genealogy: list[dict[str, str]] = []
    accounting: list[dict[str, str]] = []
    for work_order in sorted(orders):
        batch = batch_by_wo[work_order]
        good = output_by_wo[work_order]
        scrap = scrap_by_wo[work_order]
        inputs = consumption[work_order]
        input_qty = sum((d(row["qty"]) for row in inputs), Decimal())
        uoms = {row["uom"] for row in inputs}
        if len(uoms) > 1:
            raise ValueError(f"Mixed input UOMs for {work_order}: {sorted(uoms)}")
        input_uom = next(iter(uoms), "")
        disposition = disposition_by_batch.get(batch, "HOLD")
        for item in sorted(inputs, key=lambda row: (row["lot_id"], row["event_id"])):
            genealogy.append(
                {
                    "output_batch_id": batch,
                    "work_order_id": work_order,
                    "input_lot_id": item["lot_id"],
                    "consumed_qty": item["qty"],
                    "consumed_uom": item["uom"],
                    "good_output_qty": q(good),
                    "scrap_qty": q(scrap),
                    "traceability_status": disposition,
                }
            )
        accounting.append(
            {
                "work_order_id": work_order,
                "good_qty": q(good),
                "scrap_qty": q(scrap),
                "total_accounted_qty": q(good + scrap),
                "input_qty": q(input_qty),
                "input_uom": input_uom,
                "yield_pct": q((good / input_qty * Decimal("100")) if input_qty else Decimal("0")),
                "status": disposition,
            }
        )

    genealogy.sort(key=lambda row: (row["output_batch_id"], row["input_lot_id"]))
    quality.sort(key=lambda row: (row["batch_id"], row["inspection_id"]))
    audit = {
        "schema_version": "1.0",
        "clock_normalization": [
            {"source": source, "offset_seconds": q(offset), "authority_rank": rank}
            for source, (offset, rank) in sorted(offsets.items())
        ],
        "dropped_duplicate_ids": sorted(dropped),
        "quarantined_conflict_ids": sorted(quarantined),
        "state_conflicts_resolved": sorted(
            state_conflicts, key=lambda row: (row["discarded_event_id"], row["machine_id"])
        ),
        "material_reallocations": [
            {
                "event_id": event_id,
                "from_work_order_id": next(
                    str(item["work_order_id"])
                    for item in retained_events
                    if str(item["event_id"]) == event_id
                ),
                "to_work_order_id": correction["correct_work_order_id"],
                "repair_ref": correction["evidence_id"],
            }
            for event_id, correction in sorted(allocation.items())
        ],
        "batch_link_repairs": [
            {
                "inspection_id": inspection_id,
                "from_batch_id": next(
                    row["recorded_batch_id"]
                    for row in csvrows(data, "quality_inspections.csv")
                    if row["inspection_id"] == inspection_id
                ),
                "to_batch_id": correction["correct_batch_id"],
                "repair_ref": correction["evidence_id"],
            }
            for inspection_id, correction in sorted(links.items())
        ],
        "invariants": {
            "accounting_conserved": all(
                d(row["good_qty"]) + d(row["scrap_qty"]) == d(row["total_accounted_qty"])
                for row in accounting
            ),
            "all_consumption_routed": all(
                event["work_order_id"] in orders
                for events in consumption.values()
                for event in events
            ),
            "failed_holds_preserved": all(
                row["disposition"] == "HOLD" for row in quality if row["result"] == "FAIL"
            ),
            "unique_history_event_ids": len({row["event_id"] for row in history}) == len(history),
        },
    }
    return {
        "history": history,
        "genealogy": genealogy,
        "accounting": accounting,
        "quality": quality,
        "audit": audit,
    }


def write_outputs(value: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "reconstructed_history.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in value["history"]
        ),
        encoding="utf-8",
    )
    for name, rows, fields in [
        (
            "batch_genealogy.csv",
            value["genealogy"],
            [
                "output_batch_id",
                "work_order_id",
                "input_lot_id",
                "consumed_qty",
                "consumed_uom",
                "good_output_qty",
                "scrap_qty",
                "traceability_status",
            ],
        ),
        (
            "production_accounting.csv",
            value["accounting"],
            [
                "work_order_id",
                "good_qty",
                "scrap_qty",
                "total_accounted_qty",
                "input_qty",
                "input_uom",
                "yield_pct",
                "status",
            ],
        ),
        (
            "quality_dispositions.csv",
            value["quality"],
            ["batch_id", "inspection_id", "result", "disposition", "utc_ts", "repair_ref"],
        ),
    ]:
        with (output / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (output / "repair_audit.json").write_text(
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
