# ADR-3B-003: Account Explorer Page Lifecycle

## Status

Accepted (Wave 3B)

## Context

Frappe desk pages can be loaded once and shown/hidden as users navigate. Query Report uses `$(wrapper).bind("show", ...)` to refresh when the page becomes visible again. Account Explorer currently initializes entirely in `on_page_load` with no `show` handler, which can leave stale data when returning to the page.

## Decision

Follow the **Query Report page lifecycle pattern**:

1. `on_page_load` — create page shell, instantiate controller, render initial UI
2. `$(wrapper).bind("show", ...)` — delegate to `controller.on_page_show()` when page becomes visible
3. `on_page_show` — soft refresh if metadata is loaded and explorer is enabled

Account Explorer must behave like a native Frappe desk page. Reuse existing Frappe lifecycle hooks before introducing custom page management.

## Consequences

### Positive

- Fresh data when user returns to Account Explorer
- Consistent with Query Report, List View, and other desk pages
- Enables lazy initialization patterns in future waves

### Negative

- Must guard against duplicate network requests on first show (constructor already loads)

## Implementation

- **3B-0**: Add `show` binding and `on_page_show()` with guarded soft refresh
- Subsequent waves wire workspace URL restore into `on_page_show` after metadata load (3B-5)

## References

- `frappe/public/js/frappe/views/reports/query_report.js` lines 25–27
