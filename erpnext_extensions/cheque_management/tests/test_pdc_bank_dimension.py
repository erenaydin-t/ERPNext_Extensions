# Copyright (c) 2026, ERPNext Extensions contributors
# For license information, please see license.txt

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from erpnext_extensions.cheque_management.pdc_bank_dimension import (
	_row_account_needs_bank_dimension,
	apply_pdc_bank_dimension_to_je_row,
	build_je_account_row_from_pdc_payload,
	resolve_pdc_bank_dimension_value,
)


class TestPDCBankDimension(unittest.TestCase):
	def test_bank_account_set_dimension_empty_returns_none(self) -> None:
		doc = SimpleNamespace(bank_account="BA-1", bank_dimension=None)
		with patch(
			"erpnext_extensions.cheque_management.pdc_bank_dimension.get_bank_accounting_dimension_fieldname",
			return_value="bank_dimension",
		):
			self.assertIsNone(resolve_pdc_bank_dimension_value(doc))

	def test_resolve_reads_pdc_bank_dimension_field_only(self) -> None:
		doc = SimpleNamespace(bank_account="BA-1", bank_dimension="BANK-FROM-PDC")
		with patch(
			"erpnext_extensions.cheque_management.pdc_bank_dimension.get_bank_accounting_dimension_fieldname",
			return_value="bank_dimension",
		):
			self.assertEqual(resolve_pdc_bank_dimension_value(doc), "BANK-FROM-PDC")

	def test_bank_account_set_dimension_empty_no_apply_on_eligible_row(self) -> None:
		doc = SimpleNamespace(bank_account="BA-1", bank_dimension=None, company="_TC")
		with (
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.get_bank_accounting_dimension_fieldname",
				return_value="bank_dimension",
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension._pdc_bank_gl_account",
				return_value="BANK-GL",
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension._get_pdc_settings_for_company",
				return_value={},
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.resolve_pdc_accounts_for_journal",
				return_value={"cheques_in_clearing": "CLR-GL"},
			),
		):
			clr = apply_pdc_bank_dimension_to_je_row(doc, {"account": "CLR-GL", "bank_dimension": "stale"})
			self.assertNotIn("bank_dimension", clr)
			bgl = apply_pdc_bank_dimension_to_je_row(doc, {"account": "BANK-GL"})
			self.assertNotIn("bank_dimension", bgl)

	def test_dimension_set_applied_on_bank_gl_and_clearing(self) -> None:
		doc = SimpleNamespace(bank_dimension="BANK-X", company="_TC")
		with (
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.get_bank_accounting_dimension_fieldname",
				return_value="bank_dimension",
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension._pdc_bank_gl_account",
				return_value="BANK-GL",
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension._get_pdc_settings_for_company",
				return_value={},
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.resolve_pdc_accounts_for_journal",
				return_value={"cheques_in_clearing": "CLR-GL"},
			),
		):
			clr = apply_pdc_bank_dimension_to_je_row(doc, {"account": "CLR-GL"})
			self.assertEqual(clr.get("bank_dimension"), "BANK-X")
			bgl = apply_pdc_bank_dimension_to_je_row(doc, {"account": "BANK-GL"})
			self.assertEqual(bgl.get("bank_dimension"), "BANK-X")

	def test_dimension_set_not_applied_on_cih_protested_ar(self) -> None:
		doc = SimpleNamespace(bank_dimension="BANK-X", company="_TC")
		with (
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.get_bank_accounting_dimension_fieldname",
				return_value="bank_dimension",
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension._pdc_bank_gl_account",
				return_value="BANK-GL",
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension._get_pdc_settings_for_company",
				return_value={},
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.resolve_pdc_accounts_for_journal",
				return_value={"cheques_in_clearing": "CLR-GL"},
			),
		):
			for acc in ("CIH-GL", "PROTEST-GL", "AR-GL", "AP-GL", "POOL-GL"):
				row = apply_pdc_bank_dimension_to_je_row(doc, {"account": acc})
				self.assertNotIn("bank_dimension", row, acc)

	def test_build_row_strips_party_on_clear_bank_only(self) -> None:
		doc = SimpleNamespace(bank_account="BA-1", company="_TC")
		row = {
			"account": "BANK-GL",
			"debit_in_account_currency": 100,
			"party_type": "Customer",
			"party": "C-1",
		}
		with (
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.get_bank_accounting_dimension_fieldname",
				return_value=None,
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.apply_pdc_bank_dimension_to_je_row",
				side_effect=lambda _d, e: e,
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.get_accounting_dimensions",
				return_value=[],
			),
		):
			entry = build_je_account_row_from_pdc_payload(
				doc, row, bank_gl_party_strip="BANK-GL"
			)
			self.assertNotIn("party_type", entry)
			self.assertNotIn("party", entry)

	def test_payload_stale_bank_dimension_not_copied_when_doc_empty(self) -> None:
		doc = SimpleNamespace(bank_dimension=None, company="_TC")
		row = {
			"account": "CLR-GL",
			"debit_in_account_currency": 100,
			"bank_dimension": "from-payload",
		}
		with (
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.get_bank_accounting_dimension_fieldname",
				return_value="bank_dimension",
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension._pdc_bank_gl_account",
				return_value="BANK-GL",
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension._get_pdc_settings_for_company",
				return_value={},
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.resolve_pdc_accounts_for_journal",
				return_value={"cheques_in_clearing": "CLR-GL"},
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.get_accounting_dimensions",
				return_value=["bank_dimension"],
			),
		):
			entry = build_je_account_row_from_pdc_payload(doc, row)
			self.assertNotIn("bank_dimension", entry)

	def test_row_account_needs_bank_dimension(self) -> None:
		doc = SimpleNamespace(company="_TC", cheques_in_clearing_account="CLR")
		with (
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension._pdc_bank_gl_account",
				return_value="BGL",
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension._get_pdc_settings_for_company",
				return_value={},
			),
			patch(
				"erpnext_extensions.cheque_management.pdc_bank_dimension.resolve_pdc_accounts_for_journal",
				return_value={"cheques_in_clearing": "CLR"},
			),
		):
			self.assertTrue(_row_account_needs_bank_dimension(doc, "CLR"))
			self.assertTrue(_row_account_needs_bank_dimension(doc, "BGL"))
			self.assertFalse(_row_account_needs_bank_dimension(doc, "CIH"))


if __name__ == "__main__":
	unittest.main()
