# ERPNext Extensions v4.5.0

Account Explorer opening-policy correctness and voucher-axis performance hardening.

## Account Explorer

- **Opening Entry Policy** — formal OFF/ON handling for opening-flagged GL rows across Account Explorer axes.
- **Include Opening Entries OFF** — opening-flagged amounts stay out of period turnover; opening balances follow policy-adjusted Trial Balance / scoped GL paths.
- **Include Opening Entries ON** — opening-flagged rows in the analysis window contribute to turnover as intended; opening vs turnover buckets stay distinct.
- **E1 / E2 / E3 production query paths** — Trial Balance + policy delta (E1), gap-window supplement when PCV/ACB applies (E2), and scoped GL fallback (E3) for advanced filters / ACB correctness cases.
- **PCV / Account Closing Balance** — correctness fallbacks and golden fixtures (GF-13..GF-17) so historical closing and gap opening behave consistently.
- **Cross-axis consistency** — account, party, dimension, currency, and voucher axes share the same opening-policy semantics.
- **Direct GL parity** — Account Explorer totals match direct `tabGL Entry` baselines within max abs difference **0**.

## Performance

- Voucher-axis **double aggregation removed**.
- **SQL-level voucher pagination** with deterministic sort keys.
- Full Python materialization of all voucher groups **removed** (high-cardinality OOM path eliminated).
- **Bounded query count** for interactive voucher pages (page-only enrichment).
- **Export scaling** — single grouped materialization / streaming-oriented path instead of repeated summary-builder aggregation.
- Large voucher sets keep peak process memory well under the Phase 4A contract (under 150 MB at ~500k groups).

Reference interactive voucher budgets (host-specific; not sub-second SLAs):

| Voucher groups | P95 budget |
|---|---|
| ~10k | ≤ 1.5s |
| ~50k | ≤ 3.0s |
| ~100k | ≤ 4.5s |
| ~250k | ≤ 8.5s |
| ~500k | ≤ 15s |

## Known limitations (performance only)

Accounting correctness for Opening Entry Policy and Account Explorer axes is complete for this release.

- Very high voucher cardinality remains bounded by MariaDB `GROUP BY` cost over matching GL rows.
- High-scale pre-aggregation / async prepared reporting is **deferred** to a future release.
- **No Redis** and **no additional GL indexes** are introduced in 4.5.0.

## Deferred

Very-high-scale voucher pre-aggregation, enriched full-export streaming architecture, and any production GL index strategy are out of scope for 4.5.0.
