# Inventory corruption and ledger recovery

Recover a deterministic, idempotent lot ledger from immutable WMS/MES/ERP source evidence in `/app/data`. Write only under `/app/output`.

## Required deliverables

1. `/app/output/recovered_ledger.jsonl`: one canonical JSON object per accepted source event or approved synthetic recovery event, sorted by `effective_ts,event_id`. Every object must contain `event_id`, `effective_ts`, `operation`, `warehouse`, `lot_id`, `qty_base`, `base_uom`, `transfer_id`, `provenance`, and `idempotency_key`.
2. `/app/output/inventory_balances.csv`, ordered by `warehouse,lot_id`, with columns `warehouse,lot_id,item_id,base_uom,on_hand_qty,reserved_qty,available_qty`.
3. `/app/output/transfer_reconciliation.csv`, ordered by `transfer_id`, with columns `transfer_id,lot_id,dispatched_qty_base,received_qty_base,in_transit_qty_base,status`.
4. `/app/output/recovery_audit.json` with keys `schema_version`, `ledger_digest`, `accepted_event_ids`, `dropped_exact_duplicate_ids`, `quarantined_conflict_ids`, `synthetic_recovery_event_ids`, `snapshot_findings`, and `invariants`.
   - `snapshot_findings` contains exactly one object for every snapshot whose `checksum_status` is not `OK`, with `snapshot_id`, `checksum_status`, and a non-empty `action` string.
   - `invariants` is an object with boolean fields `nonnegative_on_hand`, `nonnegative_reserved`, `unique_idempotency_keys`, and `active_reservation_evidence_matches`.

Quantities are decimal strings rounded only to three decimal places (no binary floating point). `ledger_digest` is the SHA-256 hexadecimal digest of UTF-8 `event_id|effective_ts|operation|warehouse|lot_id|qty_base|provenance` records joined by `\n` in recovered-ledger order.

## Binding recovery policy

- Normalize source quantities with `uom_conversions.csv`. A receipt, positive adjustment, or transfer-in increases on-hand; an issue, negative adjustment, or transfer-out decreases on-hand. Reserve increases reserved quantity only; release decreases reserved quantity only. `available = on_hand - reserved`.
- Event IDs are idempotency keys. For repeated IDs with byte-for-byte identical business fields, retain one event and list the ID once in `dropped_exact_duplicate_ids`. For conflicting duplicates, retain the earliest `recorded_ts` event and quarantine the later conflicting occurrence; list the ID once in `quarantined_conflict_ids`. Never invent a replacement for a quarantined event.
- Add every approved row from `recovery_evidence.csv` as a synthetic event with `provenance` `RECOVERY_EVIDENCE` and `idempotency_key` equal to its recovery ID. This is the only permitted synthetic adjustment source.
- Sort replay by `effective_ts,event_id`, not source-file order or `recorded_ts`. Preserve source events as `provenance` `SOURCE`.
- Reconcile transfers from accepted replay events against `transfer_orders.csv`. `in_transit_qty_base = max(dispatched - received, 0)`. Status is `COMPLETE` when expected, dispatched, and received all agree; `IN_TRANSIT` when dispatched exceeds received; otherwise `EXCEPTION`.
- Snapshots are non-authoritative. Report each stale or corrupt snapshot in `snapshot_findings`; do not force the ledger to match it. Active rows in `reservations.csv` are current reservation evidence and must agree with the reserve/release replay balance.
- A valid recovery has no negative on-hand, reserved, or available balance; unique idempotency keys; every ledger lot exists in `lots.csv`; and deterministic replay digest exactly as specified.

You have 1800 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
