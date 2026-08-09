# Copyright (c) 2026, ERPNext Extensions contributors
"""Regression: RAL monkey-patch must tolerate ERPNext 16.31.1 API shape."""

from __future__ import annotations

import types
import unittest
from unittest import mock

import frappe


def _make_legacy_ral_module():
	"""Pre-16.31.1 shape: module-level start_repost does the work."""
	calls = {"start": []}

	def start_repost(account_repost_doc=None):
		calls["start"].append(account_repost_doc)

	mod = types.ModuleType("fake_ral_legacy")
	mod.start_repost = start_repost
	mod.RepostAccountingLedger = type("RepostAccountingLedger", (), {})
	mod._calls = calls
	return mod


def _make_v1631_ral_module():
	"""ERPNext 16.31.1 shape: Document.start_repost enqueues; module repost works."""
	calls = {"repost": []}

	class RepostAccountingLedger:
		def start_repost(self):
			raise AssertionError("Document.start_repost must not be wrapped as module API")

	def repost(repost_doc_name: str, commit: bool = True):
		calls["repost"].append((repost_doc_name, commit))

	mod = types.ModuleType("fake_ral_v1631")
	mod.RepostAccountingLedger = RepostAccountingLedger
	mod.repost = repost
	# Intentionally NO module-level start_repost (the AttributeError that broke migrate).
	mod._calls = calls
	return mod


def _make_empty_ral_module():
	mod = types.ModuleType("fake_ral_empty")
	mod.RepostAccountingLedger = type(
		"RepostAccountingLedger",
		(),
		{"start_repost": lambda self: None},
	)
	return mod


