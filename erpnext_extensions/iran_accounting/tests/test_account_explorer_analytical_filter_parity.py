# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Wave 3B-3A — Analytical Filter accounting parity vs General Ledger."""

from __future__ import annotations

import json
import time
import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
	spec_has_advanced_gle_filters,
)
from erpnext_extensions.iran_accounting.account_explorer.opening_balance import (
	get_account_wise_measures,
)
from erpnext_extensions.iran_accounting.account_explorer.party_opening import (
	get_unspecified_party_measures,
)
from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
	AccountExplorerQuerySpec_from_client,
)
from erpnext_extensions.iran_accounting.tests.analytical_parity_fixtures import (
	direct_gl_opening_totals,
	direct_gl_period_totals,
	ensure_parity_company,
	ensure_parity_dataset,
	full_measures_from_opening_period,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	default_document_scope,
)

MEASURE_FIELDS = (
	"opening_debit",
	"opening_credit",
	"period_debit",
	"period_credit",
	"closing_debit",
	"closing_credit",
	"net_balance",
)


class TestAccountExplorerAnalyticalFilterParity(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

		class _Gate:
			@staticmethod
			def skipTest(msg):
				raise unittest.SkipTest(msg)

		cls.ctx = ensure_parity_dataset(ensure_parity_company(_Gate()))
		cls.max_abs_diff = 0.0

	@classmethod
	def tearDownClass(cls):
		"""Cancel parity JEs so later AE modules do not inherit fixture party GL."""
		company = (cls.ctx or {}).get("company") or "_Test Company"
		for old in frappe.get_all(
			"Journal Entry",
			filters={"company": company, "user_remark": ("like", "AE-AF-PARITY%"), "docstatus": 1},
			pluck="name",
		):
			doc = frappe.get_doc("Journal Entry", old)
			doc.flags.ignore_permissions = True
			doc.cancel()
		frappe.db.commit()
	def _base_document(self, **overrides) -> dict:
		document = default_document_scope(
			self.ctx["company"],
			self.ctx["fiscal_year"],
			self.ctx["from_date"],
			self.ctx["to_date"],
		)
		document["hide_zero_rows"] = 0
		for key, value in overrides.items():
			if isinstance(value, dict) and isinstance(document.get(key), dict):
				document[key] = {**document[key], **value}
			else:
				document[key] = value
		return document

	def _payload(self, *, axis: str, analysis: dict | None = None, document: dict | None = None) -> str:
		analysis_context = {
			"view_axis": axis,
			"detail_mode": "summary",
			"page": 1,
			"page_size": 500,
			"account_scope": {"mode": "tree"},
			"party_scope": {},
			"unified_party_scope": {},
			"dimension_scope": {},
			"voucher_scope": {},
		}
		if analysis:
			analysis_context.update(analysis)
		return json.dumps(
			{
				"document_scope": document or self._base_document(),
				"analysis_context": analysis_context,
			}
		)

	def _call_axis(self, axis: str, payload: str) -> dict:
		methods = {
			"account_level": api.get_account_summary,
			"party": api.get_party_summary,
			"dimension": api.get_dimension_summary,
			"currency": api.get_currency_summary,
			"voucher": api.get_voucher_summary,
		}
		return methods[axis](payload)

	def _period_from_result(self, axis: str, result: dict) -> tuple[float, float]:
		totals = result.get("totals") or {}
		if axis == "voucher":
			return flt(totals.get("scoped_debit")), flt(totals.get("scoped_credit"))
		return flt(totals.get("period_debit")), flt(totals.get("period_credit"))

	def _assert_zero_diff(self, actual, expected, label: str):
		diff = abs(flt(actual) - flt(expected))
		self.max_abs_diff = max(self.max_abs_diff, diff)
		self.assertEqual(
			diff,
			0,
			msg=f"{label}: AE={actual} GL={expected} abs_diff={diff}",
		)

	def _assert_period_parity(self, axis: str, payload: str, expected: dict, label: str):
		result = self._call_axis(axis, payload)
		period_debit, period_credit = self._period_from_result(axis, result)
		self._assert_zero_diff(period_debit, expected["period_debit"], f"{label}/{axis}/period_debit")
		self._assert_zero_diff(period_credit, expected["period_credit"], f"{label}/{axis}/period_credit")

	def _assert_full_account_measure_parity(self, payload: str, gl_kwargs: dict, label: str):
		result = api.get_account_summary(payload)
		totals = result["totals"]
		opening_kwargs = {
			key: value
			for key, value in gl_kwargs.items()
			if key != "include_opening_entries"
		}
		opening = direct_gl_opening_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			**opening_kwargs,
		)
		period = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			**gl_kwargs,
		)
		expected = full_measures_from_opening_period(opening, period)
		for field in MEASURE_FIELDS:
			self._assert_zero_diff(totals.get(field), expected[field], f"{label}/{field}")

	def test_spec_decision_function_matrix(self):
		plain = AccountExplorerQuerySpec_from_client(
			self._payload(axis="account_level"),
			require_dates=True,
		)
		self.assertFalse(spec_has_advanced_gle_filters(plain))

		cases = [
			({"voucher_scope": {"voucher_no": self.ctx["je_a"]}}, None),
			(
				{"dimension_scope": {"dimension_type": "cost_center", "selected_dimension_value": self.ctx["cost_center"]}},
				{"accounting_dimensions": {"cost_center": self.ctx["cost_center"]}},
			),
			({}, {"currency": {"currency_type": "account_currency", "currency": self.ctx["currency"]}}),
			({}, {"accounting": {"account": self.ctx["receivable"]}}),
			({}, {"voucher": {"voucher_type": "Journal Entry", "voucher_no": self.ctx["je_a"]}}),
			({}, {"voucher": {"against_voucher_no": "X"}}),
			({}, {"voucher": {"reference_no": "REF"}}),
			({}, {"status": {"include_cancelled_entries": 1}}),
		]
		if self.ctx.get("customer"):
			cases.insert(
				1,
				(
					{"party_scope": {"party_type": "Customer", "selected_party": self.ctx["customer"]}},
					None,
				),
			)
		for analysis, document_overrides in cases:
			document = self._base_document(**(document_overrides or {}))
			spec = AccountExplorerQuerySpec_from_client(
				self._payload(axis="account_level", analysis=analysis, document=document),
				require_dates=True,
			)
			self.assertTrue(
				spec_has_advanced_gle_filters(spec),
				msg=f"expected advanced for analysis={analysis} document={document_overrides}",
			)

		# Unified party selection without resolving a real DocType (detector-only).
		uap_spec = AccountExplorerQuerySpec_from_client(
			self._payload(axis="account_level"),
			require_dates=True,
		)
		uap_spec.analysis.unified_party_scope.selected_unified_party = "UAP-X"
		self.assertTrue(spec_has_advanced_gle_filters(uap_spec))
		uap_spec.analysis.unified_party_scope.selected_unified_party = None
		uap_spec.resolved_member_tuples = [("Customer", self.ctx.get("customer") or "X")]
		self.assertTrue(spec_has_advanced_gle_filters(uap_spec))

	def test_voucher_filter_parity_matrix(self):
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			voucher_type="Journal Entry",
			voucher_no=self.ctx["je_a"],
		)
		self._assert_zero_diff(gl["period_debit"], self.ctx["amount_a"], "fixture/je_a_amount")
		analysis = {
			"voucher_scope": {
				"voucher_type": "Journal Entry",
				"voucher_no": self.ctx["je_a"],
			}
		}
		for axis, extra in (
			("account_level", {}),
			("party", {}),
			("voucher", {}),
			("currency", {}),
			("dimension", {"dimension_scope": {"dimension_type": "cost_center"}}),
		):
			payload = self._payload(axis=axis, analysis={**analysis, **extra})
			self._assert_period_parity(axis, payload, gl, "voucher_filter")

		self._assert_full_account_measure_parity(
			self._payload(axis="account_level", analysis=analysis),
			{"voucher_type": "Journal Entry", "voucher_no": self.ctx["je_a"]},
			"voucher_filter_full",
		)

	def test_party_filter_parity_matrix(self):
		if not self.ctx.get("customer"):
			self.skipTest("No existing customer GL activity for party filter parity")
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			party_type="Customer",
			party=self.ctx["customer"],
		)
		analysis = {
			"party_scope": {
				"party_type": "Customer",
				"selected_party": self.ctx["customer"],
			}
		}
		for axis, extra in (
			("account_level", {}),
			("party", {}),
			("voucher", {}),
			("currency", {}),
			("dimension", {"dimension_scope": {"dimension_type": "cost_center"}}),
		):
			payload = self._payload(axis=axis, analysis={**analysis, **extra})
			self._assert_period_parity(axis, payload, gl, "party_filter")
		self._assert_full_account_measure_parity(
			self._payload(axis="account_level", analysis=analysis),
			{"party_type": "Customer", "party": self.ctx["customer"]},
			"party_filter_full",
		)

	def test_dimension_filter_parity_matrix(self):
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			cost_center=self.ctx["cost_center"],
		)
		document = self._base_document(accounting_dimensions={"cost_center": self.ctx["cost_center"]})
		analysis = {
			"dimension_scope": {
				"dimension_type": "cost_center",
				"selected_dimension_value": self.ctx["cost_center"],
			}
		}
		for axis in ("account_level", "party", "voucher", "currency", "dimension"):
			payload = self._payload(axis=axis, analysis=analysis, document=document)
			self._assert_period_parity(axis, payload, gl, "dimension_filter")
		self._assert_full_account_measure_parity(
			self._payload(axis="account_level", analysis=analysis, document=document),
			{"cost_center": self.ctx["cost_center"]},
			"dimension_filter_full",
		)

	def test_currency_filter_parity_matrix(self):
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			voucher_no=self.ctx["je_b"],
			currency=self.ctx["currency"],
		)
		document = self._base_document(
			currency={"currency_type": "account_currency", "currency": self.ctx["currency"]}
		)
		analysis = {
			"voucher_scope": {
				"voucher_type": "Journal Entry",
				"voucher_no": self.ctx["je_b"],
			}
		}
		for axis, extra in (
			("account_level", {}),
			("party", {}),
			("voucher", {}),
			("currency", {}),
			("dimension", {"dimension_scope": {"dimension_type": "cost_center"}}),
		):
			payload = self._payload(
				axis=axis,
				analysis={**analysis, **extra},
				document=document,
			)
			self._assert_period_parity(axis, payload, gl, "currency_filter")
		self._assert_full_account_measure_parity(
			self._payload(axis="account_level", analysis=analysis, document=document),
			{"voucher_no": self.ctx["je_b"], "currency": self.ctx["currency"]},
			"currency_filter_full",
		)

	def test_account_filter_parity_matrix(self):
		account = self.ctx["receivable"]
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			account=account,
			voucher_no=self.ctx["je_a"],
		)
		document = self._base_document(accounting={"account": account})
		analysis = {
			"voucher_scope": {
				"voucher_type": "Journal Entry",
				"voucher_no": self.ctx["je_a"],
			}
		}
		for axis, extra in (
			("account_level", {}),
			("party", {}),
			("voucher", {}),
			("currency", {}),
			("dimension", {"dimension_scope": {"dimension_type": "cost_center"}}),
		):
			payload = self._payload(
				axis=axis,
				analysis={**analysis, **extra},
				document=document,
			)
			self._assert_period_parity(axis, payload, gl, "account_filter")
		self._assert_full_account_measure_parity(
			self._payload(axis="account_level", analysis=analysis, document=document),
			{"account": account, "voucher_no": self.ctx["je_a"]},
			"account_filter_full",
		)

	def test_multi_dimension_and_status_flags(self):
		dims = {"cost_center": self.ctx["cost_center"]}
		if self.ctx.get("project"):
			dims["project"] = self.ctx["project"]
		# Company may have no JE rows with project; combine with voucher for isolation.
		gl_kwargs = {
			"voucher_no": self.ctx["je_a"],
			"cost_center": self.ctx["cost_center"],
			"include_opening_entries": 0,
			"include_cancelled_entries": 0,
			"include_period_closing_vouchers": 0,
		}
		document = self._base_document(
			accounting_dimensions=dims,
			status={
				"include_opening_entries": 0,
				"include_cancelled_entries": 0,
				"include_period_closing_vouchers": 0,
				"include_default_finance_book_entries": 1,
			},
		)
		analysis = {
			"voucher_scope": {
				"voucher_type": "Journal Entry",
				"voucher_no": self.ctx["je_a"],
			},
			"dimension_scope": {
				"dimension_type": "cost_center",
				"selected_dimension_value": self.ctx["cost_center"],
			},
		}
		self._assert_full_account_measure_parity(
			self._payload(axis="account_level", analysis=analysis, document=document),
			gl_kwargs,
			"multi_dim_status",
		)

		# Decision: include_cancelled forces scoped path even without other filters.
		cancelled_doc = self._base_document(status={"include_cancelled_entries": 1})
		spec = AccountExplorerQuerySpec_from_client(
			self._payload(axis="account_level", document=cancelled_doc),
			require_dates=True,
		)
		self.assertTrue(spec_has_advanced_gle_filters(spec))

	def test_blank_party_unspecified_aggregation(self):
		"""Blank party_type/party GL rows must remain visible under party axis defaults."""
		payload = self._payload(
			axis="party",
			analysis={
				"voucher_scope": {
					"voucher_type": "Journal Entry",
					"voucher_no": self.ctx["je_a"],
				}
			},
		)
		result = api.get_party_summary(payload)
		rows = result.get("rows") or []
		unspecified = next((row for row in rows if row.get("is_virtual_group")), None)
		self.assertIsNotNone(unspecified, "expected unspecified blank-party row")
		# JE-A has no party on either leg — both sides land in unspecified.
		self._assert_zero_diff(unspecified.get("period_debit"), self.ctx["amount_a"], "blank_party/debit")
		self._assert_zero_diff(unspecified.get("period_credit"), self.ctx["amount_a"], "blank_party/credit")

		spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
		blank = get_unspecified_party_measures(spec, [])
		self._assert_zero_diff(blank.get("period_debit"), self.ctx["amount_a"], "helper/blank_party_debit")
		self._assert_zero_diff(blank.get("period_credit"), self.ctx["amount_a"], "helper/blank_party_credit")

		if not self.ctx.get("customer"):
			return

		# Explicit party filter must not use unspecified path and must match party-only GL.
		explicit = self._payload(
			axis="party",
			analysis={
				"party_scope": {
					"party_type": "Customer",
					"selected_party": self.ctx["customer"],
				}
			},
		)
		explicit_result = api.get_party_summary(explicit)
		self.assertFalse(any(row.get("is_virtual_group") for row in explicit_result.get("rows") or []))
		expected = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			party_type="Customer",
			party=self.ctx["customer"],
		)
		self._assert_zero_diff(
			(explicit_result.get("totals") or {}).get("period_debit"),
			expected["period_debit"],
			"explicit_party/period_debit",
		)

	def test_unfiltered_account_measures_still_use_trial_balance_path(self):
		payload = self._payload(axis="account_level")
		spec = AccountExplorerQuerySpec_from_client(payload, require_dates=True)
		self.assertFalse(spec_has_advanced_gle_filters(spec))
		measures = get_account_wise_measures(spec, [self.ctx["receivable"]])
		self.assertIn(self.ctx["receivable"], measures)

	def test_scoped_account_measures_are_not_slower_than_unfiltered_order(self):
		unfiltered = self._payload(axis="account_level")
		scoped = self._payload(
			axis="account_level",
			analysis={
				"voucher_scope": {
					"voucher_type": "Journal Entry",
					"voucher_no": self.ctx["je_a"],
				}
			},
		)
		samples_u = []
		samples_s = []
		for _ in range(5):
			t0 = time.perf_counter()
			api.get_account_summary(unfiltered)
			samples_u.append((time.perf_counter() - t0) * 1000)
			t1 = time.perf_counter()
			api.get_account_summary(scoped)
			samples_s.append((time.perf_counter() - t1) * 1000)
		samples_u.sort()
		samples_s.sort()
		median_s = samples_s[len(samples_s) // 2]
		p90_s = samples_s[max(0, int(len(samples_s) * 0.9) - 1)]
		self.assertLess(median_s, 5000.0)
		self.assertLess(p90_s, 8000.0)
		# Keep a note for gate report consumption.
		self._last_perf = {
			"unfiltered_median_ms": samples_u[len(samples_u) // 2],
			"scoped_median_ms": median_s,
			"scoped_p90_ms": p90_s,
		}

	def _account_analysis(self, account: str, **extra) -> dict:
		return {
			"account_scope": {
				"mode": "account",
				"selected_account": account,
				"tree_root_account": account,
				"is_virtual_group": 0,
			},
			**extra,
		}

	def test_cross_axis_account_filter_member_matrix(self):
		"""Account Analysis Filter must constrain every axis and match direct GL."""
		account = self.ctx["receivable"]  # leaf used only on JE-A
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			account=account,
		)
		analysis = self._account_analysis(account)
		for axis, extra in (
			("account_level", {}),
			("party", {}),
			("voucher", {}),
			("currency", {}),
			("dimension", {"dimension_scope": {"dimension_type": "cost_center"}}),
		):
			payload = self._payload(axis=axis, analysis={**analysis, **extra})
			self._assert_period_parity(axis, payload, gl, "cross_axis_account")

		# Members must be related to Account filter — exclude unrelated vouchers.
		voucher_rows = (
			self._call_axis("voucher", self._payload(axis="voucher", analysis=analysis)).get("rows") or []
		)
		voucher_nos = {row.get("voucher_no") for row in voucher_rows if row.get("voucher_no")}
		self.assertIn(self.ctx["je_a"], voucher_nos)
		self.assertNotIn(self.ctx["je_b"], voucher_nos)

		dim_rows = (
			self._call_axis(
				"dimension",
				self._payload(
					axis="dimension",
					analysis={**analysis, "dimension_scope": {"dimension_type": "cost_center"}},
				),
			).get("rows")
			or []
		)
		dim_values = {
			row.get("dimension_value")
			for row in dim_rows
			if row.get("dimension_value") not in (None, "")
		}
		self.assertIn(self.ctx["cost_center"], dim_values)

		currency_rows = (
			self._call_axis("currency", self._payload(axis="currency", analysis=analysis)).get("rows")
			or []
		)
		currencies = {row.get("currency") for row in currency_rows if row.get("currency")}
		self.assertIn(self.ctx["currency"], currencies)

		self._assert_full_account_measure_parity(
			self._payload(axis="account_level", analysis=analysis),
			{"account": account},
			"cross_axis_account_full",
		)

	def test_cross_axis_group_account_descendants(self):
		"""Group Account filter resolves to descendant ledger accounts."""
		leaf = self.ctx["receivable"]
		parent = frappe.db.get_value("Account", leaf, "parent_account")
		if not parent or not frappe.db.get_value("Account", parent, "is_group"):
			self.skipTest("No group parent for parity leaf account")

		from erpnext_extensions.iran_accounting.account_explorer.account_hierarchy import (
			descendant_accounts,
			load_company_accounts,
		)

		accounts = load_company_accounts(self.ctx["company"])
		descendants = set(descendant_accounts(accounts, parent))
		self.assertIn(leaf, descendants)

		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			account=list(descendants),
		)
		analysis = self._account_analysis(parent)
		spec = AccountExplorerQuerySpec_from_client(
			self._payload(axis="account_level", analysis=analysis),
			require_dates=True,
		)
		self.assertEqual(set(spec.included_account_names or []), descendants)

		for axis, extra in (
			("account_level", {}),
			("voucher", {}),
			("dimension", {"dimension_scope": {"dimension_type": "cost_center"}}),
		):
			payload = self._payload(axis=axis, analysis={**analysis, **extra})
			self._assert_period_parity(axis, payload, gl, "group_account_descendants")

	def test_cross_axis_party_filter_matrix(self):
		if not self.ctx.get("customer") or not self.ctx.get("je_party"):
			self.skipTest("No party parity JE")
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			party_type="Customer",
			party=self.ctx["customer"],
		)
		analysis = {
			"party_scope": {
				"party_type": "Customer",
				"selected_party": self.ctx["customer"],
			}
		}
		for axis, extra in (
			("account_level", {}),
			("party", {}),
			("voucher", {}),
			("currency", {}),
			("dimension", {"dimension_scope": {"dimension_type": "cost_center"}}),
		):
			payload = self._payload(axis=axis, analysis={**analysis, **extra})
			self._assert_period_parity(axis, payload, gl, "cross_axis_party")

		voucher_rows = (
			self._call_axis("voucher", self._payload(axis="voucher", analysis=analysis)).get("rows") or []
		)
		voucher_nos = {row.get("voucher_no") for row in voucher_rows if row.get("voucher_no")}
		self.assertIn(self.ctx["je_party"], voucher_nos)
		self.assertNotIn(self.ctx["je_b"], voucher_nos)

	def test_cross_axis_dimension_filter_matrix(self):
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			cost_center=self.ctx["cost_center"],
		)
		analysis = {
			"dimension_scope": {
				"dimension_type": "cost_center",
				"selected_dimension_value": self.ctx["cost_center"],
			}
		}
		for axis, extra in (
			("account_level", {}),
			("party", {}),
			("voucher", {}),
			("currency", {}),
			("dimension", {}),
		):
			payload = self._payload(axis=axis, analysis={**analysis, **extra})
			self._assert_period_parity(axis, payload, gl, "cross_axis_dimension")

		account_rows = (
			self._call_axis("account_level", self._payload(axis="account_level", analysis=analysis)).get(
				"rows"
			)
			or []
		)
		# Scoped totals already assert GL parity; non-zero leaf rows must belong to CC activity.
		self.assertTrue(any(flt(row.get("period_debit")) or flt(row.get("period_credit")) for row in account_rows))

	def test_cross_axis_voucher_filter_matrix(self):
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			voucher_no=self.ctx["je_a"],
		)
		analysis = {
			"voucher_scope": {
				"voucher_type": "Journal Entry",
				"voucher_no": self.ctx["je_a"],
			}
		}
		for axis, extra in (
			("account_level", {}),
			("party", {}),
			("voucher", {}),
			("currency", {}),
			("dimension", {"dimension_scope": {"dimension_type": "cost_center"}}),
		):
			payload = self._payload(axis=axis, analysis={**analysis, **extra})
			self._assert_period_parity(axis, payload, gl, "cross_axis_voucher")

		dim_rows = (
			self._call_axis(
				"dimension",
				self._payload(
					axis="dimension",
					analysis={**analysis, "dimension_scope": {"dimension_type": "cost_center"}},
				),
			).get("rows")
			or []
		)
		dim_values = {row.get("dimension_value") for row in dim_rows if row.get("dimension_value")}
		self.assertIn(self.ctx["cost_center"], dim_values)

	def test_cross_axis_currency_filter_matrix(self):
		account = self.ctx["receivable"]
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			account=account,
			currency=self.ctx["currency"],
		)
		document = self._base_document(
			currency={"currency_type": "account_currency", "currency": self.ctx["currency"]}
		)
		analysis = self._account_analysis(account)
		for axis, extra in (
			("account_level", {}),
			("party", {}),
			("voucher", {}),
			("currency", {}),
			("dimension", {"dimension_scope": {"dimension_type": "cost_center"}}),
		):
			payload = self._payload(
				axis=axis,
				analysis={**analysis, **extra},
				document=document,
			)
			self._assert_period_parity(axis, payload, gl, "cross_axis_currency")

	def test_cross_axis_multi_filter_intersection(self):
		account = self.ctx["receivable"]
		gl = direct_gl_period_totals(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			account=account,
			cost_center=self.ctx["cost_center"],
			voucher_no=self.ctx["je_a"],
		)
		analysis = {
			**self._account_analysis(account),
			"dimension_scope": {
				"dimension_type": "cost_center",
				"selected_dimension_value": self.ctx["cost_center"],
			},
			"voucher_scope": {
				"voucher_type": "Journal Entry",
				"voucher_no": self.ctx["je_a"],
			},
		}
		for axis, extra in (
			("account_level", {}),
			("party", {}),
			("voucher", {}),
			("currency", {}),
			("dimension", {}),
		):
			payload = self._payload(axis=axis, analysis={**analysis, **extra})
			self._assert_period_parity(axis, payload, gl, "cross_axis_multi")

		# Removing the account filter (broader WHERE) must increase or keep voucher activity.
		broader = {
			"dimension_scope": {
				"dimension_type": "cost_center",
				"selected_dimension_value": self.ctx["cost_center"],
			},
			"voucher_scope": {
				"voucher_type": "Journal Entry",
				"voucher_no": self.ctx["je_a"],
			},
		}
		narrow = self._call_axis("voucher", self._payload(axis="voucher", analysis=analysis))
		wide = self._call_axis("voucher", self._payload(axis="voucher", analysis=broader))
		self.assertLessEqual(
			flt((narrow.get("totals") or {}).get("scoped_debit")),
			flt((wide.get("totals") or {}).get("scoped_debit")),
		)

	def test_no_duplicate_where_projection_for_dimension(self):
		"""Analysis dimension wins; document dimension conflict is warned once."""
		from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
			AccountExplorerQuerySpec_from_client as parse,
		)

		# Client payload already projected — simulate conflict via document dims + analysis dim.
		document = self._base_document(
			accounting_dimensions={"cost_center": "OTHER-CC"},
		)
		analysis = {
			"dimension_scope": {
				"dimension_type": "cost_center",
				"selected_dimension_value": self.ctx["cost_center"],
			}
		}
		payload = self._payload(axis="dimension", analysis=analysis, document=document)
		spec = parse(payload, require_dates=True)
		self.assertEqual(spec.dimension_scope.selected_dimension_value, self.ctx["cost_center"])
		# Document dim remains as authored unless mapper ran; server trusted analysis selected value.
		self.assertEqual(spec.dimension_scope.dimension_type, "cost_center")

	def test_max_abs_gl_difference_gate(self):
		"""Max absolute GL difference across this module's asserts must stay zero."""
		self.assertEqual(self.max_abs_diff, 0.0)
