# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Unit tests for Payable PDC ↔ Cheque Leaf ownership validation.

Run from bench root::

    bench --site development.localhost run-tests --module erpnext_extensions.cheque_management.tests.test_pdc_cheque_leaf_validation
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

import frappe

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_pdc_assert_cheque_leaf_usable_by_pdc,
)


def _row(**kwargs):
	base = {
		"status": "Available",
		"reserved_by_pdc": "",
		"linked_post_dated_cheque": "",
		"company": "C1",
		"bank_account": "BA1",
		"cheque_number": "1001",
	}
	base.update(kwargs)
	return SimpleNamespace(**base)


class TestPDCAssertChequeLeafUsableByPDC(FrappeTestCase):
	def test_available_allowed(self):
		_pdc_assert_cheque_leaf_usable_by_pdc(_row(status="Available"), "PDC-A")

	def test_reserved_same_pdc_allowed(self):
		_pdc_assert_cheque_leaf_usable_by_pdc(
			_row(status="Reserved", reserved_by_pdc="PDC-A"), "PDC-A"
		)

	def test_reserved_other_pdc_blocked(self):
		with self.assertRaises(ValidationError):
			_pdc_assert_cheque_leaf_usable_by_pdc(
				_row(status="Reserved", reserved_by_pdc="PDC-B"), "PDC-A"
			)

	def test_used_same_pdc_allowed(self):
		_pdc_assert_cheque_leaf_usable_by_pdc(
			_row(status="Used", linked_post_dated_cheque="PDC-A"), "PDC-A"
		)

	def test_used_other_pdc_blocked(self):
		with self.assertRaises(ValidationError):
			_pdc_assert_cheque_leaf_usable_by_pdc(
				_row(status="Used", linked_post_dated_cheque="PDC-B"), "PDC-A"
			)

	def test_void_blocked(self):
		with self.assertRaises(ValidationError):
			_pdc_assert_cheque_leaf_usable_by_pdc(_row(status="Void"), "PDC-A")


class TestPDCValidateChequeLeafIntegrationUsedSamePDC(FrappeTestCase):
	"""Registered → Issued path: submitted PDC, leaf already Used by this PDC."""

	def test_used_leaf_linked_to_same_pdc_passes_validate(self):
		from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
			PostDatedCheque,
		)

		pdc = frappe.get_doc(
			{
				"doctype": "Post Dated Cheque",
				"name": "PDC-TEST-001",
				"cheque_direction": "Payable",
				"company": "C1",
				"bank_account": "BA1",
				"cheque_no": "1001",
				"cheque_leaf": "LEAF-1",
				"docstatus": 1,
			}
		)
		row = _row(status="Used", linked_post_dated_cheque="PDC-TEST-001")
		with patch(
			"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._pdc_get_cheque_leaf_row_for_update",
			return_value=row,
		):
			PostDatedCheque._validate_cheque_leaf_integration(pdc)

	def test_used_leaf_linked_to_other_pdc_fails_validate(self):
		from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
			PostDatedCheque,
		)

		pdc = frappe.get_doc(
			{
				"doctype": "Post Dated Cheque",
				"name": "PDC-TEST-002",
				"cheque_direction": "Payable",
				"company": "C1",
				"bank_account": "BA1",
				"cheque_no": "1001",
				"cheque_leaf": "LEAF-1",
				"docstatus": 1,
			}
		)
		row = _row(status="Used", linked_post_dated_cheque="PDC-OTHER")
		with patch(
			"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._pdc_get_cheque_leaf_row_for_update",
			return_value=row,
		):
			with self.assertRaises(ValidationError):
				PostDatedCheque._validate_cheque_leaf_integration(pdc)

