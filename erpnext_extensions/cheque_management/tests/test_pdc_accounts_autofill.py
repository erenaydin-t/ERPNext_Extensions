# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Backend auto-fill of PDC accounts from PDC Settings (no UI dependency).

Run from bench ``sites`` dir::

    ../env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_accounts_autofill -v
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frappe.exceptions import ValidationError

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import PostDatedCheque
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_SENT_TO_BANK,
)


def _pdc(**overrides) -> PostDatedCheque:
	p = PostDatedCheque.__new__(PostDatedCheque)
	# Minimal defaults; these tests call helper methods directly (no full validate()).
	base = {
		"company": "_TC",
		"cheque_direction": CHEQUE_DIRECTION_RECEIVABLE,
		"account_paid_to": None,
		"cheques_in_clearing_account": None,
		"workflow_state": None,
	}
	base.update(overrides)
	for k, v in base.items():
		setattr(p, k, v)
	return p


class TestPDCAccountsAutofill(unittest.TestCase):
	@staticmethod
	def _fake_frappe():
		def _throw(msg, *args, **kwargs):
			raise ValidationError(msg if isinstance(msg, str) else str(msg))

		return SimpleNamespace(_=lambda s: s, throw=_throw)

	def test_autofill_does_not_overwrite_user_values(self) -> None:
		p = _pdc(account_paid_to="USER-CIH", cheques_in_clearing_account="USER-CLR")
		settings = {
			"default_cheques_in_hand_account": "SET-CIH",
			"default_cheques_in_clearing_account": "SET-CLR",
		}
		with patch(
			"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._get_pdc_settings_for_company",
			return_value=settings,
		):
			p._autofill_accounts_from_pdc_settings_if_missing()
		self.assertEqual(p.account_paid_to, "USER-CIH")
		self.assertEqual(p.cheques_in_clearing_account, "USER-CLR")

	def test_autofill_receivable_account_paid_to_from_settings(self) -> None:
		p = _pdc(account_paid_to=None, cheque_direction=CHEQUE_DIRECTION_RECEIVABLE)
		settings = {"default_cheques_in_hand_account": "SET-CIH", "default_cheques_in_clearing_account": None}
		with patch(
			"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._get_pdc_settings_for_company",
			return_value=settings,
		):
			p._autofill_accounts_from_pdc_settings_if_missing()
		self.assertEqual(p.account_paid_to, "SET-CIH")

	def test_autofill_clearing_account_from_settings(self) -> None:
		p = _pdc(cheques_in_clearing_account=None)
		settings = {"default_cheques_in_hand_account": None, "default_cheques_in_clearing_account": "SET-CLR"}
		with patch(
			"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._get_pdc_settings_for_company",
			return_value=settings,
		):
			p._autofill_accounts_from_pdc_settings_if_missing()
		self.assertEqual(p.cheques_in_clearing_account, "SET-CLR")

	def test_receivable_in_hand_account_required(self) -> None:
		p = _pdc(account_paid_to=None, cheque_direction=CHEQUE_DIRECTION_RECEIVABLE)
		with (
			patch(
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.frappe",
				self._fake_frappe(),
			),
			self.assertRaises(ValidationError),
		):
			p._validate_receivable_cheques_in_hand_account_required()

	def test_payable_does_not_require_in_hand_account(self) -> None:
		p = _pdc(account_paid_to=None, cheque_direction=CHEQUE_DIRECTION_PAYABLE)
		p._validate_receivable_cheques_in_hand_account_required()

	def test_sent_to_bank_requires_clearing_account(self) -> None:
		p = _pdc(workflow_state=WORKFLOW_SENT_TO_BANK, cheques_in_clearing_account=None)
		# Force resolver to yield empty clearing.
		with patch(
			"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.resolve_pdc_accounts_for_journal",
			return_value={"cheques_in_clearing": None},
		):
			with (
				patch(
					"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.frappe",
					self._fake_frappe(),
				),
				self.assertRaises(ValidationError),
			):
				p._validate_sent_to_bank_workflow_state()

	def test_sent_to_bank_allows_when_clearing_present(self) -> None:
		p = _pdc(workflow_state=WORKFLOW_SENT_TO_BANK, cheques_in_clearing_account="DOC-CLR")
		with patch(
			"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.resolve_pdc_accounts_for_journal",
			return_value={"cheques_in_clearing": "DOC-CLR"},
		):
			p._validate_sent_to_bank_workflow_state()


if __name__ == "__main__":
	unittest.main()

