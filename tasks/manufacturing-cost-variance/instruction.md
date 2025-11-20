# Manufacturing cost variance investigation

Produce a machine-readable investigation of the immutable cost records in `/app/data`. All reporting is in INR and all deliverables go under `/app/output`.

## Required deliverables

1. `/app/output/order_variances.csv`, ordered by `work_order_id`, columns:
   `work_order_id,period,actual_cost_inr,planned_standard_cost_inr,total_variance_inr,purchase_price_variance_inr,fx_variance_inr,material_yield_scrap_variance_inr,labor_rate_variance_inr,labor_efficiency_variance_inr,machine_rate_variance_inr,machine_utilization_variance_inr,overhead_spending_variance_inr,overhead_absorption_variance_inr,volume_variance_inr,reconciliation_difference_inr`
2. `/app/output/factor_summary.csv`, ordered by `factor`, columns `factor,variance_inr,absolute_variance_inr,materiality_rank`. `materiality_rank` is a one-based integer string after sorting by descending absolute variance then factor name.
3. `/app/output/variance_report.json` with keys `schema_version`, `currency`, `rounding_policy` (non-empty description), `order_count`, `actual_cost_inr`, `planned_standard_cost_inr`, `total_variance_inr`, `factor_total_inr`, `reconciliation_difference_inr`, and `material_factors`.
4. `/app/output/investigation_findings.json` with keys `schema_version`, `findings`, and `accounting_policies`. Each finding object contains `work_order_id`, `factor`, signed INR string `variance_inr`, and a non-empty `evidence_ids` list. `accounting_policies` is a non-empty list of policy description strings.

Every INR monetary field is a string rounded half-up to cents. Use Decimal arithmetic. Do not round intermediate calculations; round each final factor and final total to cents.

## Binding accounting policy

Select the one standard whose product and inclusive effective dates contain each work order `release_date`. Aggregate actual material, labor, machine and overhead records by work order. The standard base material cost per unit is `standard_foreign_price * budget_fx_inr`.

For each work order, calculate these signed unfavorable-positive factors:

- `purchase_price_variance = sum(actual_qty * (actual_foreign_unit_price - standard_foreign_price) * actual_fx_rate_inr)` over all material rows
- `fx_variance = sum(actual_qty * standard_foreign_price * (actual_fx_rate_inr - budget_fx_inr))` over all material rows
- `material_yield_scrap_variance = standard_material_price_base * (actual_material_qty - material_qty_per_good * actual_good_qty)`
- `labor_rate_variance = actual_labor_hours * (actual_labor_rate - standard_labor_rate)`
- `labor_efficiency_variance = standard_labor_rate * (actual_labor_hours - standard_labor_hours_per_good * actual_good_qty)`
- `machine_rate_variance = actual_machine_hours * (actual_machine_rate - standard_machine_rate)` where actual machine rate is the hour-weighted actual rate
- `machine_utilization_variance = standard_machine_rate * (actual_machine_hours - standard_machine_hours_per_good * actual_good_qty)`
- `overhead_spending_variance = actual_overhead - standard_overhead_rate * actual_machine_hours`
- `overhead_absorption_variance = standard_overhead_rate * (actual_machine_hours - standard_machine_hours_per_good * actual_good_qty)`
- `volume_variance = standard_unit_cost * (actual_good_qty - planned_good_qty)`, where standard unit cost includes material, labor, machine and overhead.

`actual_cost` is actual material cost plus actual labor cost plus actual machine cost plus actual overhead. `planned_standard_cost = standard_unit_cost * planned_good_qty`. The sum of all factors must reconcile to `actual_cost - planned_standard_cost` within INR 0.01. `material_factors` are factors whose absolute suite total is at least INR 1,000, ranked by descending absolute variance then factor name. Include an investigation finding for each order/factor whose unrounded absolute factor variance is at least INR 1,000; sort findings by work order then factor.

You have 1800 seconds to complete this task. Do not cheat by using online solutions or hints specific to this task.
