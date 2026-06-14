from __future__ import annotations

import json

import frappe
from frappe.desk.doctype.workspace_sidebar.workspace_sidebar import (
	create_workspace_sidebar_for_workspaces,
)

from erpnext_extensions.petty_management.desk_workspace_config import (
	SIDEBAR_HOME_ICON,
	SIDEBAR_LINK_ICONS,
	SIDEBAR_SECTION_ICONS,
	WORKSPACE_CARD_ICONS,
	WORKSPACE_REPORT_LINKS,
	WORKSPACE_SETUP_LINKS,
	WORKSPACE_SHORTCUTS,
	WORKSPACE_TRANSACTION_LINKS,
)


MODULE_NAME = "Petty Management"
APP_NAME = "erpnext_extensions"

# Editor.js blocks for Desk workspace main area; card_name must match Card Break labels in links.
_PETTY_WORKSPACE_CONTENT = [
	{
		"id": "pm_ws_hdr",
		"type": "paragraph",
		"data": {
			"text": "<b>Petty Management</b> — funding, clearance, and reporting.",
			"col": 12,
		},
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
	"""Ensure generic Workspace Sidebar rows exist (v16 also needs explicit items — see _sync_petty_workspace_sidebar)."""
	try:
		create_workspace_sidebar_for_workspaces()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "petty_management_workspace_sidebar")


def _sync_petty_workspace_sidebar():
	"""Frappe v16: boot.get_sidebar_items reads Workspace Sidebar `items`; factory only adds Home + shortcuts.

	Rebuild Petty Management sidebar with Home, grouped sections, and workspace links so /app/petty-management
	left navigation is usable (center cards unchanged).
	"""
	if not frappe.db.exists("Workspace", MODULE_NAME):
		return
	meta_sb = frappe.get_meta("Workspace Sidebar")
	if not meta_sb:
		return

	if frappe.db.exists("Workspace Sidebar", MODULE_NAME):
		sb = frappe.get_doc("Workspace Sidebar", MODULE_NAME)
	else:
		sb = frappe.new_doc("Workspace Sidebar")
		sb.title = MODULE_NAME

	if meta_sb.has_field("header_icon"):
		sb.header_icon = "wallet"
	if meta_sb.has_field("module"):
		sb.module = MODULE_NAME
	if meta_sb.has_field("standard"):
		sb.standard = 1
	if meta_sb.has_field("app"):
		sb.app = APP_NAME
	if meta_sb.has_field("for_user"):
		sb.for_user = None

	sb.items = []

	counter = 0

	def next_idx() -> int:
		nonlocal counter
		i = counter
		counter += 1
		return i

	def add_item(row: dict) -> None:
		row["idx"] = next_idx()
		sb.append("items", row)

	def add_section(label: str) -> None:
		row = {
			"label": label,
			"type": "Section Break",
			"collapsible": 1,
			"keep_closed": 0,
		}
		if SIDEBAR_SECTION_ICONS.get(label):
			row["icon"] = SIDEBAR_SECTION_ICONS[label]
		add_item(row)

	def add_link(label: str, link_type: str, link_to: str, **extra) -> None:
		row = {
			"label": label,
			"type": "Link",
			"link_type": link_type,
			"link_to": link_to,
			"child": 1,
			"icon": SIDEBAR_LINK_ICONS.get(label) or extra.pop("icon", None),
		}
		row.update(extra)
		add_item(row)

	add_item(
		{
			"label": "Home",
			"type": "Link",
			"link_type": "Workspace",
			"link_to": MODULE_NAME,
			"icon": SIDEBAR_HOME_ICON,
		}
	)

	add_section("Setup")
	for label, link_type, link_to, _extra in WORKSPACE_SETUP_LINKS:
		add_link(label, link_type, link_to)

	add_section("Transactions")
	for label, link_type, link_to, _extra in WORKSPACE_TRANSACTION_LINKS:
		add_link(label, link_type, link_to)

	add_section("Reports")
	for label, link_type, link_to, extra in WORKSPACE_REPORT_LINKS:
		add_link(label, link_type, link_to, **extra)

	sb.save(ignore_permissions=True)


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


def _ensure_workspace_shortcuts(ws) -> bool:
	meta = frappe.get_meta("Workspace")
	changed = False
	if not meta.has_field("shortcuts"):
		return changed
	existing = {(r.link_to or ""): r for r in (ws.get("shortcuts") or [])}
	for label, link_to, link_type in WORKSPACE_SHORTCUTS:
		if link_to in existing:
			continue
		ws.append(
			"shortcuts",
			{
				"type": link_type,
				"label": label,
				"link_to": link_to,
				"doc_view": "List",
			},
		)
		changed = True
	return changed


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

	_append_link(
		ws,
		{
			"type": "Card Break",
			"label": "Setup",
			"icon": WORKSPACE_CARD_ICONS.get("Setup", "settings"),
		},
	)
	for label, link_type, link_to, extra in WORKSPACE_SETUP_LINKS:
		_append_link(
			ws,
			{"type": "Link", "label": label, "link_type": link_type, "link_to": link_to, **extra},
		)

	_append_link(
		ws,
		{
			"type": "Card Break",
			"label": "Transactions",
			"icon": WORKSPACE_CARD_ICONS.get("Transactions", "repeat"),
		},
	)
	for label, link_type, link_to, extra in WORKSPACE_TRANSACTION_LINKS:
		_append_link(
			ws,
			{"type": "Link", "label": label, "link_type": link_type, "link_to": link_to, **extra},
		)

	_append_link(
		ws,
		{
			"type": "Card Break",
			"label": "Reports",
			"icon": WORKSPACE_CARD_ICONS.get("Reports", "bar-chart-2"),
		},
	)
	for label, link_type, link_to, extra in WORKSPACE_REPORT_LINKS:
		_append_link(
			ws,
			{"type": "Link", "label": label, "link_type": link_type, "link_to": link_to, **extra},
		)

	ws.save(ignore_permissions=True)
	_ensure_workspace_shortcuts(ws)
	_ensure_workspace_sidebar()
	_sync_petty_workspace_sidebar()
	_ensure_desktop_icon()
	_clear_desk_caches()
	frappe.db.commit()
