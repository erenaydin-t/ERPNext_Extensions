# ADR-3B-002: Workspace URL State and User Settings

## Status

Accepted (Wave 3B)

## Context

Account Explorer workspace state (document scope, analysis axis, filters, presentation) should be shareable via URL so users can bookmark or send links to a specific analytical view. Serialized state can exceed practical browser URL length limits when many filters or dimension values are active.

## Decision

Persist workspace state using a layered approach:

1. **URL query parameters** — primary mechanism for shareable, restorable workspace state
2. **`frappe.model.user_settings`** — persistent user preferences (last view, column layout, sort order)
3. **Compact token fallback** — when serialized state exceeds a practical URL length threshold, store full state in User Settings and expose a short token in the URL

Do **not** use `localStorage` for persistent preferences except as a temporary fallback when User Settings is unavailable.

Do **not** generate excessively long URLs. Target maximum serialized URL payload: ~1800 characters (conservative browser limit).

## State domains

| Domain | URL | User Settings |
|--------|-----|---------------|
| document_scope | Yes | Last-used defaults |
| analysis_context | Yes | Last axis / drill context |
| presentation | Partial | Column visibility, sort, page size |
| selection | No | No |
| navigation | Partial (breadcrumbs) | No |

## Consequences

### Positive

- Shareable analytical views
- Preferences survive browser sessions
- Graceful degradation for complex filter sets

### Negative

- Serialization/deserialization logic must stay in sync with `QuerySpec` / `DocumentScope` / `AnalysisContext` schemas
- Token indirection adds one server round-trip on restore

## Implementation

- **3B-0**: `explorer_workspace_state.js` scaffold (serialize/deserialize API, length check, token placeholder)
- **3B-2**: User Settings integration for presentation and last workspace
- **3B-5**: Full URL restore on page load and copy-link UX

## References

- `frappe/public/js/frappe/model/user_settings.js`
- `frappe/public/js/frappe/views/reports/query_report.js` (URL filters pattern)
