# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Clean-site defaults + real hierarchical business fixture acceptance."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import cint, flt

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import build_voucher_gl_print
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import (
	enrich_print_payload,
	render_voucher_package,
)
from erpnext_extensions.iran_accounting.domain.amount_scale import (
	SCALE_MILLIONS,
	SCALE_RAW,
	normalize_amount_scale,
	resolve_print_amount_scale,
)
from erpnext_extensions.patches.post_model_sync.seed_voucher_gl_layout_settings import (
	INT_DEFAULTS,
	OFF_DEFAULTS,
	ON_DEFAULTS,
	SELECT_DEFAULTS,
	SEED_VERSION,
	VERSION_FIELD,
	apply_voucher_gl_print_defaults,
	_singles_value,
)
from erpnext_extensions.iran_accounting.tests.voucher_gl_print_fixtures import (
	ensure_hierarchy_business_fixture,
	ensure_print_company,
)


class TestVoucherGLPrintDefaults(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

	def test_clean_defaults_after_seed(self):
		# Simulate post-migrate Check=0 by resetting version and zeroing ON fields.
		settings = frappe.get_single("Iran Accounting Settings")
		if settings.meta.has_field(VERSION_FIELD):
			settings.set(VERSION_FIELD, 0)
		for fieldname in ON_DEFAULTS:
			if settings.meta.has_field(fieldname):
				settings.set(fieldname, 0)
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		apply_voucher_gl_print_defaults(force=False)
		settings = frappe.get_single("Iran Accounting Settings")

		self.assertEqual(settings.voucher_gl_layout, SELECT_DEFAULTS["voucher_gl_layout"])
		self.assertEqual(settings.voucher_gl_page_layout, "Auto")
		self.assertEqual(settings.voucher_gl_amount_scale, "Raw")
		self.assertEqual(settings.default_amount_display_scale, "Raw")
		for fieldname, expected in ON_DEFAULTS.items():
			if settings.meta.has_field(fieldname):
				self.assertEqual(cint(settings.get(fieldname)), expected, fieldname)
		for fieldname, expected in OFF_DEFAULTS.items():
			if settings.meta.has_field(fieldname):
				self.assertEqual(cint(settings.get(fieldname)), expected, fieldname)
		for fieldname, expected in INT_DEFAULTS.items():
			if settings.meta.has_field(fieldname):
				self.assertEqual(cint(settings.get(fieldname)), expected, fieldname)
		self.assertEqual(cint(settings.get(VERSION_FIELD) or 0), SEED_VERSION)

	def test_user_amount_scale_pass_through_priority(self):
		# Print profile Raw beats AE Auto / Thousands (ISSUE 4).
		settings = frappe.get_single("Iran Accounting Settings")
		prev = settings.voucher_gl_amount_scale
		settings.voucher_gl_amount_scale = "Raw"
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		try:
			opts = resolve_print_amount_scale(
				{"amount_scale": "Use Default", "user_amount_scale": "Thousands", "currency": "IRR"}
			)
			self.assertEqual(opts.scale, SCALE_RAW)

			# Explicit Millions beats user Raw and profile Raw
			opts = resolve_print_amount_scale(
				{"amount_scale": "Millions", "user_amount_scale": "Raw", "currency": "IRR"}
			)
			self.assertEqual(opts.scale, SCALE_MILLIONS)
		finally:
			settings.voucher_gl_amount_scale = prev
			settings.flags.ignore_permissions = True
			settings.save()
			frappe.db.commit()

		# Enum normalization from AE modes
		self.assertEqual(normalize_amount_scale("millions"), SCALE_MILLIONS)
		self.assertEqual(normalize_amount_scale("Raw"), SCALE_RAW)

	def test_resolved_amount_scale_raw_when_settings_default_raw(self):
		"""When Default Amount Display Scale / print scale are Raw, payload resolves to raw."""
		from erpnext_extensions.iran_accounting.domain.amount_scale import (
			resolve_auto_to_settings_scale,
		)
		from erpnext_extensions.iran_accounting.tests.voucher_gl_print_fixtures import (
			ensure_hierarchy_business_fixture,
			ensure_print_company,
		)

		prev_default = frappe.db.get_single_value(
			"Iran Accounting Settings", "default_amount_display_scale"
		)
		prev_print = frappe.db.get_single_value(
			"Iran Accounting Settings", "voucher_gl_amount_scale"
		)
		frappe.db.set_single_value(
			"Iran Accounting Settings",
			{
				"default_amount_display_scale": "Raw",
				"voucher_gl_amount_scale": "Raw",
			},
		)
		frappe.clear_cache(doctype="Iran Accounting Settings")
		try:
			self.assertEqual(resolve_auto_to_settings_scale("Auto"), SCALE_RAW)
			opts = resolve_print_amount_scale(
				{"amount_scale": "Use Default", "user_amount_scale": "Auto", "currency": "IRR"}
			)
			self.assertEqual(opts.scale, SCALE_RAW)

			class _Gate:
				@staticmethod
				def skipTest(msg):
					raise unittest.SkipTest(msg)

			ctx = ensure_hierarchy_business_fixture(ensure_print_company(_Gate()))
			filters = {
				"company": ctx["company"],
				"voucher_type": "Journal Entry",
				"voucher_no": ctx["hier_je"],
				"language": "fa",
				"layout": "Standard",
				"amount_scale": "Use Default",
				"user_amount_scale": "Auto",
				"include_opening_entries": 1,
			}
			payload = enrich_print_payload(build_voucher_gl_print(filters), filters)
			self.assertEqual(payload.get("resolved_amount_scale"), "raw")
			self.assertEqual(getattr(payload.get("amount_scale"), "scale", None), "raw")
		finally:
			frappe.db.set_single_value(
				"Iran Accounting Settings",
				{
					"default_amount_display_scale": prev_default,
					"voucher_gl_amount_scale": prev_print,
				},
			)
			frappe.clear_cache(doctype="Iran Accounting Settings")


class TestVoucherGLHierarchyBusinessFixture(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

		class _Gate:
			@staticmethod
			def skipTest(msg):
				raise unittest.SkipTest(msg)

		cls.ctx = ensure_hierarchy_business_fixture(ensure_print_company(_Gate()))
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_show_account_hierarchy = 1
		settings.voucher_gl_hierarchy_start_level = 2
		settings.voucher_gl_show_party_breakdown = 1
		settings.voucher_gl_show_dimension_breakdown = 1
		settings.voucher_gl_show_group_subtotals = 1
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

	def test_renderer_shows_1201_120123_and_splits(self):
		filters = {
			"company": self.ctx["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": self.ctx["hier_je"],
			"language": "fa",
			"layout": "Standard",
			"show_account_hierarchy": 1,
			"user_amount_scale": "Raw",
			"include_opening_entries": 1,
		}
		payload = enrich_print_payload(build_voucher_gl_print(filters), filters)
		html = render_voucher_package(filters)

		self.assertIn('lang="fa"', html)
		self.assertIn('dir="rtl"', html)
		self.assertIn("سند حسابداری", html)
		self.assertIn("1201", html)
		self.assertIn("موجودی مواد و کالا", html)
		self.assertIn("120123", html)
		self.assertIn("کنترل خرید داخلی", html)
		self.assertIn("hier-level", html)
		self.assertIn("hier-code", html)
		self.assertIn("تهیه‌کننده", html)
		self.assertIn("رئیس حسابداری", html)
		self.assertNotRegex(html, r"\b[KMBT]\b")
		self.assertNotRegex(html, r"(\{%|\{\{)")

		# Hierarchy on leaf rows
		leaf_rows = [r for r in payload["rows"] if r.get("account") == self.ctx["hier_leaf"]]
		self.assertTrue(leaf_rows)
		hier = leaf_rows[0].get("account_hierarchy") or []
		nums = [n.get("account_number") for n in hier]
		self.assertIn("1201", nums)
		self.assertIn("120123", nums)
		self.assertLess(nums.index("1201"), nums.index("120123"))

		nodes = payload.get("display_nodes") or []
		party_headers = [n for n in nodes if n.get("node_type") == "party_header"]
		# At least two party groups somewhere on the voucher (leaf or payable).
		self.assertGreaterEqual(len(party_headers), 2)

		# Dimension split: two cost centers represented on leaf lines
		leaf_lines = [
			n
			for n in nodes
			if n.get("node_type") == "gl_line" and n.get("account") == self.ctx["hier_leaf"]
		]
		ccs = set()
		for line in leaf_lines:
			for dim in line.get("dimensions") or []:
				if dim.get("fieldname") == "cost_center":
					ccs.add(dim.get("value"))
			row = line.get("row") or {}
			if row.get("cost_center"):
				ccs.add(row.get("cost_center"))
		self.assertGreaterEqual(len(ccs), 2)

		remarks = " ".join((n.get("description") or {}).get("main") or "" for n in leaf_lines)
		self.assertTrue("طرف الف" in remarks or "الف" in html)
		self.assertTrue("طرف ب" in remarks or "ب" in html)

		# Dimension group headers when enabled
		dim_headers = [n for n in nodes if n.get("node_type") == "dimension_header"]
		self.assertGreaterEqual(len(dim_headers) + len(ccs), 2)

		# Totals reconcile — max abs difference = 0
		self.assertEqual(flt(payload["totals"]["difference"], 9), 0)
		self.assertTrue(payload["totals"]["is_balanced"])
		self.assertAlmostEqual(
			flt(payload["totals"]["total_debit"]),
			flt(payload["totals"]["total_credit"]),
			places=6,
		)

		# Scale pass-through: Millions metadata label + scaled cells (feature still available)
		filters_m = dict(filters)
		filters_m["amount_scale"] = "Millions"
		filters_m["user_amount_scale"] = "Millions"
		html_m = render_voucher_package(filters_m)
		self.assertIn("مقیاس نمایش", html_m)
		self.assertIn("میلیون", html_m)
		self.assertNotRegex(html_m, r"\b[KMBT]\b")
		self.assertNotRegex(html_m, r"(\{%|\{\{)")

		# Account subtotal on 120123 should match leaf debit sum when multi-line
		account_subs = [n for n in nodes if n.get("node_type") == "account_subtotal"]
		leaf_debit = sum(flt(r.get("debit")) for r in leaf_rows)
		leaf_credit = sum(flt(r.get("credit")) for r in leaf_rows)
		if account_subs:
			for sub in account_subs:
				if sub.get("account") == self.ctx["hier_leaf"]:
					self.assertAlmostEqual(flt(sub.get("debit")), leaf_debit, places=6)
					self.assertAlmostEqual(flt(sub.get("credit")), leaf_credit, places=6)


if __name__ == "__main__":
	unittest.main()
