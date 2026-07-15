# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Shared amount-scale + voucher GL hierarchy unit coverage."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_hierarchy import (
	batch_resolve_account_hierarchies,
	group_print_rows,
	resolve_account_hierarchy_for_number,
	build_account_number_index,
)
from erpnext_extensions.iran_accounting.domain.amount_scale import (
	SCALE_AUTO,
	SCALE_BILLIONS,
	SCALE_MILLIONS,
	SCALE_RAW,
	SCALE_THOUSANDS,
	SCALE_TRILLIONS,
	format_accounting_amount,
	AmountScaleOptions,
	effective_scale,
	normalize_amount_scale,
)


class TestAmountScale(unittest.TestCase):
	def test_normalize_and_divisors(self):
		self.assertEqual(normalize_amount_scale("Millions"), SCALE_MILLIONS)
		self.assertEqual(normalize_amount_scale("Use Default"), "use_default")
		self.assertEqual(effective_scale(SCALE_AUTO, 12_000_000), SCALE_MILLIONS)
		self.assertEqual(effective_scale(SCALE_AUTO, 500), SCALE_RAW)

	def test_twelve_million_scales_fa(self):
		value = 12_000_000
		raw = format_accounting_amount(
			value, AmountScaleOptions(scale=SCALE_RAW, currency="IRR", locale="fa", precision=0)
		)
		self.assertIn("12,000,000", raw["display"].replace("\u066c", ",").replace("٬", ","))

		thousands = format_accounting_amount(
			value,
			AmountScaleOptions(
				scale=SCALE_THOUSANDS, currency="IRR", locale="fa", precision=0, show_scale_label=True
			),
		)
		self.assertEqual(thousands["scale"], SCALE_THOUSANDS)
		self.assertIn("هزار", thousands["display"])
		self.assertNotIn(" K", thousands["display"])
		self.assertNotIn("K ", thousands["display"])

		millions = format_accounting_amount(
			value,
			AmountScaleOptions(
				scale=SCALE_MILLIONS, currency="IRR", locale="fa", precision=0, show_scale_label=True
			),
		)
		self.assertIn("میلیون", millions["display"])
		self.assertTrue(abs(millions["scaled"] - 12) < 1e-9)

		billions = format_accounting_amount(
			value,
			AmountScaleOptions(
				scale=SCALE_BILLIONS, currency="IRR", locale="fa", precision=3, show_scale_label=True
			),
		)
		self.assertIn("میلیارد", billions["display"])
		self.assertAlmostEqual(billions["scaled"], 0.012, places=6)

	def test_english_labels_not_kmb(self):
		out = format_accounting_amount(
			12_000_000,
			AmountScaleOptions(
				scale=SCALE_MILLIONS, currency="IRR", locale="en", precision=0, show_scale_label=True
			),
		)
		self.assertIn("million", out["display"].lower())
		self.assertNotRegex(out["display"], r"\bM\b")

	def test_zero_negative_large(self):
		z = format_accounting_amount(0, AmountScaleOptions(scale=SCALE_RAW, currency="IRR"))
		self.assertEqual(z["raw"], 0)
		neg = format_accounting_amount(
			-1_500_000,
			AmountScaleOptions(scale=SCALE_MILLIONS, locale="en", precision=1, show_scale_label=True),
		)
		self.assertLess(neg["scaled"], 0)
		huge = format_accounting_amount(
			1e13,
			AmountScaleOptions(scale=SCALE_AUTO, locale="en", precision=2, show_scale_label=True),
		)
		self.assertEqual(huge["scale"], SCALE_TRILLIONS)


