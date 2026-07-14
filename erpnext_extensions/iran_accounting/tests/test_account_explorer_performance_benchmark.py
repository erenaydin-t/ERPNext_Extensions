# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import performance_benchmark
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	enable_diagnostics,
	enable_wave2a_analysis,
	enable_wave2b_voucher,
	require_site,
)


class TestAccountExplorerPerformanceBenchmark(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2a_analysis()
		enable_wave2b_voucher(include_wave2a=False)
		enable_diagnostics()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_benchmark_structure(self):
		result = performance_benchmark.run_account_explorer_performance_benchmark(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			scales=(100_000,),
			scenarios=("account_level",),
		)
		self.assertEqual(result["company"], self.company)
		self.assertEqual(result["documentation_only"], 1)
		self.assertIn("measurements", result)
		self.assertIn("index_recommendations", result)
		self.assertEqual(len(result["measurements"]), 1)
		self.assertIn("elapsed_ms", result["measurements"][0])

	def test_benchmark_uses_existing_summary_pipeline(self):
		measurement = performance_benchmark.measure_summary_scenario(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			"account_level",
		)
		self.assertEqual(measurement.get("skipped"), 0)
		self.assertGreaterEqual(measurement.get("elapsed_ms", -1), 0)

	def test_index_recommendations_are_documentation_only(self):
		results = [{"scenario": "account_level", "elapsed_ms": 999999, "skipped": 0}]
		recommendations = performance_benchmark.propose_index_recommendations(
			results,
			query_timeout_seconds=30,
		)
		self.assertTrue(recommendations)
		for row in recommendations:
			self.assertEqual(row.get("auto_apply"), 0)

	def test_large_scale_marked_not_reached_on_small_site(self):
		gl_count = performance_benchmark.count_company_gl_entries(self.company)
		if gl_count >= 100_000:
			self.skipTest("Site already exceeds 100K GL rows")
		result = performance_benchmark.run_account_explorer_performance_benchmark(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			scales=(100_000, 500_000, 1_000_000),
			scenarios=("account_level",),
		)
		for row in result["measurements"]:
			self.assertFalse(row["scale_reached"])
			self.assertEqual(row["actual_gl_rows"], gl_count)

	def test_whitelisted_benchmark_entry_point(self):
		from erpnext_extensions.iran_accounting.account_explorer import (
			run_account_explorer_performance_benchmark,
		)

		result = run_account_explorer_performance_benchmark(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
		)
		self.assertIn("target_scales", result)
		self.assertEqual(result["target_scales"], list(performance_benchmark.BENCHMARK_SCALES))

	def test_no_database_indexes_created(self):
		before_indexes = frappe.db.sql("show index from `tabGL Entry`", as_dict=True)
		performance_benchmark.run_account_explorer_performance_benchmark(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			scales=(100_000,),
			scenarios=("party",),
		)
		after_indexes = frappe.db.sql("show index from `tabGL Entry`", as_dict=True)
		self.assertEqual(len(before_indexes), len(after_indexes))
