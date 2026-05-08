"""Refresh Payments sidebar Cheque Management groups.

This is a forward-only patch that re-applies the latest grouping logic for the
Payments `Workspace Sidebar` after the original patch was already recorded as
executed on existing sites.
"""

from __future__ import annotations


def execute():
	# Delegate to the current implementation (idempotent).
	from erpnext_extensions.patches.post_model_sync.update_payments_module_sidebar_add_pdc_items import (
		execute as _apply,
	)

	_apply()

