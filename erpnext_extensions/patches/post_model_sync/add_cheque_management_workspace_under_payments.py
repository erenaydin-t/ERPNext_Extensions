from __future__ import annotations

import json

import frappe


def _ensure_workspace_shortcut(ws, label: str, link_to: str, link_type: str = "DocType"):
	"""Add a shortcut without duplicating. Supports both `shortcuts` child table and JSON `content`."""
	meta = frappe.get_meta("Workspace")

	# Newer/standard: child table `shortcuts`
	if meta.has_field("shortcuts"):
		existing = []
		try:
			existing = ws.get("shortcuts") or []
		except Exception:
			existing = []

		for row in existing:
			if (row.get("label") or "") == label and (row.get("link_to") or "") == link_to:
				return

		ws.append(
			"shortcuts",
			{
				"type": link_type,
				"label": label,
				"link_to": link_to,
			},
		)
		return

	# Fallback: JSON `content`
	if not meta.has_field("content"):
		return

	content = []
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
			return

	items.append({"type": link_type, "label": label, "link_to": link_to})
	ws.set("content", json.dumps(content))


def execute():
	"""
	Task A: Payments module navigation/access.

	Create a small "Cheque Management" workspace under the ERPNext "Payments" module.
	This adds shortcuts but does not change permissions or business logic, and does not remove
	the app's existing/custom-module access paths.
	"""
	meta = frappe.get_meta("Workspace")

	workspace_name = "Cheque Management"
	if frappe.db.exists("Workspace", workspace_name):
		ws = frappe.get_doc("Workspace", workspace_name)
	else:
		ws = frappe.new_doc("Workspace")
		# Be explicit: some Workspace naming setups require a name.
		ws.name = workspace_name

	# Explicitly set required-ish UI fields (vary across versions).
	if meta.has_field("title"):
		ws.set("title", workspace_name)
	if meta.has_field("label"):
		ws.set("label", workspace_name)

	if meta.has_field("module"):
		# Frappe expects Workspace.module to be a valid Module Def.
		# "Payments" may not exist as a module in some sites; "Accounts" does.
		ws.set("module", "Accounts")

	# Ensure content is present (required in some versions). Stored as JSON string.
	if meta.has_field("content"):
		ws.set("content", "[]")

	# Make it visible to all (unless the site uses user-specific workspaces).
	for fn, val in (
		("public", 1),
		("is_hidden", 0),
	):
		if meta.has_field(fn):
			ws.set(fn, val)

	_ensure_workspace_shortcut(ws, "Post Dated Cheque", "Post Dated Cheque", "DocType")
	_ensure_workspace_shortcut(ws, "PDC Settings", "PDC Settings", "DocType")

	# Idempotent upsert.
	if frappe.db.exists("Workspace", workspace_name):
		ws.save(ignore_permissions=True)
	else:
		ws.insert(ignore_permissions=True)

	frappe.db.commit()
