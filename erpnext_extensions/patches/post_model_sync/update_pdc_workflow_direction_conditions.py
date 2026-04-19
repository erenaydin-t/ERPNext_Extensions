# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Apply ``cheque_direction`` conditions to **PDC Workflow** transitions (Desk Actions menu).

Mirrors ``erpnext_extensions/fixtures/workflow.json`` so existing sites pick up direction-aware
transitions without relying on fixture re-import alone.
"""

from __future__ import annotations

import frappe

# workflow_builder_id -> condition Python (None = no filter, both directions)
_COND: dict[str, str | None] = {
	"pdc-tr-00": None,
	"pdc-tr-02": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-03": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-04": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-05": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-06": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-07": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-08": None,
	"pdc-tr-09": "doc.get('cheque_direction') == 'Payable'",
	"pdc-tr-10": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-11": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-12": "doc.get('cheque_direction') == 'Payable'",
	"pdc-tr-13": "doc.get('cheque_direction') == 'Payable'",
	"pdc-tr-14": "doc.get('cheque_direction') == 'Payable'",
	"pdc-tr-15": "doc.get('cheque_direction') == 'Payable'",
	"pdc-tr-16": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-17": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-18": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-19": None,
	"pdc-tr-20": None,
	"pdc-tr-21": "doc.get('cheque_direction') == 'Receivable'",
	"pdc-tr-22": "doc.get('cheque_direction') == 'Receivable'",
}


def execute():
	if not frappe.db.exists("Workflow", "PDC Workflow"):
		return
	wf = frappe.get_doc("Workflow", "PDC Workflow")
	changed = False
	for bid, new_c in _COND.items():
		for row in wf.transitions:
			if (getattr(row, "workflow_builder_id", None) or "").strip() != bid:
				continue
			if (row.condition or None) != (new_c or None):
				row.condition = new_c
				changed = True
			break
	if changed:
		wf.flags.ignore_permissions = True
		wf.save()
		frappe.db.commit()
