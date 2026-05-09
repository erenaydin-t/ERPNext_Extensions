"""Refresh Payments sidebar Cheque Management groups.

This is a forward-only patch that re-applies the latest grouping logic for the
Payments `Workspace Sidebar` after the original patch was already recorded as
executed on existing sites.

Note on patch evolution:
- This patch was the first refresh vehicle for already-migrated sites.
- It was later superseded by `refresh_payments_sidebar_cheque_native_section_ux.py`
  when the sidebar items were updated to use native section semantics (`child`, `indent`,
  section icons) to improve the UX.
- It intentionally remains in patch history for migration safety; do not remove/reorder
  without an explicit patch cleanup phase.
"""

from __future__ import annotations


def execute():
	# Delegate to the current implementation (idempotent).
	from erpnext_extensions.patches.post_model_sync.update_payments_module_sidebar_add_pdc_items import (
		execute as _apply,
	)

	_apply()

