# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Desk Payment Entry list API smoke (real whitelisted call, no mocks).

Run::

	bench --site development.localhost execute erpnext_extensions.petty_management.smoke.pm_request_pe_list_api_smoke.execute
"""

from __future__ import annotations

from typing import Any

import frappe

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm
from erpnext_extensions.petty_management.tests.test_pm_request_multi_pe import (
	_create_funding_pe,
	_ensure_pm_settings_bank,
	_new_submitted_request,
)


def execute() -> dict[str, Any]:
	frappe.set_user("Administrator")
	out: dict[str, Any] = {"pass": False}
	try:
		tpm._ensure_company_context()
		if not tpm.COMPANY or not tpm.BANK_ACCOUNT:
			out["error"] = "missing company or bank"
			return out
		tpm._ensure_petty_account()
		_ensure_pm_settings_bank()
		emp = tpm._make_employee()
		tpm._make_holder(emp)
		req = _new_submitted_request(emp, 12_000)
		_create_funding_pe(req, 4_000)
		rows = frappe.call(
			"erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_pm_request_payment_entries",
			pm_request=req,
		)
		out["pm_request"] = req
		out["row_count"] = len((rows or {}).get("payment_entries") or []) if isinstance(rows, dict) else -1
		out["response_version_id"] = (
			(rows or {}).get("response_version_id") if isinstance(rows, dict) else None
		)
		out["http_equivalent"] = 200
		out["pass"] = isinstance(rows, dict) and out["row_count"] >= 1 and bool(out["response_version_id"])
		frappe.db.commit()
	except frappe.PermissionError as exc:
		out["error"] = "PermissionError"
		out["detail"] = str(exc)
	except TypeError as exc:
		out["error"] = "TypeError"
		out["detail"] = str(exc)
	except Exception as exc:
		out["error"] = type(exc).__name__
		out["detail"] = repr(exc)
	return out
