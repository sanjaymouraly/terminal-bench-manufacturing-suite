# Manufacturing production data and traceability repair

Reconstruct a defensible production history from immutable MES, PLC, ERP, QMS and maintenance evidence in `/app/data`. Do not change raw inputs; create corrected records only under `/app/output`.

## Required deliverables

1. `/app/output/reconstructed_history.jsonl`, sorted by `utc_ts,authority_rank,event_id`, with objects containing `event_id`, `utc_ts`, `authority_rank`, `event_type`, `machine_id`, `work_order_id`, `batch_id`, `lot_id`, `qty`, `uom`, `provenance`, and `repair_ref`.
2. `/app/output/batch_genealogy.csv`, ordered by `output_batch_id,input_lot_id`, columns `output_batch_id,work_order_id,input_lot_id,consumed_qty,consumed_uom,good_output_qty,scrap_qty,traceability_status`.
3. `/app/output/production_accounting.csv`, ordered by `work_order_id`, columns `work_order_id,good_qty,scrap_qty,total_accounted_qty,input_qty,input_uom,yield_pct,status`.
4. `/app/output/quality_dispositions.csv`, ordered by `batch_id,inspection_id`, columns `batch_id,inspection_id,result,disposition,utc_ts,repair_ref`.
5. `/app/output/repair_audit.json` with keys `schema_version`, `clock_normalization`, `dropped_duplicate_ids`, `quarantined_conflict_ids`, `state_conflicts_resolved`, `material_reallocations`, `batch_link_repairs`, and `invariants`.
   - `clock_normalization` items contain `source`, `offset_seconds`, `authority_rank`.
   - `state_conflicts_resolved` items contain `machine_id`, `discarded_event_id`, `kept_event_id`, `maintenance_id`.
   - `material_reallocations` items contain `event_id`, `from_work_order_id`, `to_work_order_id`, `repair_ref`.
   - `batch_link_repairs` items contain `inspection_id`, `from_batch_id`, `to_batch_id`, `repair_ref`.
   - `invariants` is an object with boolean fields `accounting_conserved`, `all_consumption_routed`, `failed_holds_preserved`, and `unique_history_event_ids`.

Use decimal strings (up to three decimal places) for quantities and yield percent. All normalized timestamps must be UTC `YYYY-MM-DDTHH:MM:SSZ`.

## Binding repair policy

- Convert MES, PLC and QMS local timestamps to UTC by subtracting `clock_offsets.csv.offset_seconds`; ERP timestamps are already UTC. Use the listed `authority_rank` for deterministic tie ordering.
- Event IDs are idempotency keys. For repeated IDs where every business field is identical, retain one event, drop the duplicate, and report its ID in `dropped_duplicate_ids`. For conflicting duplicates, retain the occurrence with the earliest MES `recorded_ts` (then earliest `local_ts`), quarantine every other occurrence, and report the ID in `quarantined_conflict_ids`. Never average or add conflicting duplicates.
- A maintenance row explicitly names a `stale_event_id` and its `replacement_event_id`. The maintenance record overrides that stale lower-quality PLC state. Retain the replacement evidence and report the resolution. Do not discard any other PLC event.
- ERP `OUTPUT_RECEIPT` and `SCRAP` movements are authoritative accounting quantities. If retained MES evidence lacks a completion/scrap event for a work order, synthesize a `RECOVERED_COMPLETE` or `RECOVERED_SCRAP` history event with `provenance` `ERP` and `repair_ref` equal to the ERP movement ID. Do not invent a quantity not supported by ERP or PLC evidence.
- Reallocate a material consumption only when `allocation_evidence.csv` names its event and corrected work order. Preserve the original event ID and set `repair_ref` to the evidence ID.
- Correct a QMS batch link only when `batch_link_evidence.csv` names the inspection and corrected batch. QMS disposition is authoritative after correction; where a batch has multiple inspections, the latest UTC inspection governs.
- For each output batch, genealogy must list every corrected material input lot associated with its work order. `good_output_qty + scrap_qty = total_accounted_qty`, no input lot may be assigned to an unrelated work order, and every failed/HOLD disposition must remain HOLD.

You have 1800 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
