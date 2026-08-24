# ERPNext Extensions v4.6.0

Account Explorer prepared reporting and performance hardening for heavy Account / Voucher workloads.

## Prepared Report architecture

- **Query fingerprinting** — stable fingerprints for Account Explorer specs (pagination ignored for artifact identity).
- **Accounting revision** — per-company revision counter bumped when GL / closing / dimension metadata changes, so prepared artifacts invalidate correctly.
- **Prepared Result DocType** — stores Queued → Started → Completed / Error / Stale lifecycle with attached result payloads.
- **Background prepare jobs** — heavy queries enqueue preparation; UI polls until ready, then renders from the prepared artifact.
- **Hit path** — identical fingerprints with a matching revision serve prepared results immediately (no full recompute).

## Heavy Account / Voucher handling

- Large Account and Voucher axis loads use the prepared path when live compute would stall the interactive request.
- Voucher / account scalability hardening continues the 4.5.x pagination and bounded enrichment model; prepared artifacts reduce repeated heavy recomputation for the same filter set.

## Loading UX

- Generation-owned loading ownership so stale responses cannot leave a stuck banner.
- Loading banner clears immediately after successful paint (rows + totals), including prepared miss → prepare → render.
- Rapid Apply / Refresh: older in-flight requests cannot overwrite newer request UI state.
- Financial amount columns use a consistent wide, end-aligned, nowrap layout.

## Data correctness validation

- Post-load UI validation compares visible rows / totals against the backend response.
- Remount / recovery paths when the API returns rows but the grid paint is empty.
- Playwright A–F correctness gate covers live load, prepared miss/hit, refresh, rapid Apply, voucher, account, and currency dual-display.

## Currency axis dual display

- Numeric cells on all Account Explorer axes show **numbers only** (no `IRR` / `ریال` suffix). Currency unit is in column headers, the Currency field, and the totals badge.
- Currency axis rows show **native (transaction/account) amounts** next to **company-currency equivalents**.
- Currency axis **totals always aggregate in company currency** and never sum mixed native currencies together.

## Party enrichment and request cache

- Batch party display-title / identifier enrichment replaces per-row resolver chatter.
- Request-level caching for enabled party sources and related config lookups within a single request.

## Schema / ops notes

- New DocTypes (synced via `bench migrate`, **no** `patches.txt` entries and **no** new GL indexes):
  - `Account Explorer Prepared Result`
  - `Account Explorer Accounting Revision`
- Permissions: System Manager (read/write), Accounts User (read).
- No GL posting behavior changes in this release.

## Explicitly not claimed

- Universal sub-3-second performance for all companies / axes
- Redis caching layer
- New database indexes on GL
- Large-scale pre-aggregation

## Deferred

- Large-scale pre-aggregation
- Async export collector architecture
- Future accounting snapshot architecture
