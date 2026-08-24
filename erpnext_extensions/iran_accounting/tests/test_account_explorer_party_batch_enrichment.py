# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Unit tests: v4.6.0 party batch enrichment and request-local caches."""

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer.party_sources import (
	batch_party_display_titles,
	batch_party_identifiers,
	enrich_party_rows,
	get_enabled_party_sources,
	get_party_display_title,
	get_party_source_config,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import require_site


class TestAccountExplorerPartyBatchEnrichment(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.company = require_site(self)
		if hasattr(frappe.local, "request_cache"):
			frappe.local.request_cache.clear()

	def test_get_enabled_party_sources_is_request_cached(self):
		first = get_enabled_party_sources()
		second = get_enabled_party_sources()
		self.assertIs(first, second)

	def test_get_party_source_config_uses_cached_sources(self):
		sources = get_enabled_party_sources()
		if not sources:
			self.skipTest("No party sources configured")
		row = get_party_source_config(sources[0].party_type)
		self.assertEqual(row.party_type, sources[0].party_type)

	def test_batch_party_display_titles_matches_single_resolver(self):
		customer = frappe.db.get_value("Customer", {}, "name", order_by="creation asc")
		if not customer:
			self.skipTest("No Customer")
		expected = get_party_display_title("Customer", customer)
		batch = batch_party_display_titles("Customer", [customer])
		self.assertEqual(batch[customer], expected)

	def test_enrich_party_rows_sets_titles(self):
		customer = frappe.db.get_value("Customer", {}, "name", order_by="creation asc")
		if not customer:
			self.skipTest("No Customer")
		rows = [
			{
				"party_type": "Customer",
				"party": customer,
				"display_code": customer,
				"display_title": customer,
				"party_identifier": None,
				"is_virtual_group": 0,
			}
		]
		enrich_party_rows(rows)
		self.assertEqual(rows[0]["display_title"], get_party_display_title("Customer", customer))

	def test_batch_party_identifiers_returns_map(self):
		customer = frappe.db.get_value("Customer", {}, "name", order_by="creation asc")
		if not customer:
			self.skipTest("No Customer")
		source = get_party_source_config("Customer")
		id_field = source.identifier_field if source else None
		if not id_field:
			self.skipTest("Customer identifier field not configured")
		meta = frappe.get_meta("Customer")
		if not meta.has_field(id_field):
			self.skipTest("Customer identifier field missing on doctype")
		expected = frappe.db.get_value("Customer", customer, id_field)
		batch = batch_party_identifiers("Customer", [customer], id_field)
		self.assertEqual(batch[customer], expected)
