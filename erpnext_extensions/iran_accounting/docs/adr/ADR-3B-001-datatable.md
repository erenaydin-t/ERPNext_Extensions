# ADR-3B-001: Account Explorer Grid — Frappe DataTable

## Status

Accepted (Wave 3B)

## Context

Account Explorer currently renders summary and GL detail rows with a custom HTML `<table class="ae-grid">`. This duplicates capabilities already provided by Frappe DataTable (sorting, resize, reorder, sticky columns, selection, keyboard navigation, clipboard, filtering, scrolling) and diverges from native ERPNext/Frappe UX patterns used in Query Report and Report View.

## Decision

Use **Frappe DataTable** (`frappe-datatable`) for all grid rendering in Account Explorer.

Do **not** continue investing in the custom HTML table. Do **not** adopt third-party grid libraries.

All DataTable access must go through a single integration point:

```
Account Explorer → AE DataTable Adapter → Frappe DataTable
```

No other module may instantiate or manipulate DataTable directly. If Frappe changes DataTable in a future version, only the adapter should require modification.

Native DataTable capabilities must be used whenever available. Build adapters only where Account Explorer requires accounting-specific behavior (e.g. drill-down links, dimension compact cells, voucher row actions).

## Consequences

### Positive

- Consistent desk UX with Query Report / Report View
- Reduced maintenance of custom grid code
- Built-in accessibility and keyboard behavior
- Single upgrade path when Frappe DataTable evolves

### Negative

- Migration effort from custom grid (Wave 3B-1)
- Some accounting-specific cell renderers require adapter hooks

## Implementation

- **3B-0**: Create `ae_datatable_adapter.js` skeleton (no grid migration)
- **3B-1**: Replace custom HTML grid with adapter-backed DataTable
- Feature flag `account_explorer_datatable_enabled` may gate rollout for rollback

## References

- `frappe/public/js/frappe/views/reports/query_report.js`
- `frappe/public/js/frappe/views/reports/report_view.js`
- `frappe/node_modules/frappe-datatable/`
