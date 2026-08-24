# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""v4.6.2 — empty classification excluded before aggregation (totals = visible rows)."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.constants import (
	VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX,
	VIRTUAL_PARTY_UNSPECIFIED_KEY,
	VIRTUAL_UNIFIED_UNMAPPED_KEY,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import (
	measures_from_opening_period,
	sum_measure_rows,
)
from erpnext_extensions.iran_accounting.account_explorer.pagination import (
	exclude_empty_classification_rows,
	is_empty_classification_presentation_row,
	is_empty_classification_value,
	paginate_summary_rows,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import (
	AccountExplorerQuerySpec,
	AnalysisContext,
	DocumentScope,
	PaginationState,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_wave2a_analysis,
	require_site,
)


def _pagination_spec() -> AccountExplorerQuerySpec:
	return AccountExplorerQuerySpec(
		document_scope=DocumentScope(
			company="_Test Company",
			from_date="2026-01-01",
			to_date="2026-12-31",
			hide_zero_rows=False,
		),
		analysis=AnalysisContext(
			view_axis="party",
			pagination=PaginationState(page=1, page_size=50),
		),
	)


class TestEmptyClassificationValueHelpers(unittest.TestCase):
	def test_null_blank_whitespace_are_empty(self):
		for value in (None, "", "   ", "\t"):
			self.assertTrue(is_empty_classification_value(value), repr(value))

	def test_real_values_are_not_empty(self):
		for value in ("Customer A", "Main - _TC", "IRR"):
			self.assertFalse(is_empty_classification_value(value), repr(value))

	def test_presentation_markers(self):
		self.assertTrue(
			is_empty_classification_presentation_row(
				{"row_key": VIRTUAL_PARTY_UNSPECIFIED_KEY, "is_virtual_group": 1}
			)
		)
		self.assertTrue(
			is_empty_classification_presentation_row(
				{
					"row_key": f"{VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX}:cost_center",
					"dimension_value": "",
					"is_virtual_group": 1,
				}
			)
		)
		self.assertTrue(
			is_empty_classification_presentation_row(
				{
					"row_key": VIRTUAL_UNIFIED_UNMAPPED_KEY,
					"display_code": "__UNMAPPED__",
					"is_virtual_group": 1,
				}
			)
		)


class TestEmptyClassificationTotalsUnit(unittest.TestCase):
	def test_party_total_excludes_empty_bucket(self):
		"""Party A = 100, empty party = 50 → total must be 100."""
		classified = {
			"row_key": "party:Customer:A",
			"party": "A",
			"party_type": "Customer",
			"display_code": "A",
			"is_virtual_group": 0,
			**measures_from_opening_period(0, 0, 100, 0),
		}
		empty = {
			"row_key": VIRTUAL_PARTY_UNSPECIFIED_KEY,
			"party": "",
			"party_type": "",
			"display_code": "__UNSPECIFIED__",
			"is_virtual_group": 1,
			**measures_from_opening_period(0, 0, 50, 0),
		}
		result = paginate_summary_rows([classified, empty], _pagination_spec())
		self.assertEqual(len(result["rows"]), 1)
		self.assertEqual(result["rows"][0]["party"], "A")
		self.assertEqual(flt(result["totals"]["period_debit"]), 100.0)
		self.assertEqual(result["pagination"]["total_rows"], 1)
		self.assertEqual(
			flt(result["totals"]["period_debit"]),
			flt(sum_measure_rows(result["rows"])["period_debit"]),
		)

	def test_dimension_total_excludes_empty_bucket(self):
		classified = {
			"row_key": "dimension:cost_center:X",
			"dimension_value": "X",
			"display_code": "X",
			"is_virtual_group": 0,
			**measures_from_opening_period(0, 0, 80, 0),
		}
		empty = {
			"row_key": f"{VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX}:cost_center",
			"dimension_value": "",
			"display_code": "-",
			"is_virtual_group": 1,
			**measures_from_opening_period(0, 0, 40, 0),
		}
		result = paginate_summary_rows([classified, empty], _pagination_spec())
		self.assertEqual([r["dimension_value"] for r in result["rows"]], ["X"])
		self.assertEqual(flt(result["totals"]["period_debit"]), 80.0)

	def test_exclude_helper_drops_all_empty_variants(self):
		rows = [
			{"row_key": "ok", "party": "A", "is_virtual_group": 0, **measures_from_opening_period(0, 0, 1, 0)},
			{"row_key": VIRTUAL_PARTY_UNSPECIFIED_KEY, "party": "", "is_virtual_group": 1},
			{"row_key": "dim-empty", "dimension_value": None, "is_virtual_group": 1},
			{"row_key": "dim-blank", "dimension_value": "  ", "is_virtual_group": 0},
			{"row_key": VIRTUAL_UNIFIED_UNMAPPED_KEY, "unified_party": "", "is_virtual_group": 1},
		]
		kept = exclude_empty_classification_rows(rows)
		self.assertEqual([r["row_key"] for r in kept], ["ok"])


class TestEmptyClassificationApi(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.company = require_site(cls)
		enable_wave2a_analysis()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(cls.company)
		if not fy:
			raise unittest.SkipTest("No fiscal year")
		cls.fiscal_year, cls.from_date, cls.to_date = fy

	def _payload(self, analysis: dict) -> dict:
		return build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis=analysis,
			document={"hide_zero_rows": 0},
		)

	def _fetch_all_pages(self, fetch, base_analysis: dict) -> tuple[dict, list[dict]]:
		"""Fetch every page so totals can be compared to the full filtered row set.

		Site default_page_size may be very small; grand totals cover all pages.
		"""
		page_size = 50
		page = 1
		all_rows: list[dict] = []
		first = None
		while True:
			analysis = {
				**base_analysis,
				"page": page,
				"page_size": page_size,
			}
			result = fetch(self._payload(analysis))
			if first is None:
				first = result
			page_rows = result.get("rows") or []
			all_rows.extend(page_rows)
			pagination = result.get("pagination") or {}
			total_rows = int(pagination.get("total_rows") or 0)
			if not page_rows or len(all_rows) >= total_rows or not pagination.get("has_next"):
				break
			page += 1
			if page > 500:
				self.fail("pagination did not terminate")
		return first, all_rows

	def test_party_api_has_no_unspecified_and_totals_match_rows(self):
		first, rows = self._fetch_all_pages(api.get_party_summary, {"view_axis": "party"})
		self.assertFalse(any(r.get("row_key") == VIRTUAL_PARTY_UNSPECIFIED_KEY for r in rows))
		self.assertFalse(any(r.get("is_virtual_group") for r in rows))
		self.assertFalse(any(is_empty_classification_value(r.get("party")) for r in rows))
		self.assertEqual(int((first.get("pagination") or {}).get("total_rows") or 0), len(rows))
		row_totals = sum_measure_rows(rows)
		for field in ("period_debit", "period_credit", "opening_debit", "opening_credit"):
			self.assertEqual(
				flt((first.get("totals") or {}).get(field)),
				flt(row_totals.get(field)),
				field,
			)

	def test_dimension_api_has_no_unassigned_and_totals_match_rows(self):
		if not frappe.get_meta("GL Entry").has_field("cost_center"):
			self.skipTest("No cost_center")
		first, rows = self._fetch_all_pages(
			api.get_dimension_summary,
			{
				"view_axis": "dimension",
				"dimension_scope": {"dimension_type": "cost_center"},
			},
		)
		self.assertFalse(
			any((r.get("row_key") or "").startswith(VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX) for r in rows)
		)
		self.assertFalse(any(is_empty_classification_value(r.get("dimension_value")) for r in rows))
		self.assertEqual(int((first.get("pagination") or {}).get("total_rows") or 0), len(rows))
		row_totals = sum_measure_rows(rows)
		for field in ("period_debit", "period_credit"):
			self.assertEqual(
				flt((first.get("totals") or {}).get(field)),
				flt(row_totals.get(field)),
				field,
			)

	def test_currency_api_skips_blank_currency(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.currency_analysis_enabled = 1
		settings.flags.ignore_permissions = True
		settings.save()
		_first, rows = self._fetch_all_pages(api.get_currency_summary, {"view_axis": "currency"})
		self.assertFalse(any(is_empty_classification_value(r.get("currency")) for r in rows))
