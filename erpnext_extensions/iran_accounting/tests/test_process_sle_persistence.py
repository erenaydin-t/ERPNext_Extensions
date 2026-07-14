# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import frappe

from erpnext_extensions.iran_accounting.domain.sle_persistence import persist_processed_sle_if_possible
from erpnext_extensions.iran_accounting.integration.bootstrap import apply


class TestProcessSlePersistence(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		apply()

	def test_process_sle_with_document(self):
		sle = frappe._dict(
			doctype="Stock Ledger Entry",
			name="sle-doc-path",
			stock_value=100,
			valuation_rate=10,
		)
		doc = MagicMock()
		with patch.object(frappe, "get_doc", return_value=doc):
			self.assertTrue(persist_processed_sle_if_possible(sle))
			doc.db_update.assert_called_once()

	def test_process_sle_with_frappe_dict_with_doctype(self):
		sle = frappe._dict(
			doctype="Stock Ledger Entry",
			name="sle-2",
			stock_value=50,
			valuation_rate=5,
		)
		doc = MagicMock()
		with patch.object(frappe, "get_doc", return_value=doc) as mock_get:
			self.assertTrue(persist_processed_sle_if_possible(sle))
			mock_get.assert_called_once_with(sle)
			doc.db_update.assert_called_once()

	def test_process_sle_with_plain_dict_without_doctype(self):
		sle = {"name": "n1", "stock_value": 10}
		with patch.object(frappe.db, "exists", return_value=False):
			self.assertFalse(persist_processed_sle_if_possible(sle))

	def test_process_sle_with_existing_name_only(self):
		sle = frappe._dict(name="existing-sle", stock_value=1000, valuation_rate=100)
		doc = MagicMock()
		with patch.object(frappe.db, "exists", return_value=True):
			with patch.object(frappe, "get_doc", return_value=doc) as mock_get:
				self.assertTrue(persist_processed_sle_if_possible(sle))
				mock_get.assert_called_once_with("Stock Ledger Entry", "existing-sle")
				doc.db_update.assert_called_once()

	def test_process_sle_not_yet_persisted(self):
		sle = frappe._dict(company="ESPAD", stock_value=1)
		self.assertFalse(persist_processed_sle_if_possible(sle))

	def test_no_duplicate_sle_insert(self):
		sle = frappe._dict(name="n2", stock_value=1)
		doc = MagicMock()
		with patch.object(frappe.db, "exists", return_value=True):
			with patch.object(frappe, "get_doc", return_value=doc) as mock_get:
				persist_processed_sle_if_possible(sle)
				mock_get.assert_called_once_with("Stock Ledger Entry", "n2")

	def test_missing_sle_name_is_handled_safely(self):
		self.assertFalse(persist_processed_sle_if_possible(frappe._dict(stock_value=1)))

	def test_frappe_dict_without_doctype_skips_get_doc_on_mapping(self):
		sle = frappe._dict(name="orphan", company="ESPAD", stock_value=99)
		with patch.object(frappe.db, "exists", return_value=False):
			with patch.object(frappe, "get_doc") as mock_get:
				self.assertFalse(persist_processed_sle_if_possible(sle))
				mock_get.assert_not_called()


if __name__ == "__main__":
	unittest.main()
