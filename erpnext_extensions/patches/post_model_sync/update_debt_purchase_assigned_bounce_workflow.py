# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Migrate Assigned DP desk transitions: Bounce only (remove Return path).

Sites that already ran ``ensure_debt_purchase_pdc_workflow`` still have
Assigned → Returned; re-apply the corrected transition set.
"""

from __future__ import annotations

from erpnext_extensions.patches.post_model_sync.ensure_debt_purchase_pdc_workflow import execute as _sync


def execute():
	_sync()
