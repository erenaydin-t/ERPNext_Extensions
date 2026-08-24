# Release 4.6.1 — Account Explorer drill-down performance

## Summary

Account Explorer account-axis **drill-down** no longer runs company-wide GL aggregation when the user selects a real account tree. The E1 Trial Balance path scopes opening, period, and OpeningEntryPolicy auxiliary GL queries to the selected account subtree (`included_account_names` / lft–rgt descendants).

## What changed

- **E1 engine** scopes GL aggregation to the selected account tree on drill/filter.
- **Root / company-wide** Account Explorer behavior is unchanged (full-company scans when scope covers the whole chart).
- Prepared Report architecture is unchanged.
- OpeningEntryPolicy OFF/ON semantics are unchanged.

## Explicitly out of scope

- No Redis
- No database indexes
- No schema migration
- No GL posting changes
- No additional background workers
- No Prepared Report redesign

## Performance

| Context | Timing |
|---------|--------|
| Before — production Account drill-down (miss / Preparing…) | **34–52 seconds** |
| After — restore-espad materialize for account `1114` tree | **~1.5 seconds** |

Root/company Apply remains a full-scope GL pass (same class as before).

## Accounting correctness

- GF fixtures (GF-01 … GF-17 / golden + production integration): **PASS**
- 24-cell OpeningEntryPolicy axis matrix: **PASS**
- Analytical filter parity: **PASS**
- PCV/ACB integration: **PASS**
- Maximum accounting difference (scoped vs company-wide measures for accounts in scope): **0**

## Version

`erpnext_extensions` **4.6.0 → 4.6.1**
