"""Database reads for Playwright E2E — source of truth for document state."""

from __future__ import annotations

import frappe


def _default_fields(doctype: str) -> list[str]:
	fields = ["name", "docstatus", "modified"]
	meta = frappe.get_meta(doctype)
	for optional in ("workflow_state", "cheque_status", "status", "import_status"):
		if optional in meta.get_valid_columns() and optional not in fields:
			fields.append(optional)
	return fields


def e2e_get_document_state(
	doctype: str,
	name: str,
	fields: list[str] | None = None,
) -> dict:
	"""Return current row from DB (or ``exists: false``)."""
	doctype = (doctype or "").strip()
	name = (name or "").strip()
	if not doctype or not name:
		return {"exists": False, "doctype": doctype, "name": name}
	if not frappe.db.exists(doctype, name):
		return {"exists": False, "doctype": doctype, "name": name}
	use_fields = list(fields) if fields else _default_fields(doctype)
	use_fields = ["name", *{f for f in use_fields if f != "name"}]
	row = frappe.db.get_value(doctype, name, use_fields, as_dict=True) or {}
	return {"exists": True, "doctype": doctype, **row}


def e2e_document_exists(doctype: str, name: str) -> dict:
	"""Bench-safe JSON (plain bool breaks Playwright JSON.parse)."""
	return {
		"exists": bool(
			e2e_get_document_state(doctype, name, fields=["name"]).get("exists")
		)
	}


def e2e_wait_document_state(
	doctype: str,
	name: str,
	expected: dict,
	timeout_sec: float = 90.0,
	poll_sec: float = 0.5,
	fields: list[str] | None = None,
) -> dict:
	"""Poll DB until ``expected`` field values match (for bench execute / diagnostics)."""
	import time

	started = time.monotonic()
	last: dict = {"exists": False}
	while time.monotonic() - started < timeout_sec:
		last = e2e_get_document_state(doctype, name, fields=fields)
		if expected.get("exists") is False and not last.get("exists"):
			return {
				"ok": True,
				"state": last,
				"elapsed_ms": int((time.monotonic() - started) * 1000),
				"expected": expected,
			}
		if last.get("exists"):
			if all(last.get(k) == v for k, v in expected.items() if k != "exists"):
				return {
					"ok": True,
					"state": last,
					"elapsed_ms": int((time.monotonic() - started) * 1000),
					"expected": expected,
				}
		time.sleep(poll_sec)
	return {
		"ok": False,
		"state": last,
		"elapsed_ms": int((time.monotonic() - started) * 1000),
		"expected": expected,
	}


def e2e_wait_workflow_state(
	doctype: str,
	name: str,
	workflow_state: str,
	**kwargs,
) -> dict:
	return e2e_wait_document_state(
		doctype, name, {"workflow_state": workflow_state}, **kwargs
	)


def e2e_wait_docstatus(
	doctype: str,
	name: str,
	docstatus: int,
	**kwargs,
) -> dict:
	return e2e_wait_document_state(doctype, name, {"docstatus": docstatus}, **kwargs)
