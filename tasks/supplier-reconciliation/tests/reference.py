#!/usr/bin/env python3
"""Reference implementation for the supplier three-way reconciliation task."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

CENT = Decimal("0.01")
QTY = Decimal("0.001")


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


def money(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), "f")


def quantity(value: Decimal) -> str:
    return format(value.quantize(QTY, rounding=ROUND_HALF_UP).normalize(), "f")


def read_csv(root: Path, name: str) -> list[dict[str, str]]:
    with (root / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def normalized_invoice(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def fx_lookup(rows: list[dict[str, str]]) -> dict[tuple[str, str], Decimal]:
    rates = {(row["rate_date"], row["currency"]): dec(row["inr_per_unit"]) for row in rows}
    return rates


def rate(rates: dict[tuple[str, str], Decimal], date: str, currency: str) -> Decimal:
    if currency == "INR":
        return Decimal("1")
    try:
        return rates[(date, currency)]
    except KeyError as exc:
        raise ValueError(f"Missing FX rate for {date}/{currency}") from exc


def compute(data: Path) -> dict[str, Any]:
    aliases = {
        row["observed_supplier_id"]: row["supplier_id"]
        for row in read_csv(data, "supplier_aliases.csv")
    }
    conversions = {
        (row["item_id"], row["uom"]): dec(row["factor_to_base"])
        for row in read_csv(data, "uom_conversions.csv")
    }
    receipts = {row["receipt_id"]: row for row in read_csv(data, "goods_receipts.csv")}
    inspections = {row["receipt_id"]: row for row in read_csv(data, "inspections.csv")}
    contracts = read_csv(data, "contracts.csv")
    invoice_rows = read_csv(data, "invoices.csv")
    line_rows = read_csv(data, "invoice_lines.csv")
    credits = read_csv(data, "supplier_credits.csv")
    rates = fx_lookup(read_csv(data, "fx_rates.csv"))

    accepted_by_po: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for receipt_id, receipt in receipts.items():
        inspection = inspections[receipt_id]
        factor = conversions[(receipt["item_id"], inspection["uom"])]
        accepted_by_po[(receipt["po_id"], receipt["line_no"])] += (
            dec(inspection["accepted_qty"]) * factor
        )

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for item in invoice_rows:
        canonical = aliases[item["observed_supplier_id"]]
        grouped[(canonical, normalized_invoice(item["invoice_number"]))].append(item)
    duplicate_of: dict[str, str] = {}
    for members in grouped.values():
        members.sort(key=lambda row: (row["invoice_date"], row["invoice_id"]))
        keeper = members[0]["invoice_id"]
        for duplicate in members[1:]:
            duplicate_of[duplicate["invoice_id"]] = keeper

    lines_by_invoice: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in line_rows:
        lines_by_invoice[row["invoice_id"]].append(row)

    available = dict(accepted_by_po)
    disputes: list[dict[str, str]] = []
    decisions: dict[str, dict[str, Any]] = {}
    line_details: dict[str, list[dict[str, Any]]] = defaultdict(list)

    candidates = [row for row in invoice_rows if row["invoice_id"] not in duplicate_of]
    candidates.sort(key=lambda row: (row["invoice_date"], row["invoice_id"]))
    for invoice in candidates:
        invoice_id = invoice["invoice_id"]
        supplier = aliases[invoice["observed_supplier_id"]]
        total_gross = Decimal("0")
        total_unresolved = Decimal("0")
        supported_qty_sum = Decimal("0")
        reasons: set[str] = set()
        for line in sorted(lines_by_invoice[invoice_id], key=lambda row: row["line_no"]):
            factor = conversions[(line["item_id"], line["uom"])]
            billed_qty = dec(line["qty"]) * factor
            key = (line["po_id"], line["po_line_no"])
            supported_qty = min(billed_qty, available.get(key, Decimal("0")))
            available[key] = available.get(key, Decimal("0")) - supported_qty
            matching = [
                row
                for row in contracts
                if row["supplier_id"] == supplier
                and row["item_id"] == line["item_id"]
                and row["effective_from"] <= invoice["invoice_date"] <= row["effective_to"]
            ]
            if len(matching) != 1:
                raise ValueError(
                    f"Expected exactly one contract for {invoice_id}/{line['line_no']}"
                )
            contract = matching[0]
            contract_factor = conversions[(line["item_id"], contract["uom"])]
            billed_per_base = (
                dec(line["unit_price"])
                / factor
                * rate(rates, invoice["invoice_date"], invoice["currency"])
            )
            contract_per_base = (
                dec(contract["unit_price"])
                / contract_factor
                * rate(rates, invoice["invoice_date"], contract["currency"])
            )
            tax = dec(contract["tax_rate"])
            supported_per_base = min(billed_per_base, contract_per_base)
            gross = (supported_qty * supported_per_base * (Decimal("1") + tax)).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
            total_gross += gross
            supported_qty_sum += supported_qty
            detail = {
                "line_no": line["line_no"],
                "supported_qty": supported_qty,
                "billed_qty": billed_qty,
                "gross": gross,
                "billed_per_base": billed_per_base,
                "contract_per_base": contract_per_base,
                "tax": tax,
            }
            line_details[invoice_id].append(detail)
            if billed_per_base > contract_per_base and supported_qty > 0:
                amount = (
                    (billed_per_base - contract_per_base) * supported_qty * (Decimal("1") + tax)
                ).quantize(CENT, rounding=ROUND_HALF_UP)
                total_unresolved += amount
                reasons.add("PRICE_ABOVE_CONTRACT")
                disputes.append(
                    {
                        "invoice_id": invoice_id,
                        "line_no": line["line_no"],
                        "reason_code": "PRICE_ABOVE_CONTRACT",
                        "disputed_qty_base": quantity(supported_qty),
                        "disputed_amount_inr": money(amount),
                        "detail": "Billed price exceeds effective contract price.",
                    }
                )
            short_qty = billed_qty - supported_qty
            if short_qty > 0:
                amount = (short_qty * billed_per_base * (Decimal("1") + tax)).quantize(
                    CENT, rounding=ROUND_HALF_UP
                )
                total_unresolved += amount
                reasons.add("QUANTITY_NOT_ACCEPTED")
                disputes.append(
                    {
                        "invoice_id": invoice_id,
                        "line_no": line["line_no"],
                        "reason_code": "QUANTITY_NOT_ACCEPTED",
                        "disputed_qty_base": quantity(short_qty),
                        "disputed_amount_inr": money(amount),
                        "detail": "Billed quantity exceeds accepted, previously unallocated receipt quantity.",
                    }
                )
        decisions[invoice_id] = {
            "supplier": supplier,
            "gross": total_gross.quantize(CENT, rounding=ROUND_HALF_UP),
            "unresolved": total_unresolved.quantize(CENT, rounding=ROUND_HALF_UP),
            "supported_qty": supported_qty_sum,
            "reasons": reasons,
        }

    credits_by_invoice: dict[str, Decimal] = defaultdict(Decimal)
    kept_for_key = {
        key: sorted(values, key=lambda row: (row["invoice_date"], row["invoice_id"]))[0][
            "invoice_id"
        ]
        for key, values in grouped.items()
    }
    for credit in credits:
        supplier = aliases[credit["observed_supplier_id"]]
        key = (supplier, normalized_invoice(credit["invoice_number"]))
        credited_invoice_id = kept_for_key.get(key)
        if credited_invoice_id:
            credits_by_invoice[credited_invoice_id] += dec(credit["amount"]) * rate(
                rates, credit["credit_date"], credit["currency"]
            )

    payable_rows: list[dict[str, str]] = []
    audit_decisions: list[dict[str, Any]] = []
    for invoice in sorted(invoice_rows, key=lambda row: row["invoice_id"]):
        invoice_id = invoice["invoice_id"]
        supplier = aliases[invoice["observed_supplier_id"]]
        if invoice_id in duplicate_of:
            payable_rows.append(
                {
                    "invoice_id": invoice_id,
                    "invoice_number": invoice["invoice_number"],
                    "canonical_supplier_id": supplier,
                    "duplicate_of": duplicate_of[invoice_id],
                    "status": "DUPLICATE",
                    "gross_supported_inr": "0.00",
                    "credit_inr": "0.00",
                    "net_payable_inr": "0.00",
                    "unresolved_amount_inr": "0.00",
                    "reason_codes": "DUPLICATE_INVOICE",
                }
            )
            disputes.append(
                {
                    "invoice_id": invoice_id,
                    "line_no": "",
                    "reason_code": "DUPLICATE_INVOICE",
                    "disputed_qty_base": "0",
                    "disputed_amount_inr": "0.00",
                    "detail": f"Duplicate of {duplicate_of[invoice_id]} after supplier and invoice normalization.",
                }
            )
            audit_decisions.append(
                {
                    "invoice_id": invoice_id,
                    "canonical_supplier_id": supplier,
                    "duplicate_of": duplicate_of[invoice_id],
                    "receipt_supported_qty_base": "0",
                    "applied_credit_inr": "0.00",
                }
            )
            continue
        decision = decisions[invoice_id]
        gross = decision["gross"]
        credit = min(gross, credits_by_invoice[invoice_id].quantize(CENT, rounding=ROUND_HALF_UP))
        net = gross - credit
        unresolved = decision["unresolved"]
        if net == 0 and gross > 0:
            status = "CREDIT_EXHAUSTED"
        elif unresolved > 0 and net > 0:
            status = "PARTIAL_DISPUTE"
        elif unresolved > 0:
            status = "DISPUTED"
        else:
            status = "PAYABLE"
        payable_rows.append(
            {
                "invoice_id": invoice_id,
                "invoice_number": invoice["invoice_number"],
                "canonical_supplier_id": supplier,
                "duplicate_of": "",
                "status": status,
                "gross_supported_inr": money(gross),
                "credit_inr": money(credit),
                "net_payable_inr": money(net),
                "unresolved_amount_inr": money(unresolved),
                "reason_codes": ";".join(sorted(decision["reasons"])),
            }
        )
        audit_decisions.append(
            {
                "invoice_id": invoice_id,
                "canonical_supplier_id": supplier,
                "duplicate_of": "",
                "receipt_supported_qty_base": quantity(decision["supported_qty"]),
                "applied_credit_inr": money(credit),
            }
        )

    payable_rows.sort(key=lambda row: row["invoice_id"])
    disputes.sort(key=lambda row: (row["invoice_id"], row["line_no"], row["reason_code"]))
    total_gross = sum((dec(row["gross_supported_inr"]) for row in payable_rows), Decimal("0"))
    total_credit = sum((dec(row["credit_inr"]) for row in payable_rows), Decimal("0"))
    total_net = sum((dec(row["net_payable_inr"]) for row in payable_rows), Decimal("0"))
    total_unresolved = sum(
        (dec(row["unresolved_amount_inr"]) for row in payable_rows), Decimal("0")
    )
    reconciliation = {
        "schema_version": "1.0",
        "currency": "INR",
        "invoice_count": len(invoice_rows),
        "duplicate_invoice_count": len(duplicate_of),
        "gross_supported_inr": money(total_gross),
        "credits_inr": money(total_credit),
        "net_payable_inr": money(total_net),
        "unresolved_amount_inr": money(total_unresolved),
        "payable_invoice_ids": [
            row["invoice_id"] for row in payable_rows if dec(row["net_payable_inr"]) > 0
        ],
    }
    audit = {
        "schema_version": "1.0",
        "policy": "accepted receipts allocated by invoice date; dated contract cap; document-date FX; credit capped at supported gross",
        "invoice_decisions": audit_decisions,
        "input_files": sorted(path.name for path in data.iterdir() if path.is_file()),
    }
    return {
        "payables": payable_rows,
        "disputes": disputes,
        "reconciliation": reconciliation,
        "audit": audit,
    }


def write_outputs(result: dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    fields = [
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
    with (output / "payables.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(result["payables"])
    fields = [
        "invoice_id",
        "line_no",
        "reason_code",
        "disputed_qty_base",
        "disputed_amount_inr",
        "detail",
    ]
    with (output / "disputes.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(result["disputes"])
    (output / "reconciliation.json").write_text(
        json.dumps(result["reconciliation"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "audit.json").write_text(
        json.dumps(result["audit"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
