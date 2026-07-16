# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Unit tests: Voucher GL Print Raw amounts use #,### and currency order ریال 1,000,000."""

from __future__ import annotations

import re
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import (
	render_voucher_package,
)
from erpnext_extensions.iran_accounting.domain.amount_scale import (
	SCALE_MILLIONS,
	SCALE_RAW,
	SCALE_THOUSANDS,
	AmountScaleOptions,
	format_accounting_amount,
)
from erpnext_extensions.iran_accounting.tests.voucher_gl_business_dataset import (
	ensure_voucher_gl_business_dataset,
)


class TestVoucherGLAmountDisplay(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.ds = ensure_voucher_gl_business_dataset()
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_gl_amount_scale = "Raw"
		settings.voucher_gl_print_language = "Persian"
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		cls.voucher = next(v for v in cls.ds["vouchers"] if v["key"] == "v10_amount_raw")

	def _render(self, **extra) -> str:
		filters = {
			"company": self.ds["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": self.voucher["name"],
			"layout": "Standard",
			"amount_scale": "Raw",
			"user_amount_scale": "Raw",
			"language": "fa",
			"include_opening_entries": 1,
		}
		filters.update(extra)
		return render_voucher_package(filters)

	def test_raw_formatter_grouped_digits(self):
		cases = {
			0: "0",
			300_000: "300,000",
			700_000: "700,000",
			1_000_000: "1,000,000",
			125_000_000: "125,000,000",
			-700_000: "-700,000",
		}
		for value, number in cases.items():
			out = format_accounting_amount(
				value,
				AmountScaleOptions(scale=SCALE_RAW, currency="IRR", locale="fa", precision=0),
			)
			self.assertEqual(out["display_number"], number, value)
			self.assertIn(number, out["display"])
			self.assertTrue(out["display"].startswith("ریال ") or number.startswith("-"), out["display"])
			self.assertNotIn("هزار", out["display"])
			self.assertNotIn("میلیون", out["display"])
			self.assertIn('class="currency-label"', out["display_html"])
			self.assertIn('class="accounting-number"', out["display_html"])
			self.assertIn(number, out["display_html"])
			# Plain contract: currency then number
			self.assertRegex(out["display"], rf"^ریال {re.escape(number)}$")

	def test_html_contains_raw_line_and_total_amounts(self):
		html = self._render()
		self.assertIn("300,000", html)
		self.assertIn("700,000", html)
		self.assertIn("1,000,000", html)
		self.assertIn('class="currency-label"', html)
		self.assertIn('class="accounting-number"', html)
		# Numeric cells: currency before number in explicit wrappers
		self.assertRegex(
			html,
			r'currency-label[^>]*>ریال</span>\s*<span class="accounting-number"[^>]*>300,000</span>',
		)
		self.assertNotRegex(html, r'class="accounting-number"[^>]*>300000<')
		self.assertNotRegex(html, r"\d[\d,٫]*\s*هزار\s*ریال")
		self.assertNotRegex(html, r"\d[\d,٫]*\s*میلیون\s*ریال")
		# Codes only / titles in description
		self.assertIn('class="hier-code"', html)
		self.assertIn('class="hier-title"', html)
		self.assertIn('class="acct-code"', html)
		self.assertNotIn('class="hier-pair"', html.split('data-node="account_header"')[1][:800] if 'data-node="account_header"' in html else "")

	def test_code_column_vs_description(self):
		html = self._render()
		# First account header for expense hierarchy
		m = re.search(
			r'data-node="account_header">([\s\S]*?)</tr>',
			html,
		)
		self.assertIsNotNone(m)
		header = m.group(1)
		# Titles should be in remarks cell, not paired inside code cell as hier-pair
		self.assertIn("hier-code", header)
		self.assertIn("hier-title", header)
		self.assertIn("هزینه اجاره", header)
		codes = re.findall(r'class="acct-code"[^>]*>([^<]+)', header)
		for code in codes:
			self.assertTrue(code.isdigit() or code.replace("-", "").isalnum())

	def test_totals_align_table_present(self):
		html = self._render()
		self.assertIn("totals-align-table", html)
		self.assertIn('data-totals-align="1"', html)
		self.assertIn("جمع بدهکار", html)
		self.assertIn("جمع بستانکار", html)
		self.assertNotIn("جمع مبلغ جزء", html)
		# Footer must not put a total under مبلغ جزء
		footer = html.split('data-section="footer-totals"', 1)[-1]
		self.assertNotRegex(footer, r'col\.id == "line_amount"|جمع مبلغ جزء')
		# Amount column under line_amount in totals row must stay empty of accounting-amount
		m = re.search(
			r'data-totals-align="1">([\s\S]*?)</tr>',
			html,
		)
		self.assertIsNotNone(m)
		cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", m.group(1))
		# Standard: idx, account, remarks, line_amount, debit, credit
		self.assertGreaterEqual(len(cells), 6)
		line_cell = cells[3]
		self.assertNotIn("accounting-number", line_cell)

	def test_persian_amount_in_words_order(self):
		from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import (
			resolve_amount_in_words,
		)

		words = resolve_amount_in_words(1_000_000, "IRR", "fa")
		self.assertIn("یک میلیون ریال", words)
		self.assertNotIn("ریال یک میلیون", words)

	def test_explicit_scaled_still_available(self):
		thousands = format_accounting_amount(
			700_000,
			AmountScaleOptions(
				scale=SCALE_THOUSANDS, currency="IRR", locale="fa", precision=0, show_scale_label=True
			),
		)
		self.assertIn("هزار", thousands["display"])
		millions = format_accounting_amount(
			1_000_000,
			AmountScaleOptions(
				scale=SCALE_MILLIONS, currency="IRR", locale="fa", precision=0, show_scale_label=True
			),
		)
		self.assertIn("میلیون", millions["display"])


if __name__ == "__main__":
	unittest.main()
