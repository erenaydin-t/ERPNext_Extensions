# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Desk boot extensions (``boot_session`` hook).

Exposes workflow facts to the browser so client scripts can align with server state without relying
on ``locals`` being pre-populated (see Payment Request toolbar / ``has_workflow``).
"""

from __future__ import annotations

import frappe

from erpnext_extensions.cheque_management.pdc_payment_request_eligibility import (
	get_payment_request_settlement_eligible_workflow_states,
)


def extend_bootinfo(bootinfo) -> None:
	"""Desk flags for Payment Request toolbar / settlement UI (see ``public/js/pdc_settlement_summary.js``)."""
	bootinfo.pdc_payment_request_has_active_workflow = bool(
		frappe.db.get_value(
			"Workflow",
			{"document_type": "Payment Request", "is_active": 1},
			"name",
		)
	)
	states = get_payment_request_settlement_eligible_workflow_states()
	# ``None`` = no Workflow on PR → client falls back to ``docstatus == 1`` (classic ERPNext).
	bootinfo.pdc_pr_settlement_eligible_workflow_states = list(states) if states is not None else None
