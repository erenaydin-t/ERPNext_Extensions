# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Query count observation for OpeningEntryPolicy engines (acceptance gate)."""

from __future__ import annotations

import json

import frappe

from erpnext_extensions.iran_accounting.account_explorer.currency_summary import build_currency_summary
from erpnext_extensions.iran_accounting.account_explorer.dimension_summary import build_dimension_summary
from erpnext_extensions.iran_accounting.account_explorer.opening_balance import get_account_wise_measures
from erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy import (
	AccountAxisEngine,
	acb_applicable,
	last_pcv_before_from_date,
	opening_flagged_baked_in_acb,
	select_account_axis_engine,
)
from erpnext_extensions.iran_accounting.account_explorer.party_summary import build_party_summary
from erpnext_extensions.iran_accounting.account_explorer.query_spec import AccountExplorerQuerySpec_from_client
from erpnext_extensions.iran_accounting.account_explorer.voucher_summary import build_voucher_summary
from erpnext_extensions.iran_accounting.tests.opening_policy_golden_fixtures import FROM_DATE, TO_DATE

# Upper bounds (not exact counts — Frappe metadata queries may vary slightly).
E1_OFF_MAX = 25
E1_ON_MAX = 25
E1_OFF_ON_DELTA_MAX = 5
E3_FILTERED_MAX = 15
ENGINE_HELPER_MAX_PER_REQUEST = 1


def _count(fn):
	original_sql = frappe.db.sql
	queries = {"n": 0}

	def wrapped_sql(*args, **kwargs):
		queries["n"] += 1
		return original_sql(*args, **kwargs)

	frappe.db.sql = wrapped_sql
	try:
		fn()
	finally:
		frappe.db.sql = original_sql
	return queries["n"]


def _reset_policy_request_cache() -> None:
	if hasattr(frappe.local, "_ae_opening_policy_cache"):
		del frappe.local._ae_opening_policy_cache


def _count_engine_helper_calls(spec):
	_reset_policy_request_cache()
	counters: dict[str, int] = {}

	import erpnext_extensions.iran_accounting.account_explorer.opening_balance as ob

	original = ob.select_account_axis_engine

	def counting_select(spec_arg):
		counters["select_account_axis_engine"] = counters.get("select_account_axis_engine", 0) + 1
		return original(spec_arg)

	ob.select_account_axis_engine = counting_select
	try:
		get_account_wise_measures(spec)
	finally:
		ob.select_account_axis_engine = original

	from erpnext_extensions.iran_accounting.account_explorer import opening_entry_policy as oep

	cache = getattr(frappe.local, "_ae_opening_policy_cache", {})
	# Memoization should collapse PCV/ACB reads to a single cache entry per request.
	counters["policy_cache_entries"] = len(cache)
	return counters


@frappe.whitelist()
def observe_opening_policy_query_counts(company: str = "_Test Company") -> str:
	frappe.set_user("Administrator")
	_reset_policy_request_cache()
	base_doc = {
		"company": company,
		"fiscal_year": "2026",
		"from_date": str(FROM_DATE),
		"to_date": str(TO_DATE),
		"hide_zero_rows": 0,
		"status": {"include_opening_entries": 0},
	}

	def spec(axis: str, **extra):
		payload = json.dumps(
			{
				"document_scope": {**base_doc, **extra.get("document", {})},
				"analysis_context": {
					"view_axis": axis,
					"detail_mode": "summary",
					"page_size": 50,
					"page": 1,
					**extra.get("analysis", {}),
				},
			}
		)
		return AccountExplorerQuerySpec_from_client(payload, require_dates=True)

	off_spec = spec("account_level")
	on_spec = spec("account_level", document={"status": {"include_opening_entries": 1}})
	e3_spec = spec("account_level", document={"accounting": {"account": "Stock In Hand - _TC"}})

	# ERPNext Trial Balance caches chart-of-accounts on first call; warm up so
	# OFF vs ON counts reflect policy path rather than cold-start asymmetry.
	_count(lambda: get_account_wise_measures(off_spec))
	_reset_policy_request_cache()

	counts = {
		"E1_account_unfiltered_off": _count(lambda: get_account_wise_measures(off_spec)),
		"E1_account_unfiltered_on": _count(lambda: get_account_wise_measures(on_spec)),
		"E3_account_filtered_off": _count(lambda: get_account_wise_measures(e3_spec)),
		"party_summary": _count(lambda: build_party_summary(spec("party"))),
		"dimension_summary": _count(
			lambda: build_dimension_summary(
				spec("dimension", analysis={"dimension_scope": {"dimension_type": "cost_center"}})
			)
		),
		"currency_summary": _count(lambda: build_currency_summary(spec("currency"))),
		"voucher_summary": _count(lambda: build_voucher_summary(spec("voucher"))),
		"engine_off": select_account_axis_engine(off_spec).value,
		"engine_on": select_account_axis_engine(on_spec).value,
		"engine_e3_filtered": select_account_axis_engine(e3_spec).value,
		"engine_helper_calls_off": _count_engine_helper_calls(off_spec),
	}
	return json.dumps(counts)


if __name__ == "__main__":
	print(observe_opening_policy_query_counts())
