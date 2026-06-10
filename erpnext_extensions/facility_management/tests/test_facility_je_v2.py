# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

from erpnext_extensions.facility_management.facility_accounting import (
	_planned_receipt_rows,
	_planned_repayment_rows,
)
from erpnext_extensions.facility_management.facility_settings_doc import resolve_account, resolve_dimension
from erpnext_extensions.facility_management.facility_templates import (
	build_template_context,
	render_facility_template,
)
from frappe.utils import flt


class TestFacilityPlannedRows(unittest.TestCase):
	def test_receipt_rows_with_profit(self):
		from decimal import Decimal

		rows = _planned_receipt_rows(Decimal("8000"), Decimal("1000"))
		self.assertEqual(len(rows), 3)
		self.assertEqual(rows[0], (Decimal("8000"), "debit"))
		self.assertEqual(rows[1], (Decimal("1000"), "debit"))
		self.assertEqual(rows[2], (Decimal("9000"), "credit"))

	def test_receipt_rows_profit_zero(self):
		from decimal import Decimal

		rows = _planned_receipt_rows(Decimal("8000"), Decimal("0"))
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[-1], (Decimal("8000"), "credit"))

	def test_repayment_excel_model_order(self):
		from decimal import Decimal

		rows = _planned_repayment_rows(Decimal("800"), Decimal("140"), Decimal("60"))
		self.assertEqual(rows[0], (Decimal("1000"), "credit"))
		self.assertEqual(len(rows), 4)

	def test_repayment_skip_zero_lines(self):
		from decimal import Decimal

		rows = _planned_repayment_rows(Decimal("800"), Decimal("0"), Decimal("60"))
		self.assertEqual(len(rows), 3)
		self.assertEqual(rows[0][0], Decimal("860"))


class TestFacilityTemplates(unittest.TestCase):
	def test_placeholder_render(self):
		class F:
			name = "FAC-1"
			facility_name = "Test"
			company = "C"
			bank = "B1"
			contract_date = "2026-01-01"
			receive_date = None
			principal_amount = 8000
			profit_amount = 1000
			total_liability_amount = 9000
			installment_count = 12

		ctx = build_template_context(F())
		out = render_facility_template("{facility_number} واریز تسهیلات", ctx)
		self.assertEqual(out, "FAC-1 واریز تسهیلات")

	def test_unknown_placeholder_empty(self):
		out = render_facility_template("{not_a_real_key}", {"facility_number": "X"})
		self.assertEqual(out, "")


class TestFacilityResolvePriority(unittest.TestCase):
	def test_account_priority(self):
		class Rep:
			bank_account = "REP-BANK"

			def get(self, k):
				return getattr(self, k, None)

		class Fac:
			bank_account = "FAC-BANK"

			def get(self, k):
				return getattr(self, k, None)

		class Settings:
			default_bank_account = "SET-BANK"

			def get(self, k):
				return getattr(self, k, None)

		self.assertEqual(
			resolve_account("bank_account", repayment=Rep(), facility=Fac(), settings=Settings()),
			"REP-BANK",
		)
		self.assertEqual(
			resolve_account("bank_account", repayment=None, facility=Fac(), settings=Settings()),
			"FAC-BANK",
		)
		self.assertEqual(
			resolve_account("bank_account", repayment=None, facility=None, settings=Settings()),
			"SET-BANK",
		)

	def test_dimension_priority(self):
		class Rep:
			department = "REP-DEPT"

			def get(self, k):
				return getattr(self, k, None)

		class Fac:
			department = "FAC-DEPT"

			def get(self, k):
				return getattr(self, k, None)

		self.assertEqual(
			resolve_dimension("department", repayment=Rep(), facility=Fac(), settings=None),
			"REP-DEPT",
		)


class TestDecimalMetadata(unittest.TestCase):
	def test_precision_targets(self):
		from erpnext_extensions.facility_management.facility_precision import (
			TARGET_PRECISION,
			TARGET_SCALE,
		)

		self.assertEqual(TARGET_PRECISION, 30)
		self.assertEqual(TARGET_SCALE, 9)
