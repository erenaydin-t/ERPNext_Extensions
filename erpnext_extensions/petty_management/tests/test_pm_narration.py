# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

from erpnext_extensions.petty_management.services.narration_templates import (
	compose_accounting_narration,
	render_pm_template,
)


class TestPMNarration(unittest.TestCase):
	def test_template_render_placeholders(self):
		tpl = "Fund {pm_request} / {employee} ({employee_name}) {total_amount} {currency}"
		ctx = {
			"pm_request": "REQ-001",
			"employee": "HR-EMP-1",
			"employee_name": "Test Employee",
			"total_amount": "10,000.00",
			"currency": "IRR",
		}
		out = render_pm_template(tpl, ctx, fallback="fallback")
		self.assertEqual(out, "Fund REQ-001 / HR-EMP-1 (Test Employee) 10,000.00 IRR")

	def test_template_fallback_when_empty(self):
		ctx = {"pm_request": "REQ-001"}
		self.assertEqual(render_pm_template("", ctx, fallback="Built-in default"), "Built-in default")
		self.assertEqual(render_pm_template(None, ctx, fallback="Built-in default"), "Built-in default")

	def test_missing_placeholder_preserved(self):
		tpl = "Clearance {pm_clearance} ref {missing_field}"
		out = render_pm_template(tpl, {"pm_clearance": "CLR-1"}, fallback="x")
		self.assertIn("CLR-1", out)
		self.assertIn("{missing_field}", out)

	def test_compose_user_remark_append(self):
		out = compose_accounting_narration("Petty cash advance for REQ-001", "Please pay today")
		self.assertTrue(out.startswith("Petty cash advance for REQ-001"))
		self.assertIn("User Remark:", out)
		self.assertIn("Please pay today", out)
		self.assertLess(out.index("Petty cash advance"), out.index("User Remark:"))

	def test_compose_without_user_remark(self):
		self.assertEqual(compose_accounting_narration("System only", ""), "System only")
		self.assertEqual(compose_accounting_narration("System only", None), "System only")
		self.assertEqual(compose_accounting_narration("System only", "   "), "System only")

	def test_compose_user_remark_only(self):
		out = compose_accounting_narration("", "Notes")
		self.assertEqual(out, "User Remark:\nNotes")


if __name__ == "__main__":
	unittest.main()
