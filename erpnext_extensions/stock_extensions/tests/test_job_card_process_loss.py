# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""The 3.8.8 process-loss override must stand down where upstream (ERPNext 16.33+,
frappe/erpnext#58262) already scopes the loss to the Job Card. Run under bench:

    bench --site <site> run-tests --module erpnext_extensions.stock_extensions.tests.test_job_card_process_loss
"""

from __future__ import annotations

import unittest

from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

from erpnext_extensions.stock_extensions import job_card_process_loss as patch


class TestJobCardProcessLossGuard(unittest.TestCase):
	def test_detects_upstream_scoped_process_loss(self):
		class Legacy:
			def set_process_loss_qty(self):
				pass

		class Scoped(Legacy):
			def get_pending_process_loss_qty(self):
				return 0

		self.assertFalse(patch.upstream_scopes_process_loss(Legacy))
		self.assertTrue(patch.upstream_scopes_process_loss(Scoped))

	def test_apply_patch_follows_upstream_capability(self):
		patch.apply_patch()
		self.assertTrue(StockEntry._job_card_process_loss_patched)
		overridden = StockEntry.set_process_loss_qty is patch.set_process_loss_qty
		# 16.33+: upstream keeps its own method; older 16.x: the override is installed.
		self.assertEqual(overridden, not patch.upstream_scopes_process_loss(StockEntry))