class TestRepostAccountingLedgerCompat(unittest.TestCase):
	def test_live_erpnext_has_module_repost_not_module_start_repost(self):
		import erpnext.accounts.doctype.repost_accounting_ledger.repost_accounting_ledger as ral_mod

		self.assertTrue(callable(getattr(ral_mod, "repost", None)))
		self.assertFalse(hasattr(ral_mod, "start_repost"))
		self.assertTrue(callable(getattr(ral_mod.RepostAccountingLedger, "start_repost", None)))

	def test_legacy_start_repost_api_is_wrapped(self):
		from erpnext_extensions.iran_accounting.integration import monkey_patches as mp

		mod = _make_legacy_ral_module()
		self.assertTrue(mp._patch_ral_module_level_start_repost(mod))
		self.assertTrue(getattr(mod, "_iran_patched_start_repost"))
		orig_wrapped = mod.start_repost
		with mock.patch.object(mp, "_run_irr_pipeline_after_ral") as pipeline:
			mod.start_repost("RAL-LEGACY-1")
			pipeline.assert_called_once_with("RAL-LEGACY-1")
		self.assertEqual(mod._calls["start"], ["RAL-LEGACY-1"])
		self.assertTrue(mp._patch_ral_module_level_start_repost(mod))
		self.assertIs(mod.start_repost, orig_wrapped)

	def test_erpnext_1631_repost_api_is_wrapped(self):
		from erpnext_extensions.iran_accounting.integration import monkey_patches as mp

		mod = _make_v1631_ral_module()
		self.assertTrue(mp._patch_ral_module_level_repost(mod))
		self.assertTrue(getattr(mod, "_iran_patched_ral_repost"))
		self.assertFalse(hasattr(mod, "start_repost"))
		wrapped = mod.repost
		with mock.patch.object(mp, "_run_irr_pipeline_after_ral") as pipeline:
			mod.repost("RAL-NEW-1", commit=False)
			pipeline.assert_called_once_with("RAL-NEW-1")
		self.assertEqual(mod._calls["repost"], [("RAL-NEW-1", False)])
		self.assertTrue(mp._patch_ral_module_level_repost(mod))
		self.assertIs(mod.repost, wrapped)

	def test_start_repost_missing_does_not_raise(self):
		from erpnext_extensions.iran_accounting.integration import monkey_patches as mp

		mod = _make_v1631_ral_module()
		with self.assertRaises(AttributeError):
			_ = mod.start_repost
		self.assertFalse(mp._patch_ral_module_level_start_repost(mod))
		self.assertTrue(mp._patch_ral_module_level_repost(mod))

	def test_replacement_repost_exists_preferred_over_legacy(self):
		from erpnext_extensions.iran_accounting.integration import monkey_patches as mp

		mod = _make_v1631_ral_module()
		# Mistaken module binding of the Document method must not be treated as legacy API.
		mod.start_repost = mod.RepostAccountingLedger.start_repost
		self.assertTrue(mp._patch_ral_module_level_repost(mod))
		self.assertFalse(mp._patch_ral_module_level_start_repost(mod))
		self.assertTrue(getattr(mod, "_iran_patched_ral_repost"))
		self.assertFalse(getattr(mod, "_iran_patched_start_repost", False))

	def test_no_supported_hook_skips_without_crash(self):
		from erpnext_extensions.iran_accounting.integration import monkey_patches as mp

		mod = _make_empty_ral_module()
		self.assertFalse(mp._patch_ral_module_level_repost(mod))
		self.assertFalse(mp._patch_ral_module_level_start_repost(mod))

	def test_apply_monkey_patches_completes_on_live_erpnext(self):
		import erpnext.accounts.doctype.repost_accounting_ledger.repost_accounting_ledger as ral_mod

		from erpnext_extensions.iran_accounting.integration.monkey_patches import apply_monkey_patches

		apply_monkey_patches()
		self.assertTrue(getattr(ral_mod, "_iran_patched_ral_repost", False))
		self.assertTrue(callable(ral_mod.repost))

	def test_apply_monkey_patches_idempotent_no_double_wrap(self):
		import erpnext.accounts.doctype.repost_accounting_ledger.repost_accounting_ledger as ral_mod

		from erpnext_extensions.iran_accounting.integration import monkey_patches as mp

		mp.apply_monkey_patches()
		first = ral_mod.repost
		mp.apply_monkey_patches()
		mp._patch_repost_compatibility()
		second = ral_mod.repost
		self.assertIs(first, second)
		self.assertTrue(getattr(ral_mod, "_iran_patched_ral_repost"))

	def test_after_migrate_bootstrap_succeeds(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		# Must not raise AttributeError on ral_mod.start_repost
		apply()
		apply()

	def test_pipeline_runs_after_wrapped_repost(self):
		from erpnext_extensions.iran_accounting.integration import monkey_patches as mp

		mod = _make_v1631_ral_module()
		mp._patch_ral_module_level_repost(mod)
		voucher = frappe._dict(
			voucher_type="Stock Entry",
			voucher_no="STE-1",
			status="Reposted",
		)
		ral_doc = mock.Mock()
		ral_doc.get = mock.Mock(return_value=[voucher])

		se_doc = mock.Mock()
		se_doc.doctype = "Stock Entry"
		se_doc.name = "STE-1"
		se_doc.company = "ESPAD"

		with (
			mock.patch("frappe.get_doc", side_effect=[ral_doc, se_doc]) as get_doc,
			mock.patch("frappe.db.get_value", return_value="ESPAD"),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.currency.is_irr_company",
				return_value=True,
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.repost_determinism.run_post_repost_deterministic_pipeline"
			) as pipeline,
		):
			mod.repost("RAL-PIPE-1", commit=True)
			pipeline.assert_called_once()
			self.assertEqual(pipeline.call_args.args[0], se_doc)
			self.assertEqual(get_doc.call_count, 2)

	def test_pipeline_skips_failed_voucher_rows(self):
		from erpnext_extensions.iran_accounting.integration.monkey_patches import (
			_run_irr_pipeline_after_ral,
		)

		failed = frappe._dict(
			voucher_type="Stock Entry",
			voucher_no="STE-FAIL",
			status="Failed",
		)
		ral_doc = mock.Mock()
		ral_doc.get = mock.Mock(return_value=[failed])
		with (
			mock.patch("frappe.get_doc", return_value=ral_doc),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.repost_determinism.run_post_repost_deterministic_pipeline"
			) as pipeline,
		):
			_run_irr_pipeline_after_ral("RAL-FAIL")
			pipeline.assert_not_called()


class TestRepostCompatDoesNotBreakExistingAccountingPatches(unittest.TestCase):
	def test_general_ledger_patch_still_present_after_ral_compat(self):
		import erpnext.accounts.general_ledger as gl

		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		self.assertTrue(getattr(gl, "_iran_patched", False))
		self.assertTrue(callable(gl.merge_similar_entries))
		self.assertTrue(callable(gl.process_debit_credit_difference))
