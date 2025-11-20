# Terminal-Bench proposal preparation template

> **Human completion required.** Do not submit this text unchanged or represent it as a human domain-expert proposal. Replace bracketed fields with a qualified contributor's own account, real calibration data and maintainer feedback.

## Candidate: `[task slug]`

- **Domain and paid-work analogue:** `[Human author: describe an actual manufacturing/procurement/quality/cost role and workflow.]`
- **Why it is meaningfully difficult:** `[Human author: explain the interacting constraints; avoid generic “many files” claims.]`
- **What an agent must produce:** `[Human author: summarize declared artifacts and their business use.]`
- **Objective verification:** `[Human author: summarize independent recomputation, invariants and negative tests.]`
- **Fairness/solvability evidence:** `[Human author: report Oracle, NOP, mutation and actual model trial outcomes, including failures.]`
- **Originality review:** `[Human author: compare against relevant currently merged Terminal-Bench tasks.]`
- **Domain expertise:** `[Human author: truthfully state relevant experience and review process.]`
- **Maintainer discussion / feedback:** `[Link or summarize only real discussion.]`

## Technical facts available for human review

| Candidate | Public scenario facts | Offline validation supplied |
|---|---|---|
| supplier-reconciliation | aliases, partial inspection acceptance, dated contracts, duplicate AP claims, FX/tax/credits | Oracle/NOP/mutation local contract; native Harbor Oracle 1.0 / NOP 0.0 |
| inventory-corruption-recovery | idempotent event replay, lots, reservations, partial transfers, signed recovery evidence | Oracle/NOP/mutation + replay permutation property; native Harbor verified |
| manufacturing-cost-variance | time-effective standards and explicit cost-factor identity | Oracle/NOP/mutation + Decimal reconciliation; native Harbor verified |
| bom-consistency-audit | ECN-backed temporal repair, substitutions, requirement explosion, blocked configuration/cycle | Oracle/NOP/mutation + historical selection; native Harbor verified |
| production-data-repair | MES/PLC/ERP/QMS clock and linkage repair with genealogy | Oracle/NOP/mutation + accounting conservation; native Harbor verified |

## Pre-submission gate

- [ ] Replace `HUMAN-AUTHORSHIP REQUIRED` task README sections with real human-authored content.
- [ ] Set actual author name, email and GitHub handle in `task.toml`.
- [ ] Run current upstream static checks from the intended Terminal-Bench checkout.
- [ ] Build task and separate verifier containers on Docker.
- [ ] Run native Harbor Oracle = 1.0 and NOP = 0.0.
- [ ] Run approved agent trials, record settings/cost/time, and analyze failures without inventing results.
- [ ] Obtain and incorporate maintainer feedback before claiming contribution readiness.
