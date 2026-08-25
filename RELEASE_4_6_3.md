# Release 4.6.3 — Account hierarchy filter presentation

## Summary

Account Explorer **hierarchy filters now preserve the selected presentation
level**. Filtering an Account Group (example: Group **11**) while viewing
**Account Levels → Group** returns **only** that Group row. Child GL/SL codes
are no longer shown until the user explicitly navigates/drills.

This is a **presentation / drill-graph** fix only.

## Behavior

- Filtering Account Group **11** while viewing **Group** now returns only
  **Group 11**.
- **Analyze** keeps the current Account Levels pill (no automatic level advance).
- Explicit **navigation / drill** still opens child accounts (1110, 1112, …).
- Totals remain calculated from the selected account scope.
- No accounting calculation, Opening Entry Policy, or E1/E3 query changes.
- v4.6.2 scoped performance and empty-classification behavior unchanged.

## Root cause

The default drill graph treated Account Group / General Ledger **filter**
intent as `apply_filter` **plus** optional `advance_level`. Analyze therefore
bumped Group→GL (or GL→SL), so the summary grid aggregated at the deeper
code length and showed children.

## What changed

- `explorer_drill_graph.js`: `advance_level` is **navigate-only** for Account
  Group and General Ledger; filter intent only applies the session Analysis
  Filter.
- Unit / API tests for Group and GL presentation under account scope.
- Playwright suite: Group 11 → one row; Analyze keeps level; navigate reveals
  GL children; GL presentation shows only GL codes.

## Explicitly out of scope

- GL measure / Opening Entry Policy / Prepared Report changes
- E1/E3 SQL path or index policy changes
- Petty management, local benchmarks, screenshots

## Test plan

- Hierarchy presentation unit/API tests
- Cube navigation (filter does not advance level)
- Opening GF fixtures
- 24-cell opening policy axis matrix
- Analytical filter parity
- Voucher parity
- Opening PCV/ACB integration
- Playwright hierarchy filter suite
- `bench build --app erpnext_extensions`
