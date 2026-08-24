# Release 4.6.2 — E1 scoped period index + empty classification exclusion

## Summary

Account Explorer **navigator account drills** (E1) no longer force
`posting_date_company_index` on period GL SQL when `account IN (...)` narrowing
is active. MariaDB can use the `account` index, so leaf/group drills approach
E3 filter-panel latency. Root / company-wide E1 is unchanged.

**Also in 4.6.2:** empty classification buckets (Unspecified party / Unassigned
dimension / Unmapped unified party / blank currency) are **excluded before
aggregation**. They do not appear in rows, subtotals, grand totals, balance
fields, or pagination counts. Account-axis Unclassified taxonomy is unchanged.

## Root cause (E1)

v4.6.1 correctly pushed `included_account_names` into E1 opening / period /
policy-aux queries, but `_set_period_gl_entries_for_e1` still called:

```python
query = query.force_index("posting_date_company_index")
```

That forced a company/date range scan even for a single leaf account, while the
same leaf via the Filters panel (E3) finished in tens of milliseconds.

## What changed

- **E1 scoped period path**: omit `FORCE INDEX (posting_date_company_index)`
  when `restrict_accounts` is set.
- **E1 root / unscoped path**: still uses ERPNext `set_gl_entries_by_account`.
- **Empty classification (semantic)**:
  - Party / dimension / unified-party builders skip empty keys before row build.
  - `paginate_summary_rows` excludes empty-classification presentation rows
    **before** totals and pagination.
  - Currency axis continues to skip blank currency keys; totals use the same
    exclusion.
  - Voucher axis already skips blank voucher_type/no.
- **UI**: Unified Parties tab removed from Account Explorer navigator
  (`ui_nav: 0`; backend APIs retained).
- Test harness: `require_site()` raises `unittest.SkipTest` for class-level skips.
- No OpeningEntryPolicy / Prepared Report / Redis / index / schema / GL posting
  engine changes.

## Explicitly out of scope

- Initial UI toolbar-before-metadata redesign
- Lazy `discover_company_currencies`
- Account Unclassified taxonomy cleanup (still shown when it has activity)

## Performance (restore-espad.localhost, FY 1405)

| Case | Before (legacy FORCE INDEX on scoped E1) | After v4.6.2 | Notes |
|------|------------------------------------------|--------------|-------|
| A Root E1 | ~7679.9 ms | ~7679.9 ms | Unchanged path |
| B Group navigator E1 | ~2858.8 ms | **~24.6 ms** | &lt;100 ms target |
| C Leaf navigator E1 | ~2892.6 ms | **~17.6 ms** | &lt;100 ms target |
| D Filter-panel leaf E3 | ~38.1 ms | ~38.1 ms | Unchanged |

Accounting diff (legacy force-index vs v4.6.2) for A/B/C: **0**.

Empty-classification exclusion adds no per-row SQL and no extra full GL scans
(filter is in-memory on already-aggregated keys / page rows).

## Empty classification — before / after totals example

Fixture: classified Customer movement **100** + blank-party movement **50**.

| | Before (include empty bucket) | After v4.6.2 |
|--|-------------------------------|--------------|
| Party rows | Customer + Unspecified | Customer only |
| Party axis total (scoped) | 150 | **100** |
| Empty / Unspecified row | present | **absent** |
| Pagination `total_rows` | includes empty | **excludes empty** |

Classified-row debit for the fixture customer remains **100** (diff = 0 vs
included classified data).

## Accounting correctness gates

- Scoped E1 before/after: **diff = 0**
- GF-01..GF-17 golden fixtures: **PASS**
- 24-cell opening axis matrix: **PASS**
- Analytical filter parity: **PASS** (party/dimension baselines exclude empty buckets)
- Voucher parity: **PASS**
- PCV/ACB integration: **PASS**
- Production opening-policy integration: **PASS**
- Empty classification unit + API tests: **PASS**
- Playwright scenarios 1–6: **PASS**

## Version

`erpnext_extensions` **4.6.1 → 4.6.2**

## Commit recommendation

Do not commit until review of this report. Stage when ready:

- `opening_balance.py` (omit scoped FORCE INDEX)
- `pagination.py` / party / dimension / unified / currency summaries
- `account_explorer.js` + metadata `ui_nav`
- empty-classification + E1 tests, Playwright suite, `RELEASE_4_6_2.md`
- version bump
