# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Unit tests for AET realistic Voucher GL business dataset."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_hierarchy import (
	batch_resolve_account_hierarchies,
	enrich_rows_with_hierarchy,
	get_hierarchy_start_level,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import build_voucher_gl_print
from erpnext_extensions.iran_accounting.account_explorer.query_builder import get_enabled_levels
from erpnext_extensions.iran_accounting.tests.voucher_gl_business_dataset import (
	COMPANY_NAME,
	EXPECTED_LEVELS,
	EXPECTED_PRINT_HIERARCHY,
	POSTING_ACCOUNT,
	ensure_voucher_gl_business_dataset,
)


class TestVoucherGLBusinessDataset(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.ds = ensure_voucher_gl_business_dataset()

	def test_company_and_coa_tree(self):
		self.assertTrue(frappe.db.exists("Company", COMPANY_NAME))
		for code, title in (
			("11", "دارایی‌های جاری"),
			("1110", "موجودی نقد و بانک"),
			("111004", "موجودی بانک‌های ریالی"),
			("11100401", "بانک کارآفرین"),
			(POSTING_ACCOUNT, "بانک کارآفرین کارگر شمالی - 0101047285607"),
		):
			name = self.ds["accounts"][code]
			row = frappe.db.get_value(
				"Account", name, ["account_number", "account_name", "is_group", "parent_account"], as_dict=True
			)
			self.assertEqual(row.account_number, code)
			self.assertEqual(row.account_name, title)
			if code == POSTING_ACCOUNT:
				self.assertEqual(int(row.is_group), 0)
				parent_num = frappe.db.get_value("Account", row.parent_account, "account_number")
				self.assertEqual(parent_num, "11100401")

	def test_account_level_mapping(self):
		levels = get_enabled_levels()
		got = [(int(r.sequence), int(r.code_length)) for r in levels]
		self.assertEqual(got, [(s, l) for s, l, _ in EXPECTED_LEVELS])
		self.assertEqual(get_hierarchy_start_level({}), 2)

	def test_posting_hierarchy_starts_at_level_2(self):
		cache = batch_resolve_account_hierarchies(
			self.ds["company"],
			[self.ds["posting_account"]],
			start_level=2,
		)
		hier = cache[self.ds["posting_account"]]
		codes = [n["code"] for n in hier]
		names = [n["name"] for n in hier]
		self.assertEqual(codes, [c for c, _ in EXPECTED_PRINT_HIERARCHY])
		self.assertEqual(names, [n for _, n in EXPECTED_PRINT_HIERARCHY])
		self.assertNotIn("11", codes)
		self.assertEqual(len(codes), len(set(codes)))

	def test_parties_and_dimensions_exist(self):
		for c in self.ds["customers"]:
			self.assertTrue(frappe.db.exists("Customer", c))
		for s in self.ds["suppliers"]:
			self.assertTrue(frappe.db.exists("Supplier", s))
		for e in self.ds["employees"]:
			self.assertTrue(frappe.db.exists("Employee", e))
		for cc in self.ds["cost_centers"]:
			self.assertTrue(frappe.db.exists("Cost Center", cc))
		for p in self.ds["projects"]:
			self.assertTrue(frappe.db.exists("Project", p))
		for f in self.ds["facilities"]:
			self.assertTrue(frappe.db.exists("Facility", f))
		self.assertTrue(frappe.get_meta("GL Entry").has_field("facility"))

	def test_vouchers_balanced_with_gl(self):
		self.assertGreaterEqual(len(self.ds["vouchers"]), 8)
		for item in self.ds["vouchers"]:
			gl = frappe.get_all(
				"GL Entry",
				filters={
					"voucher_type": "Journal Entry",
					"voucher_no": item["name"],
					"is_cancelled": 0,
					"company": self.ds["company"],
				},
				fields=["debit", "credit"],
			)
			self.assertTrue(gl, item["name"])
			self.assertAlmostEqual(sum(flt(r.debit) for r in gl), sum(flt(r.credit) for r in gl), places=3)

	def test_multi_line_hierarchy_once(self):
		v2 = next(v for v in self.ds["vouchers"] if v["key"] == "v2_multi_line")
		filters = {
			"company": self.ds["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": v2["name"],
			"show_account_hierarchy": 1,
			"account_hierarchy_start_level": 2,
			"layout": "Standard",
			"include_opening_entries": 1,
		}
		payload = enrich_rows_with_hierarchy(build_voucher_gl_print(filters), filters)
		headers = [n for n in payload["display_nodes"] if n.get("node_type") == "account_header"]
		bank_headers = [h for h in headers if h.get("account") == self.ds["posting_account"]]
		self.assertEqual(len(bank_headers), 1)
		lines = [
			n
			for n in payload["display_nodes"]
			if n.get("node_type") == "gl_line" and (n.get("row") or {}).get("account") == self.ds["posting_account"]
		]
		self.assertGreaterEqual(len(lines), 3)

	def test_party_and_dimension_splits(self):
		v8 = next(v for v in self.ds["vouchers"] if v["key"] == "v8_combined")
		filters = {
			"company": self.ds["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": v8["name"],
			"show_account_hierarchy": 1,
			"account_hierarchy_start_level": 2,
			"layout": "Standard",
			"include_opening_entries": 1,
		}
		payload = enrich_rows_with_hierarchy(build_voucher_gl_print(filters), filters)
		nodes = payload["display_nodes"]
		self.assertTrue(any(n.get("node_type") == "party_header" for n in nodes))
		# Dimensions may attach to GL lines (or dimension_header) depending on grouping.
		self.assertTrue(
			any(n.get("node_type") == "dimension_header" for n in nodes)
			or any((n.get("dimensions") or []) for n in nodes if n.get("node_type") == "gl_line")
		)
		self.assertTrue(any(n.get("node_type") == "account_subtotal" for n in nodes))
		# Distinct parties present
		party_names = {
			(n.get("party") or {}).get("party_name")
			for n in nodes
			if n.get("node_type") == "party_header"
		}
		self.assertIn("AET Customer A", party_names)
		self.assertIn("AET Supplier A", party_names)
	def test_no_n_plus_one_hierarchy_queries(self):
		v1 = next(v for v in self.ds["vouchers"] if v["key"] == "v1_basic")
		filters = {
			"company": self.ds["company"],
			"voucher_type": "Journal Entry",
			"voucher_no": v1["name"],
			"show_account_hierarchy": 1,
			"account_hierarchy_start_level": 2,
			"layout": "Standard",
			"include_opening_entries": 1,
		}
		frappe.db.sql("select 1")  # warm
		before = frappe.db.sql_list  # noqa: not used; use recorder
		from frappe.database.database import Database

		queries = []
		orig = Database.sql

		def spy(self, query, *args, **kwargs):
			queries.append(str(query))
			return orig(self, query, *args, **kwargs)

		Database.sql = spy
		try:
			enrich_rows_with_hierarchy(build_voucher_gl_print(filters), filters)
		finally:
			Database.sql = orig
		account_lookups = [q for q in queries if "tabAccount" in q and "select" in q.lower()]
		# Batch load should not issue one Account SELECT per parent node.
		self.assertLessEqual(len(account_lookups), 8, account_lookups)