class TestAccountHierarchy(unittest.TestCase):
	def test_prefix_hierarchy_120123_from_level_2(self):
		accounts = [
			{"name": "A-12", "account_number": "12", "account_name": "دارایی‌ها"},
			{"name": "A-1201", "account_number": "1201", "account_name": "موجودی مواد و کالا"},
			{"name": "A-120123", "account_number": "120123", "account_name": "کنترل خرید داخلی"},
		]
		levels = [
			{"sequence": 2, "code_length": 4, "title": "GL", "title_fa": "کل"},
			{"sequence": 3, "code_length": 6, "title": "SL", "title_fa": "معین"},
		]
		index = build_account_number_index(accounts)
		hierarchy = resolve_account_hierarchy_for_number(
			"120123",
			levels=levels,
			number_index=index,
			leaf_account=accounts[2],
		)
		self.assertEqual([n["account_number"] for n in hierarchy], ["1201", "120123"])
		self.assertEqual(hierarchy[0]["account_name"], "موجودی مواد و کالا")
		self.assertEqual(hierarchy[1]["account_name"], "کنترل خرید داخلی")
		# Level 1 / root omitted.
		self.assertNotIn("12", [n["account_number"] for n in hierarchy if n["account_number"] == "12"])

	def test_no_duplicate_levels(self):
		accounts = [{"name": "X", "account_number": "1201", "account_name": "کل"}]
		levels = [
			{"sequence": 2, "code_length": 4, "title": "a"},
			{"sequence": 3, "code_length": 4, "title": "b"},
		]
		hierarchy = resolve_account_hierarchy_for_number(
			"1201",
			levels=levels,
			number_index=build_account_number_index(accounts),
			leaf_account=accounts[0],
		)
		self.assertEqual(len(hierarchy), 1)

	def test_missing_account_number_fallback(self):
		with patch(
			"erpnext_extensions.iran_accounting.account_explorer.voucher_gl_hierarchy.load_company_accounts",
			return_value=[{"name": "Leaf", "account_number": "", "account_name": "بدون کد"}],
		), patch(
			"erpnext_extensions.iran_accounting.account_explorer.voucher_gl_hierarchy.get_enabled_levels",
			return_value=[],
		):
			cache = batch_resolve_account_hierarchies("_Test Company", {"Leaf"}, start_level=2)
		self.assertEqual(cache["Leaf"][0]["account_name"], "بدون کد")

	def test_party_and_dimension_split(self):
		rows = [
			{
				"account": "A1",
				"account_code": "120123",
				"account_name": "X",
				"account_hierarchy": [{"account_number": "120123", "account_name": "X"}],
				"party_type": "Supplier",
				"party": "S1",
				"party_name": "شرکت الف",
				"debit": 100,
				"credit": 0,
				"cost_center": "CC1",
				"project": "",
				"dimensions": {
					"cost_center": {"value": "CC1", "title": "دفتر", "label": "Cost Center"}
				},
				"remarks": "line1",
			},
			{
				"account": "A1",
				"account_code": "120123",
				"account_name": "X",
				"account_hierarchy": [{"account_number": "120123", "account_name": "X"}],
				"party_type": "Supplier",
				"party": "S2",
				"party_name": "شرکت ب",
				"debit": 50,
				"credit": 0,
				"cost_center": "CC2",
				"project": "",
				"dimensions": {
					"cost_center": {"value": "CC2", "title": "کارخانه", "label": "Cost Center"}
				},
				"remarks": "line2",
			},
		]
		nodes = group_print_rows(rows, show_party=True, show_dimensions=True, show_subtotals=True)
		party_headers = [n for n in nodes if n["node_type"] == "party_header"]
		self.assertEqual(len(party_headers), 2)
		lines = [n for n in nodes if n["node_type"] == "gl_line"]
		self.assertEqual(len(lines), 2)
		# Subtotals reconcile
		account_sub = [n for n in nodes if n["node_type"] == "account_subtotal"]
		self.assertEqual(len(account_sub), 1)
		self.assertEqual(flt(account_sub[0]["debit"]), 150)
		self.assertEqual(flt(account_sub[0]["credit"]), 0)

	def test_empty_party_omitted(self):
		rows = [
			{
				"account": "A1",
				"account_code": "1",
				"account_name": "X",
				"account_hierarchy": [],
				"party_type": "",
				"party": "",
				"party_name": "",
				"debit": 10,
				"credit": 0,
				"cost_center": "",
				"project": "",
				"dimensions": {},
				"remarks": "",
			}
		]
		nodes = group_print_rows(rows, show_party=True, show_dimensions=True, show_subtotals=False)
		self.assertFalse(any(n["node_type"] == "party_header" for n in nodes))


if __name__ == "__main__":
	unittest.main()
