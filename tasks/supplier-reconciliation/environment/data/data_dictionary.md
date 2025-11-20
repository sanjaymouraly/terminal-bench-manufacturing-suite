# Supplier reconciliation data dictionary

All records are synthetic. Raw inputs are immutable during a task run.

| File | Purpose |
|---|---|
| `suppliers.csv / supplier_aliases.csv` | Canonical vendor master and observed-system aliases. |
| `po_lines.csv / contracts.csv` | Purchase commitments and dated commercial terms. |
| `goods_receipts.csv / inspections.csv` | Physical receipt and quality acceptance evidence. |
| `invoices.csv / invoice_lines.csv / supplier_credits.csv` | Supplier AP claims and credits. |
| `fx_rates.csv` | Specified document-date conversion rates to INR. |
| `erp_ap.csv` | Existing AP booking evidence; it is not authoritative for support. |
