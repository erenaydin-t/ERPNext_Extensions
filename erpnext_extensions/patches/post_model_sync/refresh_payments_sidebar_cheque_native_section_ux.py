"""Re-apply Payments sidebar cheque groups with native section/link metadata (child, indent, icons).

Sites that already ran `refresh_payments_module_sidebar_cheque_groups` need this forward patch
to pick up UX fixes in `update_payments_module_sidebar_add_pdc_items.execute`.
"""

from __future__ import annotations


def execute():
	from erpnext_extensions.patches.post_model_sync.update_payments_module_sidebar_add_pdc_items import (
		execute as _apply,
	)

	_apply()
