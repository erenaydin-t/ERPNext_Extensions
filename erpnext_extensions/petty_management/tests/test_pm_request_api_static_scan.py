# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Static guardrails: no raw frappe.get_doc('PM Request') outside request_api_guard."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import frappe

GET_DOC_PM_REQUEST = re.compile(r"""frappe\.get_doc\s*\(\s*['"]PM Request['"]""")

# Paths that may load PM Request without going through guard loaders (tests, e2e, smoke).
RAW_GET_DOC_ALLOWLIST_PREFIXES = (
	"petty_management/services/request_api_guard.py",
	"petty_management/tests/",
	"petty_management/e2e/",
	"petty_management/smoke/",
)

PM_REQUEST_API_FILES = (
	"petty_management/doctype/pm_request/pm_request.py",
	"petty_management/workflow_hooks.py",
	"petty_management/services/request_service.py",
	"petty_management/services/funding_service.py",
	"petty_management/services/allocation_service.py",
)


def _is_allowlisted(rel: str) -> bool:
	norm = rel.replace("\\", "/")
	for prefix in RAW_GET_DOC_ALLOWLIST_PREFIXES:
		p = prefix.replace("\\", "/")
		if norm == p or norm.startswith(p):
			return True
	return False


class TestPmRequestApiStaticScan(unittest.TestCase):
	def test_petty_management_has_no_raw_get_doc_outside_guard(self):
		app_path = Path(frappe.get_app_path("erpnext_extensions")) / "petty_management"
		violations: list[str] = []
		for path in sorted(app_path.rglob("*.py")):
			rel = str(path.relative_to(app_path.parent)).replace("\\", "/")
			if _is_allowlisted(rel):
				continue
			text = path.read_text(encoding="utf-8")
			if GET_DOC_PM_REQUEST.search(text):
				violations.append(rel)
		self.assertEqual(
			violations,
			[],
			msg="Raw frappe.get_doc('PM Request') must use request_api_guard loaders: "
			+ ", ".join(violations),
		)

	def test_pm_request_api_modules_use_guard_loaders(self):
		app_path = Path(frappe.get_app_path("erpnext_extensions"))
		violations: list[str] = []
		for rel in PM_REQUEST_API_FILES:
			path = app_path / rel
			if not path.is_file():
				continue
			text = path.read_text(encoding="utf-8")
			if GET_DOC_PM_REQUEST.search(text):
				violations.append(rel)
		self.assertEqual(violations, [], msg="API modules bypass guard: " + ", ".join(violations))

	def test_request_service_create_payment_entry_uses_guard(self):
		app_path = Path(frappe.get_app_path("erpnext_extensions"))
		text = (app_path / "petty_management/services/request_service.py").read_text(encoding="utf-8")
		start = text.find("def create_payment_entry(")
		self.assertGreater(start, -1)
		chunk = text[start : start + 2500]
		self.assertIn("get_pm_request_doc_for_write", chunk)
		self.assertIn("get_pm_request_doc_for_write_lock", chunk)
		self.assertNotRegex(chunk, GET_DOC_PM_REQUEST)


if __name__ == "__main__":
	unittest.main()
