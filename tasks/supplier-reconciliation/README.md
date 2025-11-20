# Supplier three-way reconciliation

**Status:** standalone Harbor-compatible technical package. Fixture data is synthetic and deterministic. The task transfers only four `/app/output` artifacts to a separate verifier; private verifier inputs are not present in the agent image.

## Public technical facts

This task joins vendor aliases, PO lines, date-effective contracts, goods receipts, inspection acceptance, multi-currency invoices, credits and ERP AP evidence. The intended solution must make allocation decisions in invoice order and produce both controlled payable totals and an audit trail.

## Fixture profile

The eval fixture spans 6 suppliers, 15 invoices, 15 invoice lines, 11 goods receipts, 10 dated contracts, 4 currencies and two credit notes across July-September 2025. The `dev` and `stress` generator profiles support smaller and replicated exploration fixtures; the checked-in `eval` profile is the acceptance fixture.

## Difficulty explanation

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** Replace this placeholder with one to three sentences written by a qualified procurement/AP practitioner explaining the meaningful work difficulty and calibration evidence.

## Solution explanation

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** Replace with a concise reviewer-facing explanation written by the task's human domain author. Technical source is provided for local reproducibility but must not be represented as human-authored contribution prose.

## Verification explanation

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** Replace with a human-authored summary of the independent reconciliation calculations, artifact boundary, and negative tests.

## Relevant experience

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** A submitting maintainer must state their own relevant professional experience truthfully; do not retain or attribute this placeholder.
