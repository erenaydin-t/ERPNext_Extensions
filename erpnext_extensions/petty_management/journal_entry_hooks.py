"""Journal Entry hooks for Petty Management settlement linkage."""

from __future__ import annotations

import frappe


def on_journal_entry_submit(doc, method=None):
	"""When a settlement JE is submitted, mark linked PM Clearance as Settled."""
	names = frappe.get_all(
		"PM Clearance",
		filters={"journal_entry": doc.name},
		pluck="name",
	)
	for cl_name in names:
		frappe.db.set_value("PM Clearance", cl_name, "status", "Settled", update_modified=False)
