from __future__ import annotations

from erpnext_extensions.cheque_management.payments_sidebar import apply_payments_cheque_sidebar_groups


def execute():
	"""Post-migrate patch entrypoint; shared logic lives in ``payments_sidebar`` (also ``after_migrate``)."""
	apply_payments_cheque_sidebar_groups()
