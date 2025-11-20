# Production traceability repair data dictionary

All records are synthetic. Raw inputs are immutable during a task run.

| File | Purpose |
|---|---|
| `mes_events.jsonl / plc_logs.jsonl` | Operational records with source-specific clocks and duplicates. |
| `clock_offsets.csv` | Approved offset normalization and source authority ranking. |
| `erp_movements.csv` | Authoritative warehouse output/scrap posting evidence. |
| `quality_inspections.csv / batch_link_evidence.csv` | QMS dispositions and corrective barcode evidence. |
| `allocation_evidence.csv` | Approved correction for a misallocated material issue. |
| `maintenance_events.csv` | Evidence resolving a stale machine-state conflict. |
