# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Integration: Payment Entry DECIMAL(30,9) schema + large IRR amount regression."""

from __future__ import annotations

import unittest
from decimal import Decimal

import frappe
from frappe.utils import cint, nowdate

from erpnext_extensions.patches.post_model_sync.expand_payment_entry_amount_precision import (
	execute as expand_payment_entry_amount_precision_execute,
)
from erpnext_extensions.patches.pre_model_sync.set_payment_entry_amount_decimal_metadata import (
	execute as set_payment_entry_amount_decimal_metadata_execute,
)
from erpnext_extensions.payment_entry_decimal_precision import (
	EXCLUDED_RATE_FIELDS_BY_DOCTYPE,
	EXCLUDED_VIRTUAL_FIELDS_BY_DOCTYPE,
	PAYMENT_ENTRY_FIELDS_BY_DOCTYPE,
	assert_schema_targets,
)

LARGE_IRR = Decimal("1682808518031")
LARGE_IRR_FRACTION = Decimal("1682808518031.123456789")

TARGET_COLUMNS: dict[str, tuple[str, ...]] = {
	f"tab{doctype}": fields for doctype, fields in PAYMENT_ENTRY_FIELDS_BY_DOCTYPE.items()
}


def _read_column(table: str, column: str) -> tuple[int | None, int | None, str | None]:
	db_name = frappe.db.sql("SELECT DATABASE()")[0][0]
	row = frappe.db.sql(
		"""
		SELECT NUMERIC_PRECISION, NUMERIC_SCALE, COLUMN_TYPE
		FROM INFORMATION_SCHEMA.COLUMNS
		WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
		""",
		(db_name, table, column),
		as_dict=True,
	)
	if not row:
		return None, None, None
	return (
		row[0].get("NUMERIC_PRECISION"),
		row[0].get("NUMERIC_SCALE"),
		row[0].get("COLUMN_TYPE"),
	)


def _as_decimal(value) -> Decimal:
	return Decimal(str(value))


