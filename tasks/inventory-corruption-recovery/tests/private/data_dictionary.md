# Inventory recovery data dictionary

All records are synthetic. Raw inputs are immutable during a task run.

| File | Purpose |
|---|---|
| `stock_events.jsonl` | Append-only but intentionally corrupted multi-warehouse event log. |
| `transfer_orders.csv` | Expected inter-warehouse movement contracts. |
| `stock_snapshots.csv` | Non-authoritative checkpoints marked stale or corrupt. |
| `reservations.csv` | Current active-reservation evidence reconciled to reserve/release events. |
| `recovery_evidence.csv` | Signed, approved count evidence for missing recovery adjustments. |
| `lots.csv / uom_conversions.csv` | Traceability and quantity-normalization masters. |
