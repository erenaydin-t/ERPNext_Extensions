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


def _is_section_break(it) -> bool:
	return (it.get("type") or "") == "Section Break"


def _is_link(it) -> bool:
	return (it.get("type") or "") == "Link"


def _link_key(it) -> tuple[str, str]:
	return ((it.get("link_type") or "") or "").strip(), ((it.get("link_to") or "") or "").strip()


def _has_link(sidebar, link_type: str, link_to: str) -> bool:
	want = ((link_type or "").strip(), (link_to or "").strip())
	for it in (sidebar.get("items") or []):
		if not _is_link(it):
			continue
		if _link_key(it) == want:
			return True
	return False


def _append_link(sidebar, *, link_type: str, link_to: str, label: str | None = None) -> bool:
	if _has_link(sidebar, link_type, link_to):
		return False

	sidebar.append(
		"items",
		{
			"label": label or link_to,
			"type": "Link",
			"link_type": link_type,
			"link_to": link_to,
		},
	)
	return True


def _append_section_break(sidebar, label: str) -> bool:
	"""Append a section break if missing (exact label match)."""
	for it in (sidebar.get("items") or []):
		if _is_section_break(it) and (it.get("label") or "") == label:
			return False
	sidebar.append("items", {"label": label, "type": "Section Break", "link_type": "DocType", "link_to": None})
	return True


def _remove_existing_links(sidebar, targets: set[tuple[str, str]]) -> bool:
	"""Remove any existing links matching (link_type, link_to). Keeps first occurrence removed; idempotent."""
	items = list(sidebar.get("items") or [])
	new_items = []
	changed = False
	for it in items:
		if _is_link(it) and _link_key(it) in targets:
			changed = True
			continue
		new_items.append(it)
	if changed:
		sidebar.set("items", new_items)
	return changed


def _remove_section_breaks(sidebar, labels: set[str]) -> bool:
	items = list(sidebar.get("items") or [])
	new_items = []
	changed = False
	for it in items:
		if _is_section_break(it) and (it.get("label") or "") in labels:
			changed = True
			continue
		new_items.append(it)
	if changed:
		sidebar.set("items", new_items)
	return changed


def _insert_block_before_first_section(sidebar, before_label: str, block_items: list[dict]) -> bool:
	"""Insert items before the first Section Break with given label; if not found, append at end."""
	items = list(sidebar.get("items") or [])
	idx = None
	for i, it in enumerate(items):
		if _is_section_break(it) and (it.get("label") or "") == before_label:
			idx = i
			break
	if idx is None:
		# Append
		for bi in block_items:
			sidebar.append("items", bi)
		return True
	# Insert at idx preserving order
	sidebar.set("items", items[:idx] + block_items + items[idx:])
	return True


def _native_section_break(*, label: str, icon: str, keep_closed: int = 0) -> dict:
	"""Match ERPNext `Workspace Sidebar` fixtures (e.g. payments.json Reports / Payments headers)."""
	return {
		"label": label,
		"type": "Section Break",
		"link_type": "DocType",
		"link_to": None,
		"child": 0,
		"indent": 1,
		"collapsible": 1,
		"keep_closed": keep_closed,
		"icon": icon,
		"show_arrow": 0,
	}


def _native_child_link(*, link_type: str, link_to: str, label: str | None = None) -> dict:
	"""Nested link under a Section Break: `child` + `collapsible` so desk JS nests and skips default list icon."""
	return {
		"label": label or link_to,
		"type": "Link",
		"link_type": link_type,
		"link_to": link_to,
		"child": 1,
		"collapsible": 1,
		"indent": 0,
		"keep_closed": 0,
		"show_arrow": 0,
	}


def _reindex_items(sidebar) -> None:
	"""Ensure child table `idx` matches current list order.

Without this, inserting raw dicts can leave duplicate/zero idx values, and the UI/ORM
may show a scrambled order (since child rows are sorted by idx).
"""
	for i, it in enumerate(sidebar.get("items") or []):
		it.idx = i + 1


def execute():
	"""
	Task A (navigation): grouped cheque links in the Payments *module sidebar*.

	The left module sidebar is driven by `Workspace Sidebar` (per module), not by `Workspace`.
	This patch updates the existing Payments sidebar without touching ERPNext core files.

	Scope note:
	- This patch only manages **navigation links** (sidebar sections + links).
	- It does not create/maintain a dedicated "Cheque Management" Workspace.
	"""
	sidebar = _get_payments_sidebar()
	if not sidebar:
		# If site doesn't have a Payments sidebar doc yet, do nothing (auto-gen may create later).
		return

	# Targets (type, link_to) we own.
	target_links: list[tuple[str, str, str]] = [
		("DocType", "Post Dated Cheque", "Post Dated Cheque"),
		("DocType", "Cheque Book", "Cheque Book"),
		("DocType", "Cheque Leaf", "Cheque Leaf"),
		("DocType", "Cheque Opening Import", "Cheque Opening Import"),
		("Report", "Cheque Maturity Report", "Cheque Maturity Report"),
		("DocType", "PDC Settings", "PDC Settings"),
	]
	target_set = {(lt, to) for (lt, to, _lbl) in target_links}
	section_labels = {"Cheque Operations", "Cheque Reports", "Cheque Configuration"}

	changed = False
	# Remove existing owned links wherever they currently live to avoid duplicates and to "move" them.
	changed |= bool(_remove_existing_links(sidebar, target_set))
	# Remove our sections to avoid duplicates and to allow re-insertion in correct place.
	changed |= bool(_remove_section_breaks(sidebar, section_labels))

	# Build the grouped block (native section semantics: indented collapsible headers + child links).
	block: list[dict] = []

	op_links: list[dict] = []
	for lt, to, lbl in target_links[:4]:
		if lt == "DocType" and frappe.db.exists("DocType", to):
			op_links.append(_native_child_link(link_type=lt, link_to=to, label=lbl))
	if op_links:
		block.append(_native_section_break(label="Cheque Operations", icon="banknote", keep_closed=0))
		block.extend(op_links)

	# Report link: only add if report exists (script report is a Report doc)
	if frappe.db.exists("Report", "Cheque Maturity Report"):
		block.append(_native_section_break(label="Cheque Reports", icon="sheet", keep_closed=1))
		block.append(
			_native_child_link(
				link_type="Report",
				link_to="Cheque Maturity Report",
				label="Cheque Maturity Report",
			)
		)

	if frappe.db.exists("DocType", "PDC Settings"):
		block.append(_native_section_break(label="Cheque Configuration", icon="settings", keep_closed=0))
		block.append(_native_child_link(link_type="DocType", link_to="PDC Settings", label="PDC Settings"))

	# Insert the block before the existing "Reports" section if present; otherwise append.
	if block:
		changed |= bool(_insert_block_before_first_section(sidebar, "Reports", block))

	if changed:
		_reindex_items(sidebar)
		sidebar.save(ignore_permissions=True)
		frappe.db.commit()

