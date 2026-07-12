from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from frappe.exceptions import ValidationError

import erpnext_extensions.cheque_management.pdc_advance_application_service as svc


def _fake_throw(msg, *a, **k):
	raise ValidationError(msg)


class TestAdvanceCandidatesMixedPoolSuggestion(unittest.TestCase):
	def test_suggests_order_based_first_then_general_remaining(self):
		# Invoice total 20000, order open 15000, general open 10000 => suggest 15000 + 5000
		inv = SimpleNamespace(
			company="_TC",
			currency="INR",
			grand_total=20000.0,
			supplier="SUP-1",
			items=[SimpleNamespace(purchase_order="PO-1")],
		)

		def _sql(q, params=None, as_dict=False):
			if "INNER JOIN `tabPDC Allocation`" in q:
				return [
					{"pdc": "PDC-O1", "pdc_currency": "INR", "recognition_je_posted": 1, "instrument_dead": 0}
				]
			# general
			return [
				{"pdc": "PDC-G1", "pdc_currency": "INR", "recognition_je_posted": 1, "instrument_dead": 0}
			]

		fake_frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda *a, **k: True, sql=_sql),
			get_doc=lambda *a, **k: inv,
			throw=_fake_throw,
			msgprint=lambda *a, **k: None,
		)

		with (
			patch.object(svc, "frappe", fake_frappe),
			patch.object(svc, "_", lambda s: s),
			patch.object(svc, "get_pdc_open_advance_by_order", return_value={"open_amount": 15000.0}),
			patch.object(svc, "get_pdc_open_advance_instrument", return_value={"open_amount": 10000.0}),
		):
			out = svc.get_advance_candidates_for_invoice("Purchase Invoice", "PINV-1", include_general=True)

		self.assertEqual([c["advance_scope"] for c in out["candidates"]], ["order_based", "general"])
		self.assertEqual(out["candidates"][0]["suggested_apply_amount"], 15000.0)
		self.assertEqual(out["candidates"][1]["suggested_apply_amount"], 5000.0)

	def test_order_based_only_suggests_up_to_grand_total(self):
		inv = SimpleNamespace(
			company="_TC",
			currency="INR",
			grand_total=20000.0,
			customer="CUST-1",
			items=[SimpleNamespace(sales_order="SO-1")],
		)

		def _sql(q, params=None, as_dict=False):
			return [
				{"pdc": "PDC-O1", "pdc_currency": "INR", "recognition_je_posted": 1, "instrument_dead": 0}
			]

		fake_frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda *a, **k: True, sql=_sql),
			get_doc=lambda *a, **k: inv,
			throw=_fake_throw,
			msgprint=lambda *a, **k: None,
		)

		with (
			patch.object(svc, "frappe", fake_frappe),
			patch.object(svc, "_", lambda s: s),
			patch.object(svc, "get_pdc_open_advance_by_order", return_value={"open_amount": 99999.0}),
		):
			out = svc.get_advance_candidates_for_invoice("Sales Invoice", "SINV-1", include_general=False)

		self.assertEqual(len(out["candidates"]), 1)
		self.assertEqual(out["candidates"][0]["suggested_apply_amount"], 20000.0)

	def test_no_order_link_returns_general_only(self):
		inv = SimpleNamespace(company="_TC", currency="INR", grand_total=20000.0, supplier="SUP-1", items=[])

		def _sql(q, params=None, as_dict=False):
			# only general query should matter; returning order-based rows would require join in q
			return [
				{"pdc": "PDC-G1", "pdc_currency": "INR", "recognition_je_posted": 1, "instrument_dead": 0}
			]

		fake_frappe = SimpleNamespace(
			db=SimpleNamespace(exists=lambda *a, **k: True, sql=_sql),
			get_doc=lambda *a, **k: inv,
			throw=_fake_throw,
			msgprint=lambda *a, **k: None,
		)

		with (
			patch.object(svc, "frappe", fake_frappe),
			patch.object(svc, "_", lambda s: s),
			patch.object(svc, "get_pdc_open_advance_instrument", return_value={"open_amount": 10000.0}),
		):
			out = svc.get_advance_candidates_for_invoice("Purchase Invoice", "PINV-2", include_general=True)

		self.assertEqual(len(out["candidates"]), 1)
		self.assertEqual(out["candidates"][0]["advance_scope"], "general")
		self.assertEqual(out["candidates"][0]["suggested_apply_amount"], 10000.0)
