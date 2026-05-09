from __future__ import annotations

import frappe


def _link_row_val(row, key: str):
	if row is None:
		return None
	if isinstance(row, dict):
		return row.get(key)
	return getattr(row, key, None)


def _append_link(ws, row: dict):
	meta = frappe.get_meta("Workspace")
	if not meta.has_field("links"):
		return
	for existing in ws.links or []:
		if (
			_link_row_val(existing, "type") == row.get("type")
			and (_link_row_val(existing, "label") or "") == (row.get("label") or "")
			and (_link_row_val(existing, "link_type") or "") == (row.get("link_type") or "")
			and (_link_row_val(existing, "link_to") or "") == (row.get("link_to") or "")
		):
			return
	ws.append("links", row)


def execute():
	meta = frappe.get_meta("Workspace")
	name = "Petty Management"
	if frappe.db.exists("Workspace", name):
		ws = frappe.get_doc("Workspace", name)
	else:
		ws = frappe.new_doc("Workspace")
		ws.name = name

	if meta.has_field("title"):
		ws.title = name
	if meta.has_field("label"):
		ws.label = name
	if meta.has_field("module"):
		ws.module = "Petty Management"
	for fn, val in (("public", 1), ("is_hidden", 0)):
		if meta.has_field(fn):
			ws.set(fn, val)
	if meta.has_field("content"):
		ws.content = "[]"

	# Link cards (sections via Card Break)
	_append_link(ws, {"type": "Card Break", "label": "Transactions", "icon": ""})
	for label, link_to, ltype in (
		("PM Request", "PM Request", "DocType"),
		("PM Clearance", "PM Clearance", "DocType"),
		("Payment Entry", "Payment Entry", "DocType"),
		("Journal Entry", "Journal Entry", "DocType"),
		("Purchase Invoice", "Purchase Invoice", "DocType"),
	):
		_append_link(ws, {"type": "Link", "label": label, "link_type": ltype, "link_to": link_to})

	_append_link(ws, {"type": "Card Break", "label": "Setup", "icon": ""})
	for label, link_to in (
		("PM Settings", "PM Settings"),
		("PM Expense Type", "PM Expense Type"),
		("PM Holder", "PM Holder"),
	):
		_append_link(
			ws, {"type": "Link", "label": label, "link_type": "DocType", "link_to": link_to}
		)

	_append_link(ws, {"type": "Card Break", "label": "Reports", "icon": ""})
	for label, link_to in (
		("PM Balance Report", "PM Balance Report"),
		("PM Ledger Report", "PM Ledger Report"),
		("PM Pending Clearance Report", "PM Pending Clearance Report"),
	):
		_append_link(
			ws,
			{
				"type": "Link",
				"label": label,
				"link_type": "Report",
				"link_to": link_to,
				"is_query_report": 1,
			},
		)

	if frappe.db.exists("Workspace", name):
		ws.save(ignore_permissions=True)
	else:
		ws.insert(ignore_permissions=True)
	frappe.db.commit()
