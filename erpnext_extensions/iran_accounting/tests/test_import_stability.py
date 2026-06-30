# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import importlib
import unittest

import erpnext_extensions.iran_accounting.core.rounding as core_rounding
from erpnext_extensions.iran_accounting.worker.guard import ensure_runtime_ready


class TestImportStability(unittest.TestCase):
	def test_core_rounding_import_100_times(self):
		for _ in range(100):
			mod = importlib.import_module("erpnext_extensions.iran_accounting.core.rounding")
			self.assertTrue(hasattr(mod, "round_row_amount"))
			self.assertTrue(hasattr(mod, "round_currency_amount"))
			self.assertEqual(mod.round_row_amount(3, 10.5, 0), 32)

	def test_worker_guard_after_simulated_partial_state(self):
		ensure_runtime_ready()
		# Simulate stale attribute loss on legacy shim only (core must remain intact).
		import erpnext_extensions.iran_accounting.rounding as legacy

		if hasattr(legacy, "round_row_amount"):
			delattr(legacy, "round_row_amount")
		ensure_runtime_ready()
		self.assertTrue(hasattr(legacy, "round_row_amount"))
		self.assertTrue(hasattr(core_rounding, "round_row_amount"))
