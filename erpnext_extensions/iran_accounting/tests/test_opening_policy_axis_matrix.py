# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""24-cell OpeningEntryPolicy axis matrix with independent direct-GL baselines."""

from __future__ import annotations

import json
import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.opening_policy_pcv_acb_fixtures import cleanup_pcv_acb
from erpnext_extensions.iran_accounting.tests.opening_policy_axis_matrix_fixtures import (
	cleanup_axis_matrix,
	ensure_axis_matrix_context,
)
from erpnext_extensions.iran_accounting.account_explorer.measures import finalize_measures
from erpnext_extensions.iran_accounting.tests.analytical_parity_fixtures import (
	direct_gl_opening_totals,
	direct_gl_period_totals,
	full_measures_from_opening_period,
)
from erpnext_extensions.iran_accounting.tests.opening_policy_direct_gl import (
	direct_gl_policy_measures,
	voucher_axis_direct_totals,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	enable_wave2c_unified_party,
	require_site,
)

MEASURE_FIELDS = (
	"opening_debit",
	"opening_credit",
	"period_debit",
	"period_credit",
	"net_balance",
)

AXIS_API = {
	"account_level": api.get_account_summary,
	"party": api.get_party_summary,
	"dimension": api.get_dimension_summary,
	"currency": api.get_currency_summary,
	"voucher": api.get_voucher_summary,
	"unified_party": api.get_unified_party_summary,
}

MATRIX_CELLS: list[tuple[str, bool, bool, str]] = []
for _axis in (
	"account_level",
	"party",
	"unified_party",
	"dimension",
	"currency",
	"voucher",
):
	for _include in (False, True):
		for _filtered in (False, True):
			_cell = f"{_axis}|{'ON' if _include else 'OFF'}|{'filtered' if _filtered else 'unfiltered'}"
			MATRIX_CELLS.append((_axis, _include, _filtered, _cell))


