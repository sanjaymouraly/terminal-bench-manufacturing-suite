# Supplier three-way reconciliation

You are the AP controls analyst for a discrete manufacturer. Reconcile the immutable source records in `/app/data` and write all deliverables under `/app/output`. Do not alter `/app/data`.

## Required deliverables

1. `/app/output/payables.csv` with exactly these columns, ordered by `invoice_id`:
   `invoice_id,invoice_number,canonical_supplier_id,duplicate_of,status,gross_supported_inr,credit_inr,net_payable_inr,unresolved_amount_inr,reason_codes`
   `reason_codes` is a semicolon-separated list; use an empty string when none apply.
2. `/app/output/disputes.csv` with exactly these columns, ordered by `invoice_id,line_no,reason_code`:
   `invoice_id,line_no,reason_code,disputed_qty_base,disputed_amount_inr,detail`
   `detail` is a short human-readable explanation and is not a controlled vocabulary.
3. `/app/output/reconciliation.json` with keys `schema_version`, `currency`, `invoice_count`, `duplicate_invoice_count`, `gross_supported_inr`, `credits_inr`, `net_payable_inr`, `unresolved_amount_inr`, and `payable_invoice_ids` (ascending invoice IDs with positive net payable).
4. `/app/output/audit.json` with keys `schema_version`, `policy`, `invoice_decisions`, and `input_files`.
   - `policy` is a non-empty description of the applied policy.
   - `invoice_decisions` contains exactly one object per invoice with `invoice_id`, `canonical_supplier_id`, `duplicate_of`, `receipt_supported_qty_base`, and `applied_credit_inr`.
   - `input_files` is a non-empty list of raw input filenames used.

Use INR as the reporting currency. Monetary values must be decimal strings rounded **half up to two decimal places**; quantities must be decimal strings with no more than three decimal places. Empty CSV values represent an empty string, not `null`.

## Binding reconciliation policy

- Map an invoice or credit's `observed_supplier_id` through `supplier_aliases.csv`. Canonicalize invoice-number comparisons by uppercasing and removing all non-alphanumeric characters.
- A duplicate group is `(canonical supplier, canonical invoice number)`. Keep the member with earliest `invoice_date` (then lowest `invoice_id`); mark every other member `DUPLICATE`, set all payable amounts to zero, set `duplicate_of` to the kept invoice, and emit reason `DUPLICATE_INVOICE`.
- Process non-duplicate invoice lines by `invoice_date, invoice_id, line_no`. Convert invoice, receipt, inspection, and contract quantities to the item base unit with `uom_conversions.csv`. Allocate only **accepted** inspection quantity for each PO line across that ordering. Rejected quantity is never payable.
- Select the one contract matching canonical supplier and item whose inclusive effective dates contain `invoice_date`. Convert both the billed and contract price to INR per base unit using the FX rate for that document date and currency. INR has rate 1.00 even if no row exists. All non-INR document dates used by the inputs have an exact `fx_rates.csv` row.
- For supported quantity, the supported unit price is the lower of billed INR/base-unit price and contract INR/base-unit price. Apply the contract tax rate, line-round gross payable half-up to cents, then sum invoice lines. If billed price exceeds contract price, the excess is unresolved with reason `PRICE_ABOVE_CONTRACT`; if billed quantity exceeds unallocated accepted quantity, the excess is unresolved with reason `QUANTITY_NOT_ACCEPTED`.
- Match credits to the kept invoice using the same canonical supplier and canonical invoice number. Convert credits on `credit_date`, round the summed credit amount per invoice to cents, and cap credit at gross supported amount. A credit cannot make a payable negative.
- `erp_ap.csv` is audit evidence only; never use an existing booking as support for an unsupported invoice.

`status` is determined in this order: `DUPLICATE` for a duplicate invoice; `CREDIT_EXHAUSTED` when gross supported is positive and the applied credit fully exhausts it (net zero); `PARTIAL_DISPUTE` when net payable is positive and unresolved amount is positive; `DISPUTED` when net payable and gross supported are both zero but an unresolved amount remains; otherwise `PAYABLE`. Include one dispute row for each reason affecting a line or duplicate invoice. Your audit must be sufficient for a controller to reproduce each decision.

You have 1800 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
