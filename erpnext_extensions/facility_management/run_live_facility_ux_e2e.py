"""UX pre-release E2E: Accounting tile + Facility Settings Persian templates.

bench --site development.localhost execute \\
  erpnext_extensions.facility_management.run_live_facility_ux_e2e.run
"""

from __future__ import annotations

import json
import time

import frappe
from frappe.utils import today

from erpnext_extensions.facility_management.doctype.facility.facility import (
	create_receipt_journal_entry,
)
from erpnext_extensions.facility_management.facility_settings_doc import (
	DEFAULT_REPAYMENT_BANK_ROW,
	FACILITY_SETTINGS_TEMPLATE_DEFAULTS,
)


def _log(title: str, payload):
	print(f"\n=== {title} ===")
	print(json.dumps(payload, indent=2, default=str))


def _ctx():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {"name": ("!=", "")}, "name", order_by="creation asc")
	bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	bank_gl = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Bank", "is_group": 0},
		"name",
		order_by="modified desc",
	)
	loan_payable = None
	deferred = frappe.db.get_value(
		"Account",
		{"company": company, "root_type": "Expense", "is_group": 0},
		"name",
		order_by="modified desc",
	)
	penalty = (
		frappe.db.get_value(
			"Account",
			{"company": company, "root_type": "Expense", "is_group": 0, "name": ("!=", deferred)},
			"name",
			order_by="modified desc",
		)
		or deferred
	)
	for row in frappe.get_all(
		"Account",
		filters={"company": company, "root_type": "Liability", "is_group": 0},
		fields=["name", "account_type"],
		limit=50,
	):
		if (row.account_type or "") not in ("Payable", "Receivable"):
			loan_payable = row.name
			break
	return {
		"company": company,
		"bank": bank,
		"bank_gl": bank_gl,
		"loan_payable": loan_payable,
		"deferred": deferred,
		"penalty": penalty,
	}


def _row_remarks(je_name: str) -> list[str]:
	return [
		r.user_remark or ""
		for r in frappe.get_doc("Journal Entry", je_name).accounts
		if (r.user_remark or "").strip()
	]


def _accounting_tile_for_user(user: str) -> dict | None:
	frappe.set_user(user)
	rows = frappe.get_all(
		"Desktop Icon",
		filters={"label": "Facility Management", "parent_icon": "Accounting", "hidden": 0},
		fields=["name", "label", "link_to", "link_type", "parent_icon"],
		limit=1,
	)
	if not rows:
		frappe.set_user("Administrator")
		return None
	allowed_roles = frappe.get_all(
		"Has Role",
		filters={"parent": rows[0].name, "parenttype": "Desktop Icon"},
		pluck="role",
	)
	if allowed_roles and not set(allowed_roles).intersection(set(frappe.get_roles())):
		frappe.set_user("Administrator")
		return None
	frappe.set_user("Administrator")
	return rows[0]


MODULE_NAME = "Facility Management"


def _fm_workspace_settings_links() -> list[dict]:
	ws = frappe.get_doc("Workspace", MODULE_NAME)
	return [
		{
			"label": row.label,
			"link_to": row.link_to,
			"type": row.type,
			"link_type": row.link_type,
		}
		for row in ws.links
		if (row.link_to or "") == "Facility Settings" or (row.label or "") == "Facility Settings"
	]


def _fm_sidebar_settings_items() -> list[dict]:
	if not frappe.db.exists("Workspace Sidebar", MODULE_NAME):
		return []
	sb = frappe.get_doc("Workspace Sidebar", MODULE_NAME)
	return [
		{
			"label": row.label,
			"link_to": row.link_to,
			"type": row.type,
			"link_type": row.link_type,
		}
		for row in sb.items
		if (row.link_to or "") == "Facility Settings" or (row.label or "") == "Facility Settings"
	]


def _sidebar_has_configuration_section() -> bool:
	if not frappe.db.exists("Workspace Sidebar", MODULE_NAME):
		return False
	sb = frappe.get_doc("Workspace Sidebar", MODULE_NAME)
	return any((row.label or "") == "Configuration" and row.type == "Section Break" for row in sb.items)


