# Inventory corruption and ledger recovery

**Status:** standalone Harbor-compatible technical package. Synthetic inputs model event replay, lot-level stock, reservations, partial transfers and signed physical-count evidence. The verifier receives only declared output artifacts and a baked private copy of raw inputs.

## Public technical facts

The task requires idempotent event selection, deterministic ordering independent of log order, unit normalization, transfer-in-transit calculation, and auditable treatment of stale/corrupt snapshots. It has no online or paid dependency.

## Fixture profile

The eval fixture spans 4 warehouses, 7 lots, 37 raw events, 5 transfer orders, 3 active reservations and 5 snapshots covering OK, STALE and CORRUPT states. The `dev` and `stress` generator profiles support smaller and replicated exploration fixtures; the checked-in `eval` profile is the acceptance fixture.

## Difficulty explanation

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** Replace this placeholder with one to three sentences written by a qualified inventory-control or warehouse-systems practitioner explaining the meaningful work difficulty and calibration evidence.

## Solution explanation

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** Replace with a concise reviewer-facing explanation written by the task's human domain author. Technical source is provided for local reproducibility but must not be represented as human-authored contribution prose.

## Verification explanation

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** Replace with a human-authored summary of independent replay, conservation and mutation-rejection checks.

## Relevant experience

**HUMAN-AUTHORSHIP REQUIRED BEFORE UPSTREAM SUBMISSION.** A submitting maintainer must state their own relevant professional experience truthfully; do not retain or attribute this placeholder.
