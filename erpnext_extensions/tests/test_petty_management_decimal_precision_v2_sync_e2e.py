# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Integration: Petty Management DECIMAL(30,9) survives metadata sync and is idempotent (v2)."""

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.patches.post_model_sync.expand_petty_management_decimal_precision_v2 import (
	execute as expand_petty_management_decimal_precision_v2_execute,
)
from erpnext_extensions.patches.pre_model_sync.set_petty_management_decimal_metadata_v2 import (
	execute as set_petty_management_decimal_metadata_v2_execute,
)
from erpnext_extensions.petty_management_decimal_precision_v2 import PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE

TARGET_COLUMNS: dict[str, tuple[str, ...]] = {
	f"tab{doctype}": fields for doctype, fields in PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE.items()
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


class TestPettyManagementDecimalPrecisionV2SyncE2E(unittest.TestCase):
	def test_patch_and_updatedb_are_idempotent(self):
		set_petty_management_decimal_metadata_v2_execute()
		expand_petty_management_decimal_precision_v2_execute()

		for table, columns in TARGET_COLUMNS.items():
			for column in columns:
				precision, scale, column_type = _read_column(table, column)
				self.assertEqual(
					(precision, scale, column_type),
					(30, 9, "decimal(30,9)"),
					f"{table}.{column}",
				)

		target_property_setters = {
			(row.doc_type, row.field_name): row.value
			for row in frappe.get_all(
				"Property Setter",
				filters={
					"doc_type": ("in", list(PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE)),
					"property": "length",
					"field_name": (
						"in",
						sorted({f for fields in PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE.values() for f in fields}),
					),
				},
				fields=["doc_type", "field_name", "value"],
			)
		}
		for doctype, fields in PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE.items():
			for fieldname in fields:
				self.assertEqual(
					target_property_setters.get((doctype, fieldname)),
					"30",
					f"{doctype}.{fieldname}",
				)

		for doctype in PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE:
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

		before_second_run = {
			(table, column): _read_column(table, column)
			for table, cols in TARGET_COLUMNS.items()
			for column in cols
		}
		set_petty_management_decimal_metadata_v2_execute()
		expand_petty_management_decimal_precision_v2_execute()
		after_second_run = {
			(table, column): _read_column(table, column)
			for table, cols in TARGET_COLUMNS.items()
			for column in cols
		}
		self.assertEqual(before_second_run, after_second_run)

		pe_precision, pe_scale, pe_type = _read_column("tabPayment Entry", "paid_amount")
		if pe_precision is not None:
			self.assertEqual((pe_precision, pe_scale, pe_type), (21, 9, "decimal(21,9)"))
