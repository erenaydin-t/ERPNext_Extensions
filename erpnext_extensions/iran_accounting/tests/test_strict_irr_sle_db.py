# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_extensions.iran_accounting.rounding import SLE_MONETARY_FIELDS, amount_is_fractional
from erpnext_extensions.iran_accounting.sql_validation import (
	sql_find_fractional_irr_sle,
	sql_get_sle_rows,
)


class TestStrictIrrSleDb(FrappeTestCase):
	VOUCHER = "MAT-STE-2026-00102"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		import erpnext_extensions.iran_accounting  # noqa: F401

	def test_mat_ste_sle_monetary_fields_integer_in_db(self):
		if not frappe.db.exists("Stock Entry", self.VOUCHER):
			self.skipTest(f"{self.VOUCHER} not on site")
		company = frappe.db.get_value("Stock Entry", self.VOUCHER, "company")
		from erpnext_extensions.iran_accounting.diagnostics import _normalize_irr_stock_entry

		_normalize_irr_stock_entry(self.VOUCHER)
		frappe.db.commit()
		frac = sql_find_fractional_irr_sle("Stock Entry", self.VOUCHER, company)
		self.assertEqual(frac, [], msg=frac)
		for row in sql_get_sle_rows("Stock Entry", self.VOUCHER):
			for field in SLE_MONETARY_FIELDS:
				val = row.get(field)
				if val in (None, ""):
					continue
				self.assertFalse(amount_is_fractional(val, "IRR"), msg=f"{row.get('name')} {field}={val}")


if __name__ == "__main__":
	unittest.main()