class TestPaymentEntryDecimalPrecisionSyncE2E(unittest.TestCase):
	def test_patch_updatedb_and_schema_guard(self):
		set_payment_entry_amount_decimal_metadata_execute()
		expand_payment_entry_amount_precision_execute()

		for table, columns in TARGET_COLUMNS.items():
			for column in columns:
				precision, scale, column_type = _read_column(table, column)
				self.assertEqual(
					(precision, scale, column_type),
					(30, 9, "decimal(30,9)"),
					f"{table}.{column}",
				)

		for doctype, fields in PAYMENT_ENTRY_FIELDS_BY_DOCTYPE.items():
			for fieldname in fields:
				value = frappe.db.get_value(
					"Property Setter",
					{
						"doc_type": doctype,
						"field_name": fieldname,
						"property": "length",
						"doctype_or_field": "DocField",
					},
					"value",
				)
				self.assertEqual(value, "30", f"{doctype}.{fieldname}")

		for doctype in PAYMENT_ENTRY_FIELDS_BY_DOCTYPE:
			frappe.clear_cache(doctype=doctype)
			frappe.db.updatedb(doctype)

		for table, columns in TARGET_COLUMNS.items():
			for column in columns:
				precision, scale, column_type = _read_column(table, column)
				self.assertEqual(
					(precision, scale, column_type),
					(30, 9, "decimal(30,9)"),
					f"sync {table}.{column}",
				)

		before = {
			(table, column): _read_column(table, column)
			for table, cols in TARGET_COLUMNS.items()
			for column in cols
		}
		set_payment_entry_amount_decimal_metadata_execute()
		expand_payment_entry_amount_precision_execute()
		after = {
			(table, column): _read_column(table, column)
			for table, cols in TARGET_COLUMNS.items()
			for column in cols
		}
		self.assertEqual(before, after)
		assert_schema_targets()

		# Exchange / tax rates remain default width (non-targets).
		for doctype, fields in EXCLUDED_RATE_FIELDS_BY_DOCTYPE.items():
			table = f"tab{doctype}"
			for column in fields:
				precision, scale, column_type = _read_column(table, column)
				if precision is None:
					continue
				self.assertEqual(
					(precision, scale, column_type),
					(21, 9, "decimal(21,9)"),
					f"{table}.{column}",
				)

	def test_allowlist_covers_every_stored_currency_field(self):
		"""Every non-virtual Currency field on audited PE DocTypes must be allowlisted."""
		for doctype in PAYMENT_ENTRY_FIELDS_BY_DOCTYPE:
			meta = frappe.get_meta(doctype, cached=False)
			allowlisted = set(PAYMENT_ENTRY_FIELDS_BY_DOCTYPE[doctype])
			virtual = set(EXCLUDED_VIRTUAL_FIELDS_BY_DOCTYPE.get(doctype, ()))
			for df in meta.fields:
				if df.fieldtype != "Currency":
					continue
				if cint(getattr(df, "is_virtual", 0)) or df.fieldname in virtual:
					self.assertNotIn(df.fieldname, allowlisted, f"virtual {doctype}.{df.fieldname}")
					continue
				self.assertIn(
					df.fieldname,
					allowlisted,
					f"missing Currency field {doctype}.{df.fieldname} from allowlist",
				)

	def test_large_irr_draft_payment_entry_round_trip(self):
		set_payment_entry_amount_decimal_metadata_execute()
		expand_payment_entry_amount_precision_execute()

		company = "_Test Company"
		if not frappe.db.exists("Company", company):
			self.skipTest("Missing _Test Company")

		supplier = "_Test Supplier"
		if not frappe.db.exists("Supplier", supplier):
			self.skipTest("Missing _Test Supplier")

		paid_from = "_Test Bank - _TC"
		paid_to = "Creditors - _TC"
		if not frappe.db.exists("Account", paid_from) or not frappe.db.exists("Account", paid_to):
			self.skipTest("Missing test bank/creditors accounts")

		expense_account = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Expense Account", "is_group": 0},
			"name",
		) or frappe.db.get_value("Account", {"company": company, "is_group": 0}, "name")

		amount = float(LARGE_IRR)
		pe = frappe.new_doc("Payment Entry")
		pe.company = company
		pe.payment_type = "Pay"
		pe.party_type = "Supplier"
		pe.party = supplier
		pe.paid_from = paid_from
		pe.paid_to = paid_to
		pe.posting_date = nowdate()
		pe.reference_no = "PE-DEC-LARGE"
		pe.reference_date = nowdate()
		pe.source_exchange_rate = 1
		pe.target_exchange_rate = 1
		# Populate every major PE monetary amount field with the failing IRR value.
		for field in PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Payment Entry"]:
			pe.set(field, amount)
		pe.append(
			"references",
			{
				"reference_doctype": "Purchase Invoice",
				"reference_name": "DUMMY-PI-LARGE-IRR",
				"total_amount": amount,
				"outstanding_amount": amount,
				"allocated_amount": amount,
				"exchange_gain_loss": amount,
				"payment_term_outstanding": amount,
			},
		)
		if expense_account:
			pe.append("deductions", {"account": expense_account, "cost_center": None, "amount": amount})
			pe.append(
				"taxes",
				{
					"charge_type": "Actual",
					"account_head": expense_account,
					"tax_amount": amount,
					"total": amount,
					"base_tax_amount": amount,
					"base_total": amount,
					"net_amount": amount,
					"base_net_amount": amount,
				},
			)
			pe.append(
				"tax_withholding_entries",
				{
					"taxable_amount": amount,
					"withholding_amount": amount,
				},
			)
		pe.flags.ignore_mandatory = True
		pe.flags.ignore_validate = True
		pe.flags.ignore_links = True
		pe.insert(ignore_permissions=True)
		frappe.db.commit()

		reloaded = frappe.get_doc("Payment Entry", pe.name)
		for field in PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Payment Entry"]:
			self.assertEqual(_as_decimal(reloaded.get(field)), LARGE_IRR, field)
			raw = frappe.db.sql(
				f"SELECT `{field}` FROM `tabPayment Entry` WHERE name=%s",
				pe.name,
			)[0][0]
			self.assertEqual(_as_decimal(raw), LARGE_IRR, f"sql {field}")
			self.assertNotIn("e", str(raw).lower())

		self.assertEqual(_as_decimal(reloaded.references[0].allocated_amount), LARGE_IRR)
		self.assertEqual(_as_decimal(reloaded.references[0].total_amount), LARGE_IRR)
		self.assertEqual(_as_decimal(reloaded.references[0].outstanding_amount), LARGE_IRR)
		if reloaded.deductions:
			self.assertEqual(_as_decimal(reloaded.deductions[0].amount), LARGE_IRR)
		if reloaded.taxes:
			self.assertEqual(_as_decimal(reloaded.taxes[0].tax_amount), LARGE_IRR)
		if reloaded.get("tax_withholding_entries"):
			self.assertEqual(
				_as_decimal(reloaded.tax_withholding_entries[0].withholding_amount),
				LARGE_IRR,
			)

		# Fractional DECIMAL(30,9) round-trip on paid_amount.
		# Avoid Python float on write/read — large 13+9 values exceed float mantissa.
		frappe.db.sql(
			"UPDATE `tabPayment Entry` SET paid_amount=%s WHERE name=%s",
			(str(LARGE_IRR_FRACTION), pe.name),
		)
		frappe.db.commit()
		raw_frac = frappe.db.sql(
			"SELECT CAST(paid_amount AS CHAR) FROM `tabPayment Entry` WHERE name=%s",
			pe.name,
		)[0][0]
		self.assertEqual(_as_decimal(raw_frac), LARGE_IRR_FRACTION)

		# Cleanup draft
		frappe.delete_doc("Payment Entry", pe.name, force=True, ignore_permissions=True)
		frappe.db.commit()