class TestOpeningPolicyAxisMatrix(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.company = require_site(cls)
		if not cls.company:
			raise unittest.SkipTest("No test company")
		enable_wave2c_unified_party()
		frappe.set_user("Administrator")
		cleanup_pcv_acb(cls.company)
		cls.ctx = ensure_axis_matrix_context(cls.company)
		cls.max_abs_diff = 0.0

	@classmethod
	def tearDownClass(cls):
		cleanup_axis_matrix(cls.company)

	def _base_document(self, *, include_opening_entries: bool) -> dict:
		return {
			"company": self.ctx["company"],
			"fiscal_year": self.ctx["fiscal_year"],
			"from_date": self.ctx["from_date"],
			"to_date": self.ctx["to_date"],
			"hide_zero_rows": 0,
			"status": {
				"include_opening_entries": 1 if include_opening_entries else 0,
				"include_cancelled_entries": 0,
				"include_period_closing_vouchers": 0,
				"include_default_finance_book_entries": 1,
			},
		}

	def _filter_kwargs(self, axis: str, filtered: bool) -> dict:
		if not filtered:
			return {}
		if axis == "account_level":
			return {"account": self.ctx["target_account"]}
		if axis == "party":
			return {"party_type": "Customer", "party": self.ctx["customer"]}
		if axis == "unified_party":
			return {"party_type": "Customer", "party": self.ctx["customer"]} if filtered else {}
		if axis == "dimension":
			return {"cost_center": self.ctx["cost_center"]}
		if axis == "currency":
			return {"currency": self.ctx["currency"]}
		if axis == "voucher":
			return {
				"voucher_type": self.ctx["voucher_type"],
				"voucher_no": self.ctx["voucher_no"],
			}
		return {}

	def _analysis_context(self, axis: str, filtered: bool) -> dict:
		analysis = {
			"view_axis": axis,
			"detail_mode": "summary",
			"page": 1,
			"page_size": 500,
		}
		if axis == "dimension":
			analysis["dimension_scope"] = {"dimension_type": "cost_center"}
			if filtered:
				analysis["dimension_scope"]["selected_dimension_value"] = self.ctx["cost_center"]
			return analysis
		if not filtered:
			return analysis
		if axis == "account_level":
			analysis["account_scope"] = {
				"mode": "tree",
				"selected_account": self.ctx["target_account"],
			}
			return analysis
		if axis == "party":
			analysis["party_scope"] = {
				"party_type": "Customer",
				"selected_party": self.ctx["customer"],
			}
			return analysis
		if axis == "unified_party":
			analysis["unified_party_scope"] = {
				"selected_unified_party": self.ctx["uap_name"],
			}
			return analysis
		if axis == "voucher":
			analysis["voucher_scope"] = {
				"voucher_type": self.ctx["voucher_type"],
				"voucher_no": self.ctx["voucher_no"],
			}
		return analysis

	def _document_scope(self, axis: str, filtered: bool, *, include_opening_entries: bool) -> dict:
		document = self._base_document(include_opening_entries=include_opening_entries)
		if not filtered:
			return document
		if axis == "account_level":
			document["accounting"] = {"account": self.ctx["target_account"]}
		elif axis == "currency":
			document["currency"] = {
				"currency_type": "account_currency",
				"currency": self.ctx["currency"],
			}
		elif axis == "dimension":
			document["accounting_dimensions"] = {"cost_center": self.ctx["cost_center"]}
		elif axis == "voucher":
			document["voucher"] = {
				"voucher_type": self.ctx["voucher_type"],
				"voucher_no": self.ctx["voucher_no"],
			}
		return document

	def _payload(self, axis: str, *, include_opening_entries: bool, filtered: bool) -> str:
		return json.dumps(
			{
				"document_scope": self._document_scope(
					axis, filtered, include_opening_entries=include_opening_entries
				),
				"analysis_context": self._analysis_context(axis, filtered),
			}
		)

	def _unified_party_member_tuples(self, filtered: bool) -> list[tuple[str, str]]:
		if filtered:
			return [("Customer", self.ctx["customer"])]
		members: list[tuple[str, str]] = []
		for uap in frappe.get_all(
			"Unified Accounting Party",
			filters={"company": self.company, "status": "Active"},
			pluck="name",
		):
			for row in frappe.get_all(
				"Unified Accounting Party Member",
				filters={"parent": uap},
				fields=["party_type", "party"],
			):
				if row.party_type and row.party:
					members.append((row.party_type, row.party))
		return list(dict.fromkeys(members))

	def _direct_unified_party(self, *, include_opening_entries: bool, filtered: bool) -> dict:
		opening = {"opening_debit": 0.0, "opening_credit": 0.0}
		period = {"period_debit": 0.0, "period_credit": 0.0}
		include_flag = 1 if include_opening_entries else 0
		for party_type, party in self._unified_party_member_tuples(filtered):
			o = direct_gl_opening_totals(
				self.ctx["company"],
				self.ctx["from_date"],
				self.ctx["to_date"],
				include_opening_entries=include_flag,
				party_type=party_type,
				party=party,
			)
			p = direct_gl_period_totals(
				self.ctx["company"],
				self.ctx["from_date"],
				self.ctx["to_date"],
				include_opening_entries=include_flag,
				party_type=party_type,
				party=party,
			)
			opening["opening_debit"] += flt(o["opening_debit"])
			opening["opening_credit"] += flt(o["opening_credit"])
			period["period_debit"] += flt(p["period_debit"])
			period["period_credit"] += flt(p["period_credit"])
		return finalize_measures(full_measures_from_opening_period(opening, period))

	def _direct_unspecified_party(self, *, include_opening_entries: bool) -> dict[str, float]:
		include_flag = 1 if include_opening_entries else 0
		opening_cond = "posting_date < %(from_date)s"
		if not include_flag:
			opening_cond += " and is_opening='No'"
		opening = frappe.db.sql(
			f"""
			select coalesce(sum(debit),0) as debit, coalesce(sum(credit),0) as credit
			from `tabGL Entry`
			where company=%(company)s and ifnull(party,'')='' and is_cancelled=0
			  and voucher_type != 'Period Closing Voucher' and {opening_cond}
			""",
			{
				"company": self.ctx["company"],
				"from_date": self.ctx["from_date"],
			},
			as_dict=True,
		)[0]
		period = frappe.db.sql(
			"""
			select coalesce(sum(debit),0) as debit, coalesce(sum(credit),0) as credit
			from `tabGL Entry`
			where company=%(company)s and ifnull(party,'')='' and is_cancelled=0
			  and voucher_type != 'Period Closing Voucher'
			  and posting_date between %(from_date)s and %(to_date)s
			"""
			+ ("" if include_flag else " and is_opening='No'"),
			{
				"company": self.ctx["company"],
				"from_date": self.ctx["from_date"],
				"to_date": self.ctx["to_date"],
			},
			as_dict=True,
		)[0]
		od, oc = flt(opening.debit), flt(opening.credit)
		if od > oc:
			opening_m = {"opening_debit": od - oc, "opening_credit": 0.0}
		else:
			opening_m = {"opening_debit": 0.0, "opening_credit": oc - od}
		period_m = {"period_debit": flt(period.debit), "period_credit": flt(period.credit)}
		return full_measures_from_opening_period(opening_m, period_m)

	def _direct_party_axis(self, *, include_opening_entries: bool, filtered: bool) -> dict:
		include_flag = 1 if include_opening_entries else 0
		opening = {"opening_debit": 0.0, "opening_credit": 0.0}
		period = {"period_debit": 0.0, "period_credit": 0.0}
		if filtered:
			parties = [("Customer", self.ctx["customer"])]
		else:
			parties = frappe.db.sql(
				"""
				select distinct party_type, party
				from `tabGL Entry`
				where company=%s and ifnull(party_type,'')!='' and ifnull(party,'')!='' and is_cancelled=0
				""",
				self.ctx["company"],
				as_dict=True,
			)
			parties = [(row.party_type, row.party) for row in parties]
			unspecified = self._direct_unspecified_party(include_opening_entries=include_opening_entries)
			opening["opening_debit"] += flt(unspecified["opening_debit"])
			opening["opening_credit"] += flt(unspecified["opening_credit"])
			period["period_debit"] += flt(unspecified["period_debit"])
			period["period_credit"] += flt(unspecified["period_credit"])
		for party_type, party in parties:
			o = direct_gl_opening_totals(
				self.ctx["company"],
				self.ctx["from_date"],
				self.ctx["to_date"],
				include_opening_entries=include_flag,
				party_type=party_type,
				party=party,
			)
			p = direct_gl_period_totals(
				self.ctx["company"],
				self.ctx["from_date"],
				self.ctx["to_date"],
				include_opening_entries=include_flag,
				party_type=party_type,
				party=party,
			)
			opening["opening_debit"] += flt(o["opening_debit"])
			opening["opening_credit"] += flt(o["opening_credit"])
			period["period_debit"] += flt(p["period_debit"])
			period["period_credit"] += flt(p["period_credit"])
		return finalize_measures(full_measures_from_opening_period(opening, period))

	def _direct_dimension_axis(self, *, include_opening_entries: bool, filtered: bool) -> dict:
		kwargs = {"cost_center": self.ctx["cost_center"]} if filtered else {}
		return direct_gl_policy_measures(
			self.ctx["company"],
			self.ctx["from_date"],
			self.ctx["to_date"],
			include_opening_entries=include_opening_entries,
			**kwargs,
		)

	def _direct_baseline(self, axis: str, *, include_opening_entries: bool, filtered: bool) -> dict:
		kwargs = self._filter_kwargs(axis, filtered)
		if axis == "unified_party":
			base = self._direct_unified_party(
				include_opening_entries=include_opening_entries, filtered=filtered
			)
		elif axis == "party":
			base = self._direct_party_axis(
				include_opening_entries=include_opening_entries, filtered=filtered
			)
		elif axis == "dimension":
			base = self._direct_dimension_axis(
				include_opening_entries=include_opening_entries, filtered=filtered
			)
		elif axis == "voucher":
			return voucher_axis_direct_totals(
				self.ctx["company"],
				self.ctx["from_date"],
				self.ctx["to_date"],
				include_opening_entries=include_opening_entries,
				**kwargs,
			)
		else:
			base = direct_gl_policy_measures(
				self.ctx["company"],
				self.ctx["from_date"],
				self.ctx["to_date"],
				include_opening_entries=include_opening_entries,
				**kwargs,
			)
		if axis in ("party", "dimension", "currency"):
			if axis in ("dimension", "currency"):
				base["opening_debit"] = 0.0
				base["opening_credit"] = 0.0
		return base

	def _compare_fields(self, axis: str) -> tuple[str, ...]:
		if axis == "party":
			return MEASURE_FIELDS
		if axis in ("dimension", "currency"):
			return ("period_debit", "period_credit", "net_balance")
		if axis == "voucher":
			return ("scoped_debit", "scoped_credit", "scoped_net")
		return MEASURE_FIELDS

	def _assert_cell(self, axis: str, *, include_opening_entries: bool, filtered: bool, cell_id: str):
		payload = self._payload(axis, include_opening_entries=include_opening_entries, filtered=filtered)
		result = AXIS_API[axis](payload)
		totals = result.get("totals") or {}
		expected = self._direct_baseline(axis, include_opening_entries=include_opening_entries, filtered=filtered)

		if axis == "voucher":
			for field, gl_field in (
				("scoped_debit", "scoped_debit"),
				("scoped_credit", "scoped_credit"),
				("scoped_net", "scoped_net"),
			):
				diff = abs(flt(totals.get(field)) - flt(expected.get(gl_field)))
				self.max_abs_diff = max(self.max_abs_diff, diff)
				self.assertEqual(diff, 0, f"{cell_id}/{field}: AE={totals.get(field)} GL={expected.get(gl_field)}")
			return

		for field in self._compare_fields(axis):
			diff = abs(flt(totals.get(field)) - flt(expected.get(field)))
			self.max_abs_diff = max(self.max_abs_diff, diff)
			self.assertEqual(diff, 0, f"{cell_id}/{field}: AE={totals.get(field)} GL={expected.get(field)}")

	def test_opening_policy_axis_matrix_24_cells(self):
		for axis, include_opening, filtered, cell_id in MATRIX_CELLS:
			with self.subTest(cell=cell_id):
				self._assert_cell(
					axis,
					include_opening_entries=include_opening,
					filtered=filtered,
					cell_id=cell_id,
				)

	def test_matrix_gf10_anchor_off_on_filtered_account(self):
		"""Sanity: dedicated GF-10 amounts on target account (filtered account axis)."""
		for include, opening_debit, period_debit in (
			(False, 400.0, 500.0),
			(True, 500.0, 800.0),
		):
			expected = direct_gl_policy_measures(
				self.ctx["company"],
				self.ctx["from_date"],
				self.ctx["to_date"],
				include_opening_entries=include,
				account=self.ctx["target_account"],
			)
			self.assertEqual(flt(expected["opening_debit"]), opening_debit)
			self.assertEqual(flt(expected["period_debit"]), period_debit)
