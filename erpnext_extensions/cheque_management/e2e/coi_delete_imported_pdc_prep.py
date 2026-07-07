"""Prep data for Cheque Opening Import — Delete Imported PDC Playwright E2E."""

from __future__ import annotations

import time

import frappe
from frappe.utils import today

from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
	import_row,
)
from erpnext_extensions.cheque_management.doctype.cheque_opening_import.run_live_opening_import_accounting_e2e import (
	_base_receivable_row,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_site_context,
	_unique_cheque_no,
)
from erpnext_extensions.cheque_management.pdc_import_cleanup_ui import user_may_delete_imported_pdc_ui


def _ensure_drawer_bank(ctx: dict) -> None:
	if not ctx.get("drawer_bank"):
		ctx["drawer_bank"] = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")


def _ensure_accounts_manager_user() -> dict:
	"""Desk login user without Administrator (for E2E)."""
	email = frappe.db.get_value(
		"User",
		{"name": ["not in", ["Administrator", "Guest"]], "enabled": 1},
		"name",
		order_by="modified desc",
	)
	if not email:
		frappe.throw("No non-admin User for E2E")
	from frappe.utils.password import update_password

	update_password(email, "test_password")
	frappe.db.commit()
	return {"email": email, "password": "test_password"}


def _coi_with_imported_pdc(*, suffix: str) -> dict:
	frappe.set_user("Administrator")
	ctx = _site_context()
	_ensure_drawer_bank(ctx)
	chq = _unique_cheque_no(f"E2E-DEL-{suffix}")
	row = _base_receivable_row(ctx, chq, "Registered")
	coi = frappe.new_doc("Cheque Opening Import")
	coi.insert(ignore_permissions=True)
	frappe.flags.cheque_opening_import_name = coi.name
	pdc = import_row(1, row)
	if hasattr(frappe.flags, "cheque_opening_import_name"):
		delattr(frappe.flags, "cheque_opening_import_name")
	coi.reload()
	coi.items = []
	coi.append(
		"items",
		{
			"row_number": 1,
			"row_status": "Imported",
			"imported_pdc": pdc,
			"post_dated_cheque": pdc,
			"validation_message": pdc,
		},
	)
	coi.import_status = "Completed"
	coi.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"coi_name": coi.name,
		"pdc_name": pdc,
		"cheque_no": chq,
		"company": ctx["company"],
	}


def e2e_prep_safe_delete() -> dict:
	return _coi_with_imported_pdc(suffix=str(int(time.time() * 1000)))


def e2e_prep_blocked_delete() -> dict:
	out = _coi_with_imported_pdc(suffix=f"BLK-{int(time.time() * 1000)}")
	pdc = out["pdc_name"]
	from erpnext_extensions.e2e.e2e_fixture import e2e_submitted_journal_entry_for_company

	je = e2e_submitted_journal_entry_for_company(out["company"])
	doc = frappe.get_doc("Post Dated Cheque", pdc)
	doc.append(
		"journal_references",
		{
			"journal_entry": je,
			"purpose": "Receive",
			"posting_date": today(),
			"amount": 1,
		},
	)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	out["blocked"] = True
	return out


def e2e_prep_reimport_row(cheque_no: str, company: str) -> dict:
	"""After delete, run import_row again with same cheque key."""
	frappe.set_user("Administrator")
	ctx = _site_context()
	ctx["company"] = company
	_ensure_drawer_bank(ctx)
	row = _base_receivable_row(ctx, cheque_no, "Registered")
	coi = frappe.new_doc("Cheque Opening Import")
	coi.insert(ignore_permissions=True)
	frappe.flags.cheque_opening_import_name = coi.name
	pdc = import_row(1, row)
	if hasattr(frappe.flags, "cheque_opening_import_name"):
		delattr(frappe.flags, "cheque_opening_import_name")
	frappe.db.commit()
	return {"pdc_name": pdc, "coi_name": coi.name}


def e2e_non_admin_user() -> dict:
	return _ensure_accounts_manager_user()


def e2e_share_coi_read(coi_name: str, user_email: str) -> dict:
	frappe.share.add("Cheque Opening Import", coi_name, user_email, read=1)
	frappe.db.commit()
	return {"ok": True}


def e2e_may_delete_as_user(user_email: str) -> dict:
	frappe.set_user(user_email)
	return {"may_delete": bool(user_may_delete_imported_pdc_ui())}


def e2e_preview_as_user(pdc_name: str, user_email: str) -> dict:
	from erpnext_extensions.cheque_management.pdc_import_cleanup_ui import (
		preview_delete_imported_pdc,
	)

	frappe.set_user(user_email)
	try:
		preview_delete_imported_pdc(pdc_name)
		return {"rejected": False}
	except frappe.PermissionError as e:
		return {"rejected": True, "message": str(e)}
