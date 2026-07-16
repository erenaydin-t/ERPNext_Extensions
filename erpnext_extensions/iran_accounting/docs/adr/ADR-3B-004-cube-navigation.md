# ADR-3B-004: Cube Navigation Model

## Status

Accepted (Wave 3B-3 Cube Navigation Model — approved for implementation)

## Context

Account Explorer previously behaved as an axis-centric navigator: double-click drills wrote selections into `analysis_context.*_scope` and/or breadcrumb chips, while `switch_axis()` cleared breadcrumbs and partially mutated scopes. Analytical restrictions were sometimes invisible (Filter Summary stub, badge based only on DocumentScope) even when SQL still applied them via `apply_analysis_scope_filters`.

Account Explorer must behave as an OLAP-style analytical cube where every analytical entity (Account, Party, Unified Party, Voucher, Currency, every Accounting Dimension, future entities) can act as Axis, Filter, or Drill Target without entity-specific hardcoding.

## Decision

Separate four concerns permanently:

| Concern | Responsibility | Defines |
|---------|----------------|---------|
| **Axis** | Presentation / summary builder | `GROUP BY` |
| **Analysis Filters** | Typed analytical restrictions with explicit lifetime | `WHERE` |
| **Drill Graph** | Intent → edge → policy transitions | Navigation |
| **Breadcrumb / Navigation** | History of “where am I?” | Path UI only |

### ExplorerStore shape

```
document_scope      — framing filters (company, dates, FY, finance book, document options)
analysis_filters    — single source of truth for analytical WHERE
                      each entry carries: key, value, origin, lifetime, removable
analysis_context    — current axis, level, detail_mode, pagination
presentation        — grid prefs (columns, density, number format; User Settings)
navigation          — breadcrumb / history graph walk (not filter storage)
selection           — UI row selection / multi-select (compare later)
loading             — request flags
```

### QuerySpec conceptual mapping (no SQL redesign required)

```
WHERE   ← document_scope ∪ analysis_filters (active by lifetime rules)
GROUP BY ← current axis (summary builder)
ORDER BY ← presentation / analysis_context sort
```

Client maps `analysis_filters` into the existing payload fields that `gle_filters.apply_*` already understands (or a thin additive `analysis_filters` bag mirrored into current scopes during transition). Server builders continue to choose GROUP BY from `view_axis` (+ dimension_type when axis is dimension).

---

### Analytical Filter Lifetime

Every Analysis Filter **must** declare an explicit lifetime. Lifetime is data on the filter entry — never inferred from UI gestures, breadcrumb depth, or axis identity.

| Lifetime | Behavior |
|----------|----------|
| `session` | Persists across axis changes and navigation until the user removes it (or an explicit clear-filters / document reset). Default for most user-applied analytical filters (Facility, Party, Currency, …). |
| `drill` | Bound to a navigation path segment. Removed automatically when leaving that drill path (graph walk back / jump that exits the binding). Used when a filter exists only to keep an intermediate drill coherent. |
| `temporary` | Applies only to the **next** transition (one edge consumption), then discarded. Used for transient hand-offs (e.g. open-compare payload, one-shot drill-through seed). |

```
analysis_filter_entry = {
  key,           // account | party | voucher | currency | dimensions.<field> | …
  value,
  origin,        // drill_graph | filters_panel | url_hydrate | saved_view | …
  lifetime,      // session | drill | temporary
  removable,     // bool — chip UX
  bound_to,      // optional: navigation node / path id when lifetime === "drill"
}
```

Future features (bookmarks, compare, multi-select) **must** set lifetime explicitly when creating filters. Controllers must not guess.

---

### User Intent

Navigation is driven by **user intent**, not by UI gestures.

Gestures (double-click, Enter, toolbar, context menu, URL hydrate, dashboard drill-through) are translated by the controller into one of:

| Intent | Meaning |
|--------|---------|
| `filter` | Apply / replace / append an Analysis Filter per edge policy |
| `navigate` | Change axis and/or analytic level (GROUP BY / presentation + navigation history) |
| `detail` | Open detail mode (e.g. GL Detail) while resolving filter policy |
| `open` | Leave the explorer surface (source document, linked form) |
| `compare` | Future: multi-selection / side-by-side analysis |

```
UI gesture  →  Intent  →  Drill Graph resolve(node, intent, row)  →  Actions
```

Double-click is only one gesture that may map to `filter` or `navigate` depending on graph defaults for the current node. No entity-specific gesture handlers in the controller.

---

### Drill Graph Policy

Every edge is data-driven:

```
edge = {
  from_node,     // e.g. SubsidiaryLedger | DimensionValue | Party | Voucher
  intent,        // filter | navigate | detail | open | compare
  edge_type,     // apply_filter | change_axis | advance_level | open_detail | open_source | …
  target,        // node / axis / surface to arrive at (nullable for filter-only)
  policy,        // filter & navigation side-effect contract (see below)
}
```

#### Policies (initial set; extensible via registry)

