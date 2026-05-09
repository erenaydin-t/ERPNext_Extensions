from __future__ import annotations

import frappe


def execute():
	"""Rename PM Holder documents to `{employee}-{company}` when still using legacy employee-only name."""
	if not frappe.db.has_table("tabPM Holder"):
		return
	for h in frappe.get_all("PM Holder", fields=["name", "employee", "company"]):
		if not h.get("employee") or not h.get("company"):
			continue
		target = f"{h.employee}-{h.company}"
		if len(target) > 120:
			target = target[:120]
		if h.name == target:
			continue
		if frappe.db.exists("PM Holder", target):
			frappe.log_error(
				message=f"PM Holder rename skipped: {h.name} -> {target} (target exists)",
				title="PM Holder name migration",
			)
			continue
		try:
			frappe.rename_doc("PM Holder", h.name, target, force=True, merge=False)
		except Exception:
			frappe.log_error(
				message=frappe.get_traceback(),
				title=f"PM Holder rename failed: {h.name}",
			)
	frappe.db.commit()
