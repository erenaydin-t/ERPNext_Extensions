from __future__ import annotations

import frappe


def _get_payments_sidebar():
	# Standard public module sidebar doc
	name = frappe.db.get_value("Workspace Sidebar", {"module": "Payments", "for_user": None}, "name")
	if name:
		return frappe.get_doc("Workspace Sidebar", name)

	# Fallback: some sites use title/name = module
	if frappe.db.exists("Workspace Sidebar", "Payments"):
		return frappe.get_doc("Workspace Sidebar", "Payments")

	return None


def _has_doctype_link(sidebar, doctype: str) -> bool:
	for it in (sidebar.get("items") or []):
		if (it.get("type") or "") == "Link" and (it.get("link_type") or "").lower() == "doctype":
			if (it.get("link_to") or "") == doctype:
				return True
	return False


def _append_doctype_link(sidebar, doctype: str, label: str | None = None):
	if _has_doctype_link(sidebar, doctype):
		return False

	sidebar.append(
		"items",
		{
			"label": label or doctype,
			"type": "Link",
			"link_type": "DocType",
			"link_to": doctype,
		},
	)
	return True


def execute():
	"""
	Task A (actual fix): add cheque doctypes to the Payments *module sidebar*.

	The left module sidebar is driven by `Workspace Sidebar` (per module), not by `Workspace`.
	This patch updates the existing Payments sidebar without touching ERPNext core files.
	"""
	sidebar = _get_payments_sidebar()
	if not sidebar:
		# If site doesn't have a Payments sidebar doc yet, do nothing (auto-gen may create later).
		return

	changed = False
	changed |= bool(_append_doctype_link(sidebar, "Post Dated Cheque", "Post Dated Cheque"))
	changed |= bool(_append_doctype_link(sidebar, "PDC Settings", "PDC Settings"))

	if changed:
		sidebar.save(ignore_permissions=True)
		frappe.db.commit()

