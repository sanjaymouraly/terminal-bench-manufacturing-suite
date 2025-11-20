#!/usr/bin/env python3
"""Reference time-effective BOM repair and safe requirement explosion.

The implementation deliberately separates four concerns so each can be verified:
temporal revision repair, substitute effectivity, cycle-safe explosion, and audit
reporting. No scenario identifiers are hardcoded; every result is derived from the
immutable CSV inputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

Q = Decimal("0.001")


def d(value: Any) -> Decimal:
    return Decimal(str(value))


def qty(value: Decimal) -> str:
    return format(value.quantize(Q, rounding=ROUND_HALF_UP).normalize(), "f")


def read(root: Path, name: str) -> list[dict[str, str]]:
    with (root / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def prev(day: str) -> str:
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def next_day(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def intersect(a_from: str, a_to: str, b_from: str, b_to: str) -> tuple[str, str] | None:
    lo = max(a_from, b_from)
    hi = min(a_to, b_to)
    return (lo, hi) if lo <= hi else None


def compute(data: Path) -> dict[str, Any]:
    revisions = read(data, "revisions.csv")
    lines = read(data, "bom_lines.csv")
    components = {row["component_id"]: row for row in read(data, "components.csv")}
    substitutions = read(data, "substitutions.csv")
    changes = read(data, "engineering_changes.csv")
    orders = read(data, "production_orders.csv")
    factors = {
        (row["component_id"], row["uom"]): d(row["factor_to_base"])
        for row in read(data, "uom_conversions.csv")
    }
    assembly_ids = {row["assembly_id"] for row in revisions}

    # 1. Repair the approved revision timeline using approved supersession ECNs.
    revision_map = {(row["assembly_id"], row["revision"]): dict(row) for row in revisions}
    repairs: list[dict[str, str]] = []
    revision_refs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ecn in sorted(changes, key=lambda row: (row["effective_date"], row["ecn_id"])):
        if ecn["approved"].lower() != "true" or ecn["action"] != "SUPERSEDE_REVISION":
            continue
        key = (ecn["assembly_id"], ecn["target_revision"])
        target = revision_map[key]
        before = target["effective_to"]
        candidate = prev(ecn["effective_date"])
        if candidate >= before:
            continue
        target["effective_to"] = candidate
        revision_refs[key].append(ecn["ecn_id"])
        repairs.append(
            {
                "repair_ref": ecn["ecn_id"],
                "assembly_id": ecn["assembly_id"],
                "revision": ecn["target_revision"],
                "line_no": "",
                "repair_type": "TRUNCATE_REVISION_EFFECTIVITY",
                "before_value": before,
                "after_value": candidate,
                "evidence": ecn["evidence"],
            }
        )

    # 2. Apply approved line-quantity ECNs. Evidence is structured: "<component> quantity is N".
    quantity_corrections: dict[tuple[str, str, str], tuple[str, str]] = {}
    for ecn in changes:
        if ecn["approved"].lower() != "true" or ecn["action"] != "CORRECT_QUANTITY":
            continue
        number = re.search(r"quantity is ([0-9]+(?:\.[0-9]+)?)", ecn["evidence"])
        component_match = re.search(r"(C-[A-Z0-9-]+) quantity", ecn["evidence"])
        if not number or not component_match:
            raise ValueError(f"Unparseable approved quantity ECN {ecn['ecn_id']}")
        matched = [
            line
            for line in lines
            if line["assembly_id"] == ecn["assembly_id"]
            and line["revision"] == ecn["target_revision"]
            and line["component_id"] == component_match.group(1)
        ]
        if len(matched) != 1:
            raise ValueError(f"Quantity ECN {ecn['ecn_id']} does not identify exactly one line")
        line = matched[0]
        quantity_corrections[(line["assembly_id"], line["revision"], line["line_no"])] = (
            number.group(1),
            ecn["ecn_id"],
        )
        repairs.append(
            {
                "repair_ref": ecn["ecn_id"],
                "assembly_id": line["assembly_id"],
                "revision": line["revision"],
                "line_no": line["line_no"],
                "repair_type": "CORRECT_QUANTITY",
                "before_value": line["qty"],
                "after_value": number.group(1),
                "evidence": ecn["evidence"],
            }
        )

    # 3. Build effective line segments, splitting at every approved substitute boundary.
    segments: list[dict[str, str]] = []
    for line in lines:
        revision = revision_map[(line["assembly_id"], line["revision"])]
        if revision["status"] != "APPROVED":
            continue
        active = intersect(
            line["line_effective_from"],
            line["line_effective_to"],
            revision["effective_from"],
            revision["effective_to"],
        )
        if not active:
            continue
        source = components[line["component_id"]]
        correction = quantity_corrections.get(
            (line["assembly_id"], line["revision"], line["line_no"])
        )
        line_qty = correction[0] if correction else line["qty"]
        base_refs = [correction[1]] if correction else []
        factor = factors.get((line["component_id"], line["uom"]))
        if factor is None:
            factor = factors.get(("*", line["uom"]))
        if factor is None:
            raise ValueError(f"Missing UOM conversion for {line['component_id']}/{line['uom']}")

        candidates = [
            sub
            for sub in substitutions
            if sub["from_component_id"] == line["component_id"]
            and sub["configuration"] == revision["configuration"]
            and intersect(active[0], active[1], sub["approved_from"], sub["approved_to"])
            is not None
            and components.get(sub["to_component_id"], {}).get("lifecycle") == "ACTIVE"
            and components.get(sub["to_component_id"], {}).get("compatibility_class")
            == source["compatibility_class"]
            and components.get(sub["to_component_id"], {}).get("base_uom") == source["base_uom"]
        ]
        boundaries = {active[0], next_day(active[1])}
        for sub in candidates:
            lo, hi = intersect(active[0], active[1], sub["approved_from"], sub["approved_to"]) or (
                "",
                "",
            )
            if lo:
                boundaries.add(lo)
                boundaries.add(next_day(hi))
        ordered = sorted(day for day in boundaries if active[0] <= day <= next_day(active[1]))
        for index, start in enumerate(ordered[:-1]):
            end = prev(ordered[index + 1])
            if start > end:
                continue
            applicable = [
                sub for sub in candidates if sub["approved_from"] <= start <= sub["approved_to"]
            ]
            applicable.sort(key=lambda sub: (sub["approved_from"], sub["approval_ref"]))
            chosen = applicable[0] if applicable else None
            component_id = chosen["to_component_id"] if chosen else line["component_id"]
            refs = list(base_refs)
            if chosen:
                refs.append(chosen["approval_ref"])
                repairs.append(
                    {
                        "repair_ref": chosen["approval_ref"],
                        "assembly_id": line["assembly_id"],
                        "revision": line["revision"],
                        "line_no": line["line_no"],
                        "repair_type": "SUBSTITUTE_COMPONENT",
                        "before_value": line["component_id"],
                        "after_value": chosen["to_component_id"],
                        "evidence": "substitutions.csv approved effectivity",
                    }
                )
            segments.append(
                {
                    "assembly_id": line["assembly_id"],
                    "revision": line["revision"],
                    "line_no": line["line_no"],
                    "source_component_id": line["component_id"],
                    "component_id": component_id,
                    "qty_base": qty(d(line_qty) * factor),
                    "base_uom": source["base_uom"],
                    "effective_from": start,
                    "effective_to": end,
                    "repair_refs": ";".join(refs),
                }
            )

    # Deduplicate repair rows created for every segment of the same substituted line.
    unique_repairs: dict[tuple[str, ...], dict[str, str]] = {}
    for repair in repairs:
        unique_repairs[
            (
                repair["repair_ref"],
                repair["assembly_id"],
                repair["revision"],
                repair["line_no"],
                repair["repair_type"],
            )
        ] = repair
    repairs = list(unique_repairs.values())

    segments.sort(
        key=lambda row: (
            row["assembly_id"],
            row["revision"],
            int(row["line_no"]),
            row["effective_from"],
            row["component_id"],
        )
    )
    revised = [
        {
            "assembly_id": row["assembly_id"],
            "revision": row["revision"],
            "effective_from": row["effective_from"],
            "effective_to": row["effective_to"],
            "status": row["status"],
            "configuration": row["configuration"],
            "repair_refs": ";".join(sorted(revision_refs[(row["assembly_id"], row["revision"])])),
        }
        for _, row in sorted(revision_map.items())
    ]

    # 4. Detect arbitrary-length cycles in every revision, including drafts.
    graph: dict[tuple[str, str], list[str]] = defaultdict(list)
    for line in lines:
        component_record = components.get(line["component_id"], {})
        child = component_record.get("child_assembly_id") or (
            line["component_id"] if line["component_id"] in assembly_ids else ""
        )
        if child:
            graph[(line["assembly_id"], line["revision"])].append(child)

    def find_cycles(assembly: str, revision: str) -> list[list[str]]:
        found: list[list[str]] = []
        seen_cycles: set[tuple[str, ...]] = set()
        stack: list[str] = []
        on_stack: set[str] = set()

        def visit(node: str) -> None:
            stack.append(node)
            on_stack.add(node)
            for child in sorted(graph.get((node, revision), [])):
                if child in on_stack:
                    start = stack.index(child)
                    cycle = stack[start:] + [child]
                    canonical = tuple(cycle)
                    if canonical not in seen_cycles:
                        seen_cycles.add(canonical)
                        found.append(cycle)
                elif child not in stack:
                    visit(child)
            on_stack.discard(node)
            stack.pop()

        visit(assembly)
        return found

    cycle_findings: list[dict[str, Any]] = []
    seen_cycle_reports: set[tuple[str, str, tuple[str, ...]]] = set()
    for cycle_assembly, cycle_revision in sorted(revision_map):
        for cycle_path in find_cycles(cycle_assembly, cycle_revision):
            marker = (cycle_assembly, cycle_revision, tuple(cycle_path))
            if marker in seen_cycle_reports:
                continue
            seen_cycle_reports.add(marker)
            cycle_findings.append(
                {
                    "assembly_id": cycle_assembly,
                    "revision": cycle_revision,
                    "cycle_path": cycle_path,
                    "status": "DRAFT_NOT_SELECTABLE"
                    if revision_map[(cycle_assembly, cycle_revision)]["status"] != "APPROVED"
                    else "INVALID",
                }
            )
    cycle_assemblies = {item["assembly_id"] for item in cycle_findings}

    segment_index: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for segment in segments:
        segment_index[(segment["assembly_id"], segment["revision"])].append(segment)

    def selected_revision(assembly: str, configuration: str, when: str) -> dict[str, str]:
        matches = [
            row
            for row in revision_map.values()
            if row["assembly_id"] == assembly
            and row["configuration"] == configuration
            and row["status"] == "APPROVED"
            and row["effective_from"] <= when <= row["effective_to"]
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Expected one approved revision for {assembly}/{configuration}/{when}"
            )
        return matches[0]

    def explode(
        assembly: str,
        revision: str,
        when: str,
        multiplier: Decimal,
        stack: tuple[str, ...],
    ) -> tuple[dict[tuple[str, str], Decimal], bool]:
        if assembly in stack:
            return {}, True
        active = [
            segment
            for segment in segment_index[(assembly, revision)]
            if segment["effective_from"] <= when <= segment["effective_to"]
        ]
        if not active:
            return {}, True
        leaves: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
        blocked = False
        for segment in active:
            detail = components[segment["component_id"]]
            amount = multiplier * d(segment["qty_base"])
            child = detail.get("child_assembly_id", "")
            if not child and segment["component_id"] in assembly_ids:
                child = segment["component_id"]
            if detail["lifecycle"] == "SUPERSEDED":
                future_replacement = any(
                    relation["from_component_id"] == segment["source_component_id"]
                    and relation["configuration"]
                    == revision_map[(assembly, revision)]["configuration"]
                    and relation["approved_from"] > when
                    for relation in substitutions
                )
                if not future_replacement:
                    blocked = True
                    continue
            if child:
                try:
                    child_revision = selected_revision(child, "STD", when)
                except ValueError:
                    blocked = True
                    continue
                child_leaves, child_blocked = explode(
                    child, child_revision["revision"], when, amount, stack + (assembly,)
                )
                blocked = blocked or child_blocked
                for key, value in child_leaves.items():
                    leaves[key] += value
            else:
                leaves[(segment["component_id"], segment["source_component_id"])] += amount
        return leaves, blocked

    requirements: list[dict[str, str]] = []
    blocked_orders: list[str] = []
    historical: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for repair in repairs:
        findings.append(
            {
                "code": {
                    "TRUNCATE_REVISION_EFFECTIVITY": "REVISION_INTERVAL_REPAIRED",
                    "CORRECT_QUANTITY": "QUANTITY_CORRECTED",
                    "SUBSTITUTE_COMPONENT": "SUBSTITUTION_APPLIED",
                }[repair["repair_type"]],
                "assembly_id": repair["assembly_id"],
                "revision": repair["revision"],
                "repair_ref": repair["repair_ref"],
            }
        )
    for cycle_finding in cycle_findings:
        findings.append(
            {
                "code": "CYCLE_DETECTED",
                "assembly_id": cycle_finding["assembly_id"],
                "revision": cycle_finding["revision"],
                "status": cycle_finding["status"],
            }
        )

    for order in sorted(orders, key=lambda row: row["production_order_id"]):
        selected = selected_revision(
            order["assembly_id"], order["configuration"], order["order_date"]
        )
        leaves, blocked = explode(
            order["assembly_id"],
            selected["revision"],
            order["order_date"],
            d(order["quantity"]),
            (),
        )
        if selected["assembly_id"] in cycle_assemblies:
            blocked = True
        if blocked:
            requirements.append(
                {
                    "production_order_id": order["production_order_id"],
                    "assembly_id": order["assembly_id"],
                    "revision": selected["revision"],
                    "status": "BLOCKED",
                    "component_id": "",
                    "required_qty_base": "",
                    "base_uom": "",
                    "source_component_id": "",
                }
            )
            blocked_orders.append(order["production_order_id"])
            findings.append(
                {
                    "code": "BLOCKED_ORDER",
                    "production_order_id": order["production_order_id"],
                    "assembly_id": order["assembly_id"],
                    "revision": selected["revision"],
                }
            )
        else:
            for (component_id, source_component_id), value in sorted(leaves.items()):
                requirements.append(
                    {
                        "production_order_id": order["production_order_id"],
                        "assembly_id": order["assembly_id"],
                        "revision": selected["revision"],
                        "status": "READY",
                        "component_id": component_id,
                        "required_qty_base": qty(value),
                        "base_uom": components[component_id]["base_uom"],
                        "source_component_id": source_component_id,
                    }
                )

    # Historical proof: an order is historical when its selected revision is not the
    # latest approved revision for that assembly/configuration at the end of the horizon.
    horizon = max(
        [row["effective_to"] for row in revision_map.values()]
        + [row["order_date"] for row in orders]
        + ["2025-12-31"]
    )
    for order in sorted(orders, key=lambda row: row["production_order_id"]):
        selected = selected_revision(
            order["assembly_id"], order["configuration"], order["order_date"]
        )
        latest = max(
            (
                row["effective_from"]
                for row in revision_map.values()
                if row["assembly_id"] == order["assembly_id"]
                and row["configuration"] == order["configuration"]
                and row["status"] == "APPROVED"
                and row["effective_from"] <= horizon
            ),
            default=selected["effective_from"],
        )
        if selected["effective_from"] < latest:
            historical.append(
                {
                    "production_order_id": order["production_order_id"],
                    "selected_revision": selected["revision"],
                    "order_date": order["order_date"],
                    "preserved": selected["effective_from"]
                    <= order["order_date"]
                    <= selected["effective_to"],
                }
            )

    repairs.sort(
        key=lambda row: (row["repair_ref"], row["assembly_id"], row["revision"], row["line_no"])
    )
    findings.sort(key=lambda row: (row["code"], row["assembly_id"], row.get("revision", "")))
    report = {
        "schema_version": "1.0",
        "findings": findings,
        "blocked_orders": sorted(blocked_orders),
        "cycle_findings": sorted(
            cycle_findings, key=lambda row: (row["assembly_id"], row["revision"])
        ),
        "historical_revision_checks": historical,
    }
    return {
        "bom": {"schema_version": "1.0", "revisions": revised, "lines": segments},
        "requirements": requirements,
        "repairs": repairs,
        "report": report,
    }


def write_outputs(value: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "approved_bom.json").write_text(
        json.dumps(value["bom"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name, rows, fields in [
        (
            "production_requirements.csv",
            value["requirements"],
            [
                "production_order_id",
                "assembly_id",
                "revision",
                "status",
                "component_id",
                "required_qty_base",
                "base_uom",
                "source_component_id",
            ],
        ),
        (
            "repair_log.csv",
            value["repairs"],
            [
                "repair_ref",
                "assembly_id",
                "revision",
                "line_no",
                "repair_type",
                "before_value",
                "after_value",
                "evidence",
            ],
        ),
    ]:
        with (output / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (output / "validation_report.json").write_text(
        json.dumps(value["report"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
