# BOM consistency data dictionary

All records are synthetic. Raw inputs are immutable during a task run.

| File | Purpose |
|---|---|
| `revisions.csv / bom_lines.csv` | Revision and line-level temporal assembly definition. |
| `components.csv / substitutions.csv` | Lifecycle, unit and approved substitute evidence. |
| `engineering_changes.csv` | Approved evidence for the only permissible repairs. |
| `production_orders.csv` | Historical and current requirement requests. |
| `routing.csv` | Revision-specific operation context. |
