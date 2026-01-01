# Project Agent Rules (MUST FOLLOW)

## Source of Truth
- The ONLY source of truth for product requirements is: PRD/product_prd.md
- Before ANY code changes, you MUST:
  1) Open and read PRD/product_prd.md fully.
  2) Extract: scope (in/out), acceptance criteria, constraints, and any requirement IDs/headings.
  3) Produce an implementation plan that references PRD headings/sections.
- If PRD is ambiguous or missing details, STOP and ask questions. Do not guess.

## Change Policy
- PRD wins over existing code behavior or comments.
- Prefer minimal, reviewable diffs. Keep changes tightly aligned to PRD.

## Testing Policy (Python)
- After each meaningful change, run:
  - `pytest -q`
- If tests fail, fix and rerun until passing.
- If no tests exist for a PRD requirement, add tests (pytest) to cover acceptance criteria.

## Traceability
- For every change, maintain a short mapping:
  - PRD section -> files changed -> tests added/updated
- End your work with a "PRD Trace" summary.