| Policy | Effect on `analysis_filters` / navigation |
|--------|-------------------------------------------|
| `append_filter` | Add/merge filter for the selected entity; keep existing filters; lifetime from edge (usually `session`) |
| `replace_filter` | Replace the same key (e.g. replace `account`) |
| `replace_dimension` | Replace only `dimensions.<field>` for that dimension type; other filters preserved |
| `keep_filters` | Change presentation/detail without mutating filters |
| `clear_drill_filters` | Drop filters with `lifetime === "drill"` bound to the path being left |
| `consume_temporary` | Apply then remove `lifetime === "temporary"` filters after the transition |

Examples:

```
Account (Subsidiary) + intent:navigate → Voucher
  edge_type: change_axis
  policy: append_filter   // account becomes session filter; axis → Voucher

DimensionValue + intent:filter → (same axis)
  edge_type: apply_filter
  policy: replace_dimension

Voucher + intent:detail → GLDetail
  edge_type: open_detail
  policy: keep_filters

CurrencyValue + intent:filter → (same axis)
  edge_type: apply_filter
  policy: replace_filter (currency)
```

Dimensions are **not** special-cased in controller code; they use the same edge/policy mechanism as Party/Currency/Account.

---

### Filter Summary

Filter Summary is the user-visible truth. It must **visually group**:

1. **Document Scope** — company, dates, FY, finance book, panel-level document options  
2. **Analysis Filters** — every active analytical WHERE (with origin + lifetime in tooltip)  
3. **Presentation** — current axis / level / detail mode (read-only informational chips; not WHERE)

Users must always answer:

- **WHAT** is filtering (Document Scope + Analysis Filters)  
- **WHY** (origin + lifetime + which edge/action created it)  

Breadcrumb answers only “Where am I?” and must never be the sole owner of a filter.

Chip contract: `label`, `value`, `group`, `origin`, `lifetime`, `removable`.

---

### Axis lifecycle

Changing axis updates `analysis_context.view_axis` (and related presentation fields) only.  
`session` Analysis Filters are preserved.  
`drill` filters follow path-binding rules.  
`temporary` filters are not axis-owned and expire per policy.

### Frappe v16 constraints

- Remain a normal Desk Page (`account-explorer`)
- Keep ExplorerStore + EventBus (existing Wave 3B core); do not introduce Redux/Vuex/etc.
- Prefer extending `ExplorerPluginRegistry` / a new `core/explorer_drill_graph.js` included from the page
- Preserve DataTable adapter boundary, User Settings Grid section, Workspace URL serialization of filters/axis/lifetime
- Do not bypass permissions; QuerySpec APIs remain authoritative

### Future compatibility (no second navigation model)

The Cube Navigation Model must support without redesign:

- Pivot · Charts · Dashboard widgets · Drill-through  
- Bookmarks · Public links · Saved Views  
- Compare Mode · Multi-selection analysis  
- Future analytical entities (register nodes, intents, edges, policies)

Intents `compare` / multi-select and features like pivot reuse `analysis_filters` + axis + presentation; they do not invent parallel filter bags.

### Compatibility strategy

- Client `analysis_filters` is authoritative for analytical WHERE.
- `build_legacy_scope_payload_from_analysis_filters()` projects into existing `*_scope` / document currency / `accounting_dimensions` for current QuerySpec APIs (no SQL redesign).
- Workspace URL `ae_v=2` serializes `af` (analysis filters). `ae_v=1` remains readable and migrates to session filters (`origin: legacy_url`).
- Saved Views v1 continue storing legacy scopes; hydrate maps them into `analysis_filters` (`origin: saved_view`, `lifetime: session`) without DocType schema changes.

## Consequences

### Positive

- Cross-axis navigation without silent filter loss
- Explicit filter lifetime → no inferred state
- Policy-driven edges → no controller hardcoding per entity
- Intent layer → gestures stay interchangeable
- Visible analytical causality (grouped Filter Summary)
- Stable foundation for Saved Views, public links, pivot/charts/compare

### Negative

- Migration of existing URL/saved-view scope fields into `analysis_filters` (+ lifetime defaults = `session`)
- Behavioral change for users who relied on invisible leftover filters or breadcrumb-as-filter
- Second-click Dimension→Voucher becomes an explicit `navigate` intent / edge, not an implied gesture

## Implementation plan (after approval)

1. Land this ADR as Accepted  
2. Introduce `analysis_filters` entries with `lifetime` / `origin` in store + compat shim to current scopes  
3. Implement grouped Filter Summary (Document Scope / Analysis Filters / Presentation)  
4. Introduce Drill Graph module (nodes, intents, edges, policies); migrate `drill_row` onto intent resolve  
5. Make `switch_axis` presentation-only (`keep_filters` + `session` preservation)  
6. Update Workspace URL serialize/hydrate for filters including lifetime  
7. Tests: lifetime rules; Filter Summary groups; intent→policy edges; axis switch preserves `session`; no QuerySpec rewrite  

## References

- ADR-3B-001 DataTable  
- ADR-3B-002 Workspace URL State  
- ADR-3B-003 Page Lifecycle  
- `explorer_store.js`, `explorer_plugins.js`, `gle_filters.py`, `schemas.py`
