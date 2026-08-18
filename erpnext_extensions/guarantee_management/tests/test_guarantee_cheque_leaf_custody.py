# Copyright (c) 2026, ERPNext Extensions contributors
"""Tests for Guarantee Document ↔ Cheque Leaf custody (v4.4.4)."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from erpnext_extensions.guarantee_management.services.cheque_leaf_custody import (
	STATUS_USED_FOR_GUARANTEE,
	assert_leaf_available_for_guarantee,
	is_issued_cheque_guarantee,
	validate_issued_cheque_leaf,
)


def _leaf(**kw):
	base = dict(
		name="CL-1",
		status="Available",
		company="Co",
		linked_post_dated_cheque="",
		reserved_by_pdc="",
		linked_guarantee_document="",
	)
	base.update(kw)
	return SimpleNamespace(**base)


def _gd(**kw):
	base = dict(
		name="GD-1",
		company="Co",
		guarantee_direction="Issued",
		guarantee_type="Cheque",
		status="Draft",
		cheque_leaf="CL-1",
		is_new=lambda: False,
		get_doc_before_save=lambda: SimpleNamespace(status="Draft", cheque_leaf="CL-1"),
	)
	base.update(kw)
	return SimpleNamespace(**base)


class TestGuaranteeChequeLeafRules(unittest.TestCase):
	def test_available_leaf_selectable(self):
		assert_leaf_available_for_guarantee(_leaf(), "GD-1")

	def test_reserved_leaf_rejected(self):
		with self.assertRaises(ValidationError):
			assert_leaf_available_for_guarantee(_leaf(status="Reserved", reserved_by_pdc="PDC-1"), "GD-1")

	def test_used_pdc_leaf_rejected(self):
		with self.assertRaises(ValidationError):
			assert_leaf_available_for_guarantee(
				_leaf(status="Used", linked_post_dated_cheque="PDC-1"), "GD-1"
			)

	def test_void_rejected(self):
		with self.assertRaises(ValidationError):
			assert_leaf_available_for_guarantee(_leaf(status="Void"), "GD-1")

	def test_used_for_guarantee_other_gd_rejected(self):
		with self.assertRaises(ValidationError):
			assert_leaf_available_for_guarantee(
				_leaf(status=STATUS_USED_FOR_GUARANTEE, linked_guarantee_document="GD-OTHER"),
				"GD-1",
			)

	def test_duplicate_allocation_blocked(self):
		with self.assertRaises(ValidationError):
			assert_leaf_available_for_guarantee(
				_leaf(status=STATUS_USED_FOR_GUARANTEE, linked_guarantee_document="GD-2"),
				"GD-1",
			)

	def test_received_cheque_does_not_require_leaf(self):
		self.assertFalse(
			is_issued_cheque_guarantee(
				SimpleNamespace(guarantee_direction="Received", guarantee_type="Cheque")
			)
		)

	def test_bank_guarantee_does_not_use_leaf(self):
		self.assertFalse(
			is_issued_cheque_guarantee(
				SimpleNamespace(guarantee_direction="Issued", guarantee_type="Bank Guarantee")
			)
		)

	def test_promissory_note_unchanged(self):
		self.assertFalse(
			is_issued_cheque_guarantee(
				SimpleNamespace(guarantee_direction="Issued", guarantee_type="Promissory Note")
			)
		)

	def test_becoming_active_requires_leaf(self):
		gd = _gd(status="Active", cheque_leaf="")
		with patch(
			"erpnext_extensions.guarantee_management.services.cheque_leaf_custody._lock_leaf"
		):
			with self.assertRaises(ValidationError) as ctx:
				validate_issued_cheque_leaf(gd)
			self.assertIn("Cheque Leaf is required", str(ctx.exception))

	def test_existing_active_without_leaf_grandfathered(self):
		gd = _gd(status="Active", cheque_leaf="", is_new=lambda: False)
		gd.get_doc_before_save = lambda: SimpleNamespace(status="Active", cheque_leaf="")
		validate_issued_cheque_leaf(gd)

	def test_expired_and_lost_are_holding_not_release(self):
		from erpnext_extensions.guarantee_management.services.cheque_leaf_custody import (
			HOLDING_STATUSES,
			RELEASE_STATUSES,
		)

		self.assertIn("Expired", HOLDING_STATUSES)
		self.assertIn("Lost", HOLDING_STATUSES)
		self.assertIn("Cancelled", RELEASE_STATUSES)
		self.assertIn("Released", RELEASE_STATUSES)
		self.assertNotIn("Expired", RELEASE_STATUSES)
		self.assertNotIn("Lost", RELEASE_STATUSES)

	@patch("erpnext_extensions.guarantee_management.services.cheque_leaf_custody._lock_leaf")
	@patch("erpnext_extensions.guarantee_management.services.cheque_leaf_custody.frappe.db.set_value")
	def test_allocate_then_second_allocation_blocked(self, _set, lock):
		from erpnext_extensions.guarantee_management.services.cheque_leaf_custody import (
			allocate_leaf_to_guarantee,
		)

		lock.return_value = _leaf()
		gd = _gd()
		allocate_leaf_to_guarantee("CL-1", gd)
		lock.return_value = _leaf(
			status=STATUS_USED_FOR_GUARANTEE, linked_guarantee_document="GD-1"
		)
		allocate_leaf_to_guarantee("CL-1", gd)  # same GD idempotent
		lock.return_value = _leaf(
			status=STATUS_USED_FOR_GUARANTEE, linked_guarantee_document="GD-1"
		)
		with self.assertRaises(ValidationError):
			allocate_leaf_to_guarantee("CL-1", _gd(name="GD-2"))

	@patch("erpnext_extensions.guarantee_management.services.cheque_leaf_custody._lock_leaf")
	@patch("erpnext_extensions.guarantee_management.services.cheque_leaf_custody.frappe.db.set_value")
	def test_release_restores_available(self, set_value, lock):
		from erpnext_extensions.guarantee_management.services.cheque_leaf_custody import (
			release_leaf_from_guarantee,
		)

		lock.return_value = _leaf(
			status=STATUS_USED_FOR_GUARANTEE, linked_guarantee_document="GD-1"
		)
		release_leaf_from_guarantee("CL-1", "GD-1")
		args = set_value.call_args[0]
		self.assertEqual(args[0], "Cheque Leaf")
		self.assertEqual(args[2]["status"], "Available")
		self.assertIsNone(args[2]["linked_guarantee_document"])


class TestGuaranteeChequeLeafMeta(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		if os.environ.get("CI") and not frappe.db.exists("DocType", "Guarantee Document"):
			raise unittest.SkipTest("Guarantee Document not installed")
		if not frappe.db.exists("DocType", "Guarantee Document"):
			raise unittest.SkipTest("Guarantee Document not installed")

	def test_cheque_leaf_field_exists(self):
		meta = frappe.get_meta("Guarantee Document")
		self.assertTrue(meta.has_field("cheque_leaf"))
		df = meta.get_field("cheque_leaf")
		self.assertEqual(df.options, "Cheque Leaf")

	def test_cheque_leaf_status_option(self):
		meta = frappe.get_meta("Cheque Leaf")
		options = (meta.get_field("status").options or "").split("\n")
		self.assertIn("Used for Guarantee", options)
		self.assertTrue(meta.has_field("linked_guarantee_document"))
		self.assertTrue(meta.has_field("guarantee_allocated_on"))
		self.assertTrue(meta.has_field("guarantee_allocated_by"))
		self.assertTrue(meta.has_field("guarantee_released_on"))

	def test_query_source_mentions_available_only(self):
		path = frappe.get_app_path(
			"erpnext_extensions",
			"guarantee_management",
			"services",
			"cheque_leaf_custody.py",
		)
		src = open(path, encoding="utf-8").read()
		self.assertIn("cl.status = 'Available'", src)
		self.assertIn("linked_guarantee_document", src)
		self.assertIn("Expired", src)
		self.assertIn("Lost", src)
		self.assertIn("_pdc_get_cheque_leaf_row_for_update", src)
