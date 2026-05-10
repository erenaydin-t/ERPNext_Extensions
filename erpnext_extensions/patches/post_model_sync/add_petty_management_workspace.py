from __future__ import annotations

import frappe


MODULE_NAME = "Petty Management"
APP_NAME = "erpnext_extensions"


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


def _ensure_module_def():
	"""Create or update Module Def so it appears under erpnext_extensions on Desk."""
	if frappe.db.exists("Module Def", MODULE_NAME):
		doc = frappe.get_doc("Module Def", MODULE_NAME)
		changed = False
		if doc.app_name != APP_NAME:
			doc.app_name = APP_NAME
			changed = True
		if doc.custom:
			doc.custom = 0
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
		return

	frappe.get_doc(
		{
			"doctype": "Module Def",
			"module_name": MODULE_NAME,
			"app_name": APP_NAME,
			"custom": 0,
		}
	).insert(ignore_permissions=True)


def execute():
	_ensure_module_def()

	meta = frappe.get_meta("Workspace")

	if frappe.db.exists("Workspace", MODULE_NAME):
		ws = frappe.get_doc("Workspace", MODULE_NAME)
	else:
		ws = frappe.new_doc("Workspace")
		ws.label = MODULE_NAME

	if meta.has_field("title"):
		ws.title = MODULE_NAME
	if meta.has_field("label"):
		ws.label = MODULE_NAME
	if meta.has_field("module"):
		ws.module = MODULE_NAME
	if meta.has_field("type"):
		ws.type = "Workspace"
	if meta.has_field("icon"):
		ws.icon = "wallet"
	for fn, val in (("public", 1), ("is_hidden", 0)):
		if meta.has_field(fn):
			ws.set(fn, val)
	if meta.has_field("for_user"):
		ws.set("for_user", "")
	if meta.has_field("content"):
		ws.content = "[]"

	# Rebuild links so card order stays correct on every migrate (Setup → Transactions → Reports).
	if meta.has_field("links"):
		ws.links = []

	_append_link(ws, {"type": "Card Break", "label": "Setup", "icon": ""})
	for label, link_to in (
		("PM Settings", "PM Settings"),
		("PM Holder", "PM Holder"),
	):
		_append_link(ws, {"type": "Link", "label": label, "link_type": "DocType", "link_to": link_to})

	_append_link(ws, {"type": "Card Break", "label": "Transactions", "icon": ""})
	for label, link_to, ltype in (
		("PM Request", "PM Request", "DocType"),
		("PM Clearance", "PM Clearance", "DocType"),
		("Purchase Invoice", "Purchase Invoice", "DocType"),
		("Payment Entry", "Payment Entry", "DocType"),
		("Journal Entry", "Journal Entry", "DocType"),
	):
		_append_link(ws, {"type": "Link", "label": label, "link_type": ltype, "link_to": link_to})

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

	ws.save(ignore_permissions=True)
	frappe.db.commit()
