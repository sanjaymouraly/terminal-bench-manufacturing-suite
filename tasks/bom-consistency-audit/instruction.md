# Time-effective BOM consistency and engineering change audit

Audit and repair immutable engineering data in `/app/data`. You may apply only changes supported by approved records in `engineering_changes.csv` or `substitutions.csv`; do not silently invent engineering decisions. Write deliverables under `/app/output`.

## Required deliverables

1. `/app/output/approved_bom.json` with keys `schema_version`, `revisions`, and `lines`.
   - Each revision object must contain `assembly_id`, `revision`, `effective_from`, `effective_to`, `status`, `configuration`, and `repair_refs` (semicolon-separated ECN IDs that changed the interval; empty when none).
   - Each line object must contain `assembly_id`, `revision`, `line_no`, `source_component_id`, `component_id`, `qty_base`, `base_uom`, `effective_from`, `effective_to`, and `repair_refs` (semicolon-separated approval references applied to that slice; empty when none).
   - Lines are ordered by `assembly_id, revision, line_no` (numeric), `effective_from`, `component_id`. Revisions are ordered by `assembly_id, revision`.
2. `/app/output/production_requirements.csv`, ordered by `production_order_id,component_id`, columns `production_order_id,assembly_id,revision,status,component_id,required_qty_base,base_uom,source_component_id`.
3. `/app/output/repair_log.csv`, ordered by `repair_ref,assembly_id,revision,line_no`, columns `repair_ref,assembly_id,revision,line_no,repair_type,before_value,after_value,evidence`.
4. `/app/output/validation_report.json` with keys `schema_version`, `findings`, `blocked_orders`, `cycle_findings`, and `historical_revision_checks`.
   - `findings` items must contain `code`, `assembly_id`, and `revision`; order-blocking findings additionally contain `production_order_id`. Codes are `REVISION_INTERVAL_REPAIRED`, `QUANTITY_CORRECTED`, `SUBSTITUTION_APPLIED`, `CYCLE_DETECTED`, and `BLOCKED_ORDER`.
   - `cycle_findings` items must contain `assembly_id`, `revision`, `cycle_path` (assembly IDs ending with the repeated node), and `status` (`INVALID` for approved revisions, `DRAFT_NOT_SELECTABLE` otherwise).
   - `historical_revision_checks` contains one object for every order whose selected revision is not the latest approved revision for its assembly/configuration, with `production_order_id`, `selected_revision`, `order_date`, and boolean `preserved`.

Quantities are decimal strings with at most three decimal places. All dates are inclusive calendar dates.

## Binding policy

- Select only `APPROVED` revisions for production. When an approved `SUPERSEDE_REVISION` ECN takes effect, truncate the target revision's end date to the calendar day before that ECN's effective date. This resolves the A/B effective overlap without rewriting historical orders. An ECN that would not shorten the interval is not applied.
- Select an order revision by assembly, configuration, and order date after the above repair. Preserve a valid historical revision where it was applicable.
- Normalize line quantities to the component base unit using the component-specific conversion when available, otherwise the `component_id=*` conversion. Apply an approved `CORRECT_QUANTITY` ECN only to its documented line: its evidence states the corrected quantity.
- A `SUPERSEDED` component may be replaced only by a substitution with matching configuration and inclusive approval date. The replacement must be `ACTIVE` and share the source component compatibility class and base UOM. Before a future same-configuration substitute becomes effective, retain the historical source component; this preserves historical correctness. Preserve `source_component_id` and record the ECN/substitution approval reference.
- Recursively explode subassemblies into purchased components using `components.csv.child_assembly_id`. Multiply quantities across levels. Child assemblies use their approved `STD` revision effective on the order date. Detect cycles of any length before explosion; draft or non-selected configurations must still be reported as findings when cyclic, but may not be used to manufacture requirements. If a selected configuration or subassembly has no unique approved revision, or is affected by a cycle, block the order.
- If an order's selected configuration contains a superseded component with no valid approved substitute, return exactly one `BLOCKED` requirement row for that order with empty component and quantity fields, list it in `blocked_orders`, and retain a validation finding. Do not substitute a part approved only for another configuration.
- `repair_log.csv` must list every applied interval truncation, quantity correction, and substitute. `validation_report.json` must explain unsupported defects rather than repairing them.

You have 1800 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
