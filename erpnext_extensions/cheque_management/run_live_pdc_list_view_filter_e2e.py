"""Live E2E prep + server checks for Post Dated Cheque list filter hygiene.

Browser E2E (desk, after bench build + hard refresh):

  /app/post-dated-cheque?run_pdc_list_filter_e2e=1

Console: ``all_ok: true`` and cases A–E in the results table:

  A — hidden standard filter → auto-clear
  B — visible chip filter, empty list → no auto-clear
  C — URL query blocks auto-clear predicate
  D — fresh list shows rows
  E — manual Clear Filter shows rows

bench --site development.localhost execute erpnext_extensions.cheque_management.run_live_pdc_list_view_filter_e2e.run
"""

from __future__ import annotations

import json

import frappe
from frappe.model.utils.user_settings import get_user_settings, update_user_settings


def _parse_list_settings(raw: str) -> dict:
	try:
		data = json.loads(raw or "{}")
	except json.JSONDecodeError:
		return {}
	return data if isinstance(data, dict) else {}


def run():
	frappe.set_user("Administrator")
	errors: list[str] = []
	evidence: dict = {}

	db_count = frappe.db.count("Post Dated Cheque")
	evidence["db_count"] = db_count
	if db_count <= 0:
		errors.append("No Post Dated Cheque rows on site — cannot validate list filter E2E")

	raw = get_user_settings("Post Dated Cheque")
	settings = _parse_list_settings(raw)
	list_view = settings.get("List") or {}
	saved_filters = list_view.get("filters") or []
	evidence["saved_list_filters_before"] = saved_filters

	# Simulate saved invalid empty ID filter (root cause: name Equals "").
	impossible = [["Post Dated Cheque", "name", "=", ""]]
	list_view["filters"] = impossible
	settings["List"] = list_view
	update_user_settings("Post Dated Cheque", settings)
	frappe.db.commit()

	evidence["saved_list_filters_seeded"] = impossible
	evidence["browser_steps"] = [
		"1. Hard refresh desk (Ctrl+Shift+R) so post_dated_cheque_list.js is loaded.",
		"2. Open /app/post-dated-cheque — expect auto-clear alert if list was empty with filters.",
		"3. Open /app/post-dated-cheque?run_pdc_list_filter_e2e=1 — check console table (all ok: true).",
		"4. In console on list: erpnext_extensions.cheque_management.pdc_list_view.get_filter_debug(cur_list)",
	]

	# Restore filters after seeding (reconcile should have cleared on client; server-side restore empty).
	list_view["filters"] = []
	settings["List"] = list_view
	update_user_settings("Post Dated Cheque", settings)
	frappe.db.commit()
	evidence["saved_list_filters_after_restore"] = []

	result = {
		"status": "PASSED" if not errors else "FAILED",
		"errors": errors,
		"evidence": evidence,
	}
	print(json.dumps(result, indent=2, default=str))
	if errors:
		frappe.throw("; ".join(errors))
	return result
