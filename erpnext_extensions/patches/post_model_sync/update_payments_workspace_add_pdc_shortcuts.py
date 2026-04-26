from __future__ import annotations

import json

import frappe


def _ensure_workspace_shortcut(ws, label: str, link_to: str, link_type: str = "DocType"):
	"""Add a shortcut without duplicating. Supports both `shortcuts` child table and JSON `content`."""
	meta = frappe.get_meta("Workspace")

	# Preferred: child table `shortcuts`
	if meta.has_field("shortcuts"):
		try:
			existing = ws.get("shortcuts") or []
		except Exception:
			existing = []

		for row in existing:
			if (row.get("label") or "") == label and (row.get("link_to") or "") == link_to:
				return False

		ws.append(
			"shortcuts",
			{
				"type": link_type,
				"label": label,
				"link_to": link_to,
			},
		)
		return True

	# Fallback: JSON `content`
	if not meta.has_field("content"):
		return False

	try:
		raw = ws.get("content") or "[]"
		content = json.loads(raw) if isinstance(raw, str) else (raw or [])
	except Exception:
		content = []

	# Find or create a shortcut block.
	block = None
	for b in content:
		if (b or {}).get("type") == "shortcut":
			block = b
			break

	if not block:
		block = {"type": "shortcut", "data": {"shortcut_items": []}}
		content.insert(0, block)

	data = block.setdefault("data", {})
	items = data.setdefault("shortcut_items", [])

	for it in items:
		if (it.get("label") or "") == label and (it.get("link_to") or "") == link_to:
			ws.set("content", json.dumps(content))
			return False

	items.append({"type": link_type, "label": label, "link_to": link_to})
	ws.set("content", json.dumps(content))
	return True


def _get_payments_workspace():
	# Usually the Workspace name is exactly "Payments".
	if frappe.db.exists("Workspace", "Payments"):
		return frappe.get_doc("Workspace", "Payments")

	# Fallback: find by title if name differs.
	try:
		name = frappe.db.get_value("Workspace", {"title": "Payments"}, "name")
		if name:
			return frappe.get_doc("Workspace", name)
	except Exception:
		pass

	return None


def execute():
	"""
	Task A (fix): Add cheque-related shortcuts to the existing ERPNext Payments workspace.
	Preserves existing Payments content; idempotent; no permission/business-logic changes.
	"""
	ws = _get_payments_workspace()
	if not ws:
		# If the site doesn't have the standard Payments workspace, do nothing.
		return

	changed = False
	changed |= bool(_ensure_workspace_shortcut(ws, "Post Dated Cheque", "Post Dated Cheque", "DocType"))
	changed |= bool(_ensure_workspace_shortcut(ws, "PDC Settings", "PDC Settings", "DocType"))

	if changed:
		ws.save(ignore_permissions=True)
		frappe.db.commit()

