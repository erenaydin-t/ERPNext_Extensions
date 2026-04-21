# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""PDC Settings policy enforcement (endorsement + Sayad).

Run from bench ``sites`` dir::

    ../env/bin/python -m unittest erpnext_extensions.cheque_management.tests.test_pdc_settings_policy -v
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError

import erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque as pdc_mod
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	PostDatedCheque,
	_pdc_company_policy_flags,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_ENDORSED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
)


def _init_frappe():
	if not getattr(frappe.local, "site", None):
		frappe.init(site="development.localhost")
		frappe.connect()


def _bare_pdc() -> PostDatedCheque:
	d = PostDatedCheque.__new__(PostDatedCheque)
	d.flags = frappe._dict()
	return d


class TestPDCSettingsPolicy(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		_init_frappe()

	def test_policy_defaults_when_no_settings_row(self):
		with patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=None):
			self.assertEqual(
				_pdc_company_policy_flags("Any Co"),
				{"allow_endorsement": 1, "require_sayad_registration": 0},
			)

	def test_blocks_transition_to_endorsed_when_allow_endorsement_off(self):
		d = _bare_pdc()
		d.company = "_TC"
		d.cheque_direction = CHEQUE_DIRECTION_RECEIVABLE
		d.workflow_state = WORKFLOW_ENDORSED
		settings = {
			"allow_endorsement": 0,
			"require_sayad_registration": 0,
		}
		with (
			patch.object(d, "_get_previous_workflow_state_raw", return_value=WORKFLOW_REGISTERED),
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=settings),
		):
			with self.assertRaises(ValidationError):
				d._validate_endorsement_allowed_per_settings()

	def test_allows_endorsed_transition_when_allow_endorsement_on(self):
		d = _bare_pdc()
		d.company = "_TC"
		d.cheque_direction = CHEQUE_DIRECTION_RECEIVABLE
		d.workflow_state = WORKFLOW_ENDORSED
		settings = {"allow_endorsement": 1, "require_sayad_registration": 0}
		with (
			patch.object(d, "_get_previous_workflow_state_raw", return_value=WORKFLOW_REGISTERED),
			patch.object(pdc_mod, "_get_pdc_settings_for_company", return_value=settings),
		):
			d._validate_endorsement_allowed_per_settings()

	def test_sayad_required_missing_code(self):
		d = _bare_pdc()
		d.company = "_TC"
		d.sayad_code = ""
		d.sayad_registered = 0
		with patch.object(
			pdc_mod,
			"_get_pdc_settings_for_company",
			return_value={"require_sayad_registration": 1, "allow_endorsement": 1},
		):
			with self.assertRaises(ValidationError):
				d._validate_sayad_registration_per_settings()

	def test_sayad_ok_when_setting_on_and_fields_set(self):
		d = _bare_pdc()
		d.company = "_TC"
		d.sayad_code = "123456789012"
		d.sayad_registered = 1
		with (
			patch.object(d, "_get_previous_workflow_state_raw", return_value=WORKFLOW_DRAFT),
			patch.object(
				pdc_mod,
				"_get_pdc_settings_for_company",
				return_value={"require_sayad_registration": 1, "allow_endorsement": 1},
			),
		):
			d._validate_sayad_registration_per_settings()

	def test_receivable_register_requires_sayad_registered_when_setting_on(self):
		d = _bare_pdc()
		d.company = "_TC"
		d.cheque_direction = CHEQUE_DIRECTION_RECEIVABLE
		d.workflow_state = WORKFLOW_REGISTERED
		d.sayad_code = "123456789012"
		d.sayad_registered = 0
		with (
			patch.object(d, "_get_previous_workflow_state_raw", return_value=WORKFLOW_DRAFT),
			patch.object(
				pdc_mod,
				"_get_pdc_settings_for_company",
				return_value={"require_sayad_registration": 1, "allow_endorsement": 1},
			),
		):
			with self.assertRaises(ValidationError):
				d._validate_sayad_registration_per_settings()

	def test_receivable_register_allows_without_sayad_registered_when_setting_off(self):
		d = _bare_pdc()
		d.company = "_TC"
		d.cheque_direction = CHEQUE_DIRECTION_RECEIVABLE
		d.workflow_state = WORKFLOW_REGISTERED
		d.sayad_code = ""
		d.sayad_registered = 0
		with (
			patch.object(d, "_get_previous_workflow_state_raw", return_value=WORKFLOW_DRAFT),
			patch.object(
				pdc_mod,
				"_get_pdc_settings_for_company",
				return_value={"require_sayad_registration": 0, "allow_endorsement": 1},
			),
		):
			d._validate_sayad_registration_per_settings()

	def test_payable_issue_requires_sayad_registered_when_setting_on(self):
		d = _bare_pdc()
		d.company = "_TC"
		d.cheque_direction = CHEQUE_DIRECTION_PAYABLE
		d.workflow_state = WORKFLOW_ISSUED
		d.sayad_code = "123456789012"
		d.sayad_registered = 0
		with (
			patch.object(d, "_get_previous_workflow_state_raw", return_value=WORKFLOW_REGISTERED),
			patch.object(
				pdc_mod,
				"_get_pdc_settings_for_company",
				return_value={"require_sayad_registration": 1, "allow_endorsement": 1},
			),
		):
			with self.assertRaises(ValidationError):
				d._validate_sayad_registration_per_settings()

	def test_payable_issue_allows_without_sayad_registered_when_setting_off(self):
		d = _bare_pdc()
		d.company = "_TC"
		d.cheque_direction = CHEQUE_DIRECTION_PAYABLE
		d.workflow_state = WORKFLOW_ISSUED
		d.sayad_code = ""
		d.sayad_registered = 0
		with (
			patch.object(d, "_get_previous_workflow_state_raw", return_value=WORKFLOW_REGISTERED),
			patch.object(
				pdc_mod,
				"_get_pdc_settings_for_company",
				return_value={"require_sayad_registration": 0, "allow_endorsement": 1},
			),
		):
			d._validate_sayad_registration_per_settings()

	def test_sayad_optional_when_setting_off(self):
		d = _bare_pdc()
		d.company = "_TC"
		d.sayad_code = None
		d.sayad_registered = 0
		with patch.object(
			pdc_mod,
			"_get_pdc_settings_for_company",
			return_value={"require_sayad_registration": 0, "allow_endorsement": 1},
		):
			d._validate_sayad_registration_per_settings()


if __name__ == "__main__":
	unittest.main()