def _provision_fm_navigation_twice() -> dict:
	from erpnext_extensions.patches.post_model_sync.add_facility_management_workspace import (
		execute as provision_fm_workspace,
	)

	provision_fm_workspace()
	count_ws_1 = len(_fm_workspace_settings_links())
	count_sb_1 = len(_fm_sidebar_settings_items())
	provision_fm_workspace()
	count_ws_2 = len(_fm_workspace_settings_links())
	count_sb_2 = len(_fm_sidebar_settings_items())
	frappe.cache.delete_key("bootinfo")
	return {
		"workspace_link_count_after_first": count_ws_1,
		"workspace_link_count_after_second": count_ws_2,
		"sidebar_link_count_after_first": count_sb_1,
		"sidebar_link_count_after_second": count_sb_2,
	}


def run():
	errors: list[str] = []
	results: dict = {"tests": {}}
	ctx = _ctx()
	suffix = str(int(time.time()))

	# Accounting module tile (Accounts Manager role user if present)
	tile_admin = _accounting_tile_for_user("Administrator")
	am_user = frappe.db.get_value(
		"Has Role",
		{"role": "Accounts Manager", "parenttype": "User"},
		"parent",
	)
	tile_am = _accounting_tile_for_user(am_user) if am_user else None
	t1 = {
		"administrator": {"found": bool(tile_admin), "link_to": (tile_admin or {}).get("link_to")},
		"accounts_manager": {"found": bool(tile_am), "user": am_user},
	}
	results["tests"]["accounting_tile"] = t1
	_log("Accounting tile", t1)
	if not tile_admin:
		errors.append("Accounting tile missing for Administrator")
	elif tile_admin.get("link_to") != "Facility Management":
		errors.append(f"Accounting tile link_to {tile_admin.get('link_to')}")
	if am_user and not tile_am:
		errors.append("Accounting tile missing for Accounts Manager user")

	# Facility Settings in workspace + sidebar (Configuration section)
	nav = _provision_fm_navigation_twice()
	ws_links = _fm_workspace_settings_links()
	sb_links = _fm_sidebar_settings_items()
	t_nav = {
		"workspace_facility_settings_links": ws_links,
		"sidebar_facility_settings_items": sb_links,
		"sidebar_configuration_section": _sidebar_has_configuration_section(),
		"idempotent_provision": nav,
	}
	results["tests"]["facility_settings_navigation"] = t_nav
	_log("Facility Settings navigation", t_nav)
	if len(ws_links) != 1 or ws_links[0].get("link_to") != "Facility Settings":
		errors.append(f"Workspace Facility Settings link missing/wrong: {ws_links}")
	if len(sb_links) != 1 or sb_links[0].get("link_to") != "Facility Settings":
		errors.append(f"Sidebar Facility Settings link missing/wrong: {sb_links}")
	if not t_nav["sidebar_configuration_section"]:
		errors.append("Sidebar missing Configuration section")
	if nav["workspace_link_count_after_second"] != 1 or nav["sidebar_link_count_after_second"] != 1:
		errors.append(f"Duplicate Facility Settings links after double provision: {nav}")
	if am_user:
		frappe.set_user(am_user)
		can_read = frappe.has_permission("Facility Settings", "read")
		frappe.set_user("Administrator")
		t_nav["accounts_manager_can_read_settings"] = can_read
		if not can_read:
			errors.append("Accounts Manager cannot read Facility Settings")

	# Test A — new Facility Settings templates (company without existing row)
	test_co = None
	for cname in frappe.get_all("Company", pluck="name"):
		if not frappe.db.exists("Facility Settings", {"company": cname}):
			test_co = cname
			break
	if not test_co:
		fs = frappe.new_doc("Facility Settings")
		fs.company = ctx["company"]
		for fn in FACILITY_SETTINGS_TEMPLATE_DEFAULTS:
			fs.set(fn, None)
		from erpnext_extensions.facility_management.facility_settings_doc import (
			populate_facility_settings_template_defaults,
		)

		populate_facility_settings_template_defaults(fs)
		t_a = {
			"company": ctx["company"],
			"mode": "populate_only",
			"templates": {fn: fs.get(fn) for fn in FACILITY_SETTINGS_TEMPLATE_DEFAULTS},
		}
		results["tests"]["A_new_settings_templates"] = t_a
		_log("Test A populate defaults (no spare company)", t_a)
		for fn, exp in FACILITY_SETTINGS_TEMPLATE_DEFAULTS.items():
			if fs.get(fn) != exp:
				errors.append(f"A: {fn} not populated")
	else:
		fs = frappe.new_doc("Facility Settings")
		fs.company = test_co
		fs.insert(ignore_permissions=True)
		frappe.db.commit()
		templates = {fn: fs.get(fn) for fn in FACILITY_SETTINGS_TEMPLATE_DEFAULTS}
		t_a = {"company": test_co, "mode": "insert", "templates": templates}
		results["tests"]["A_new_settings_templates"] = t_a
		_log("Test A new Facility Settings templates", t_a)
		for fn, exp in FACILITY_SETTINGS_TEMPLATE_DEFAULTS.items():
			if fs.get(fn) != exp:
				errors.append(f"A: {fn} not populated")

	# Test B — receipt row descriptions (use main company settings)
	fac = frappe.new_doc("Facility")
	fac.facility_name = f"FM UX Receipt {suffix}"
	fac.company = ctx["company"]
	fac.bank = ctx["bank"]
	fac.contract_date = today()
	fac.receive_date = today()
	fac.principal_amount = 8000
	fac.profit_amount = 1000
	fac.loan_payable_account = ctx["loan_payable"]
	fac.bank_account = ctx["bank_gl"]
	fac.deferred_loan_interest_account = ctx["deferred"]
	fac.insert(ignore_permissions=True)
	frappe.db.commit()
	create_receipt_journal_entry(fac.name)
	fac.reload()
	remarks = _row_remarks(fac.receipt_journal_entry)
	t_b = {"facility": fac.name, "remarks": remarks}
	results["tests"]["B_receipt_descriptions"] = t_b
	_log("Test B receipt JE descriptions", t_b)
	if not remarks or fac.name not in "".join(remarks):
		errors.append("B: receipt row descriptions missing facility number")
	if "واریز تسهیلات" not in "".join(remarks):
		errors.append("B: default receipt bank row template missing")

	# Test C — repayment descriptions
	rep = frappe.new_doc("Facility Repayment")
	rep.facility = fac.name
	rep.posting_date = today()
	rep.principal_amount = 800
	rep.profit_amount = 140
	rep.penalty_amount = 60
	rep.insert(ignore_permissions=True)
	rep.submit()
	frappe.db.commit()
	rep_remarks = _row_remarks(rep.journal_entry)
	t_c = {"repayment": rep.name, "remarks": rep_remarks}
	results["tests"]["C_repayment_descriptions"] = t_c
	_log("Test C repayment JE descriptions", t_c)
	if "پرداخت قسط تسهیلات از بانک" not in "".join(rep_remarks):
		errors.append("C: repayment bank row template not reflected")

	# Test D — customized template on settings
	custom = f"CUSTOM-{suffix} پرداخت قسط"
	main_fs_name = frappe.db.get_value("Facility Settings", {"company": ctx["company"]}, "name")
	orig_bank_tpl = None
	if main_fs_name:
		main_fs = frappe.get_doc("Facility Settings", main_fs_name)
		orig_bank_tpl = main_fs.default_repayment_bank_row_description_template
		main_fs.default_repayment_bank_row_description_template = custom
		main_fs.save(ignore_permissions=True)
		frappe.db.commit()
	rep2 = frappe.new_doc("Facility Repayment")
	rep2.facility = fac.name
	rep2.posting_date = today()
	rep2.principal_amount = 10
	rep2.profit_amount = 0
	rep2.penalty_amount = 0
	rep2.insert(ignore_permissions=True)
	rep2.submit()
	frappe.db.commit()
	rep2_remarks = _row_remarks(rep2.journal_entry)
	t_d = {"custom_template": custom, "remarks": rep2_remarks}
	results["tests"]["D_custom_template"] = t_d
	_log("Test D custom repayment bank template", t_d)
	if custom not in "".join(rep2_remarks):
		errors.append("D: custom template not used on JE")
	if main_fs_name and orig_bank_tpl is not None:
		frappe.db.set_value(
			"Facility Settings",
			main_fs_name,
			"default_repayment_bank_row_description_template",
			orig_bank_tpl,
		)
		frappe.db.commit()

	results["errors"] = errors
	results["passed"] = not errors
	_log("SUMMARY", results)
	if errors:
		frappe.throw("Facility UX E2E failed:\n" + "\n".join(errors))
	print("\nFacility UX E2E PASSED")
	return results
