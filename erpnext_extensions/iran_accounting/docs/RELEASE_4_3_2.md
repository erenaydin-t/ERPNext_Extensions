# Copyright (c) 2026, ERPNext Extensions contributors
"""RELEASE 4.3.2 — Guarantee List View & Account Explorer export fixes.

## Fixed

- Guarantee Document List View no longer initializes with an invalid empty
  ``ID Equals`` filter (Filter popover empty-name apply sanitization).
- Company is removed from the default Guarantee Document list while remaining
  filterable (``in_list_view=0``, ``in_standard_filter=1`` + metadata patch).
- Party batch display no longer blocks first list paint (avoids stuck
  Refreshing while resolving party labels).
- Account Explorer XLSX export correctly handles immediate and background exports.
- Fixed export threshold fallback that could incorrectly queue small datasets
  when ``export_background_threshold`` was stored as ``0``.
- Sync export actions pass ``force_sync`` so users are not navigated to raw
  queued API JSON responses.
- Guarantee List party/title formatters return escaped HTML so party titles
  containing parentheses do not break Frappe ``$(column_html)`` width measurement.

## Unchanged

- Guarantee Document custody semantics (Bank party, Issuing Bank, Held By,
  position summary, accounting isolation)
- Account Explorer analysis / permission model
- CSV export path (preserved; XLSX shares threshold rules)

## Version

``4.3.1`` → ``4.3.2``
"""
