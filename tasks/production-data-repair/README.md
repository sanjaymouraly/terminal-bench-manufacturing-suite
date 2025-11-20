# Manufacturing production data and traceability repair

**Status:** standalone Harbor-compatible technical package. It reconstructs a production record from synthetic MES, PLC, ERP, QMS and maintenance evidence without any external service.

## Public technical facts

The challenge combines source-specific clock correction, duplicate suppression, stale machine-state resolution, ERP-supported completion/scrap recovery, evidentiary material reallocation, inspection batch-link repair and batch genealogy conservation.

## Fixture profile

The eval fixture spans 6 work orders, 24 MES events, 8 PLC events, 12 ERP movements, 6 inspections, 2 maintenance overrides and 2 evidence-based reallocations. The `dev` and `stress` generator profiles support smaller and replicated exploration fixtures; the checked-in `eval` profile is the acceptance fixture.

## Difficulty explanation

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** Replace this placeholder with one to three sentences written by a qualified MES, quality, or traceability practitioner explaining the meaningful work difficulty and calibration evidence.

## Solution explanation

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** Replace with a concise reviewer-facing explanation written by the task's human domain author. Technical source is provided for local reproducibility but must not be represented as human-authored contribution prose.

## Verification explanation

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** Replace with a human-authored summary of independent cross-system accounting, genealogy and mutation-rejection checks.

## Relevant experience

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** A submitting maintainer must state their own relevant professional experience truthfully; do not retain or attribute this placeholder.
