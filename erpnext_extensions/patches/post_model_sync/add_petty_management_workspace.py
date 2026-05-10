from __future__ import annotations

import json

import frappe
from frappe.desk.doctype.workspace_sidebar.workspace_sidebar import (
	create_workspace_sidebar_for_workspaces,
)


MODULE_NAME = "Petty Management"
APP_NAME = "erpnext_extensions"

# Editor.js blocks for Desk workspace main area; card_name must match Card Break labels in links.
_PETTY_WORKSPACE_CONTENT = [
	{
		"id": "pm_ws_hdr",
		"type": "header",
		"data": {"text": '<span class="h4"><b>Petty Management</b></span>', "col": 12},
	},
	{"id": "pm_ws_setup", "type": "card", "data": {"card_name": "Setup", "col": 4}},
	{"id": "pm_ws_txn", "type": "card", "data": {"card_name": "Transactions", "col": 4}},
	{"id": "pm_ws_rpt", "type": "card", "data": {"card_name": "Reports", "col": 4}},
]


def _petty_workspace_content_json() -> str:
	return json.dumps(_PETTY_WORKSPACE_CONTENT, separators=(",", ":"))


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


def _ensure_workspace_sidebar():
	"""Persist Workspace Sidebar so boot.get_sidebar_items exposes petty-management in workspace_sidebar_item."""
	try:
		create_workspace_sidebar_for_workspaces()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "petty_management_workspace_sidebar")


def _ensure_desktop_icon():
	"""Standard Desktop Icon rows are only created at site install; add one so /desk home shows the module tile."""
	if not frappe.db.exists("Workspace", MODULE_NAME):
		return

	meta_di = frappe.get_meta("Desktop Icon")
	label = MODULE_NAME

	if frappe.db.exists("Desktop Icon", label):
		icon = frappe.get_doc("Desktop Icon", label)
	else:
		icon = frappe.new_doc("Desktop Icon")
		icon.label = label

	icon.icon_type = "Link"
	icon.link_type = "Workspace Sidebar"
	icon.link_to = MODULE_NAME
	icon.standard = 1
	icon.hidden = 0
	if meta_di.has_field("icon"):
		icon.icon = "wallet"
	if meta_di.has_field("app"):
		icon.app = APP_NAME
	if meta_di.has_field("idx") and not icon.idx:
		icon.idx = 100

	icon.save(ignore_permissions=True)


def _clear_desk_caches():
	frappe.cache.delete_key("desktop_icons")
	frappe.cache.delete_key("bootinfo")


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
	if meta.has_field("sequence_id") and not ws.get("sequence_id"):
		ws.sequence_id = 90
	if meta.has_field("content"):
		ws.content = _petty_workspace_content_json()

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
	_ensure_workspace_sidebar()
	_ensure_desktop_icon()
	_clear_desk_caches()
	frappe.db.commit()
