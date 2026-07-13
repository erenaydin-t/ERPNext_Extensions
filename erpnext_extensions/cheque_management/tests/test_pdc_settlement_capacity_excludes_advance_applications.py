from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frappe.exceptions import ValidationError

import erpnext_extensions.cheque_management.pdc_settlement_capacity as cap


def _fake_frappe(*, db) -> SimpleNamespace:
	def _throw(msg, *args, **kwargs):
		raise ValidationError(msg)

	return SimpleNamespace(db=db, throw=_throw, flags=SimpleNamespace())


class TestSettlementCapacitySQLFilters(unittest.TestCase):
	def test_sum_effective_pdc_allocations_filters_allocation_mode_on_row(self) -> None:
		queries: list[str] = []

		def _sql(query, params=None):
			queries.append(query)
			return [(0,)]

		db = SimpleNamespace(sql=_sql)
		with patch.object(cap, "frappe", _fake_frappe(db=db)):
			cap.sum_effective_pdc_allocations_to_reference("Sales Invoice", "SINV-1")

		self.assertTrue(queries)
		q = " ".join((queries[0] or "").split()).lower()
		self.assertIn("coalesce(a.allocation_mode, 'direct_settlement') = 'direct_settlement'".lower(), q)

	def test_sum_effective_pdc_allocations_via_pr_filters_allocation_mode_on_row(self) -> None:
		queries: list[str] = []

		def _sql(query, params=None):
			queries.append(query)
			return []

		db = SimpleNamespace(sql=_sql)
		with patch.object(cap, "frappe", _fake_frappe(db=db)):
			cap.sum_effective_pdc_allocations_via_payment_request_to_invoice("Sales Invoice", "SINV-1")

		self.assertTrue(queries)
		q = " ".join((queries[0] or "").split()).lower()
		self.assertIn("coalesce(a.allocation_mode, 'direct_settlement') = 'direct_settlement'".lower(), q)
