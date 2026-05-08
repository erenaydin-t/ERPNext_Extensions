"""Add **Cheque Opening Import** shortcut to **Cheque Management** workspace (idempotent)."""

from __future__ import annotations

import json

import frappe


def _ensure_workspace_shortcut(ws, label: str, link_to: str, link_type: str = "DocType"):
	meta = frappe.get_meta("Workspace")
	if meta.has_field("shortcuts"):
		existing = ws.get("shortcuts") or []
		for row in existing:
			if (row.get("label") or "") == label and (row.get("link_to") or "") == link_to:
				return
		ws.append("shortcuts", {"type": link_type, "label": label, "link_to": link_to})
		return
	if not meta.has_field("content"):
		return
	content = json.loads(ws.get("content") or "[]")
	for block in content:
		if block.get("type") != "shortcut":
			continue
		data = block.setdefault("data", {})
		items = data.setdefault("shortcut_items", [])
		for it in items:
			if (it.get("label") or "") == label and (it.get("link_to") or "") == link_to:
				return
		items.append({"type": link_type, "label": label, "link_to": link_to})
	ws.set("content", json.dumps(content))


def execute():
	if not frappe.db.exists("Workspace", "Cheque Management"):
		return
	ws = frappe.get_doc("Workspace", "Cheque Management")
	_ensure_workspace_shortcut(ws, "Cheque Opening Import", "Cheque Opening Import", "DocType")
	ws.save(ignore_permissions=True)
