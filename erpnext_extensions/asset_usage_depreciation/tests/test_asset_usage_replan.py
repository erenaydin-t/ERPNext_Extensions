# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Integration tests for Asset Usage Depreciation replan.

Uses ``unittest.TestCase`` (not FrappeTestCase) to avoid ERPNext BootStrapTestData
side-effects during discovery. Run::

    bench --site development.localhost run-tests \\
        --module erpnext_extensions.asset_usage_depreciation.tests.test_asset_usage_replan \\
        --skip-before-tests
"""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, getdate, random_string

from erpnext_extensions.asset_usage_depreciation.constants import (
	COMPANY_FIELD_REDUCED_HANDLING,
	HANDLING_EXTEND,
	HANDLING_REDISTRIBUTE,
)
from erpnext_extensions.asset_usage_depreciation.custom_fields import ensure_custom_fields


def _ensure_company_handling(company: str, handling: str):
	ensure_custom_fields()
	frappe.db.set_value("Company", company, COMPANY_FIELD_REDUCED_HANDLING, handling)


def _unique_asset_name(prefix: str) -> str:
	return f"{prefix}-{random_string(6)}"


def _make_sl_asset(**kwargs):
	company = kwargs.get("company") or "_Test Company"
	asset_name = kwargs.get("asset_name") or _unique_asset_name("AUD-Asset")

	asset = frappe.get_doc(
		{
			"doctype": "Asset",
			"asset_name": asset_name,
			"asset_category": "Computers",
			"item_code": kwargs.get("item_code") or "Macbook Pro",
			"company": company,
			"purchase_date": kwargs.get("purchase_date") or "2026-01-01",
			"available_for_use_date": kwargs.get("available_for_use_date") or "2026-01-01",
			"calculate_depreciation": 1,
			"net_purchase_amount": kwargs.get("net_purchase_amount") or 120000,
			"purchase_amount": kwargs.get("purchase_amount") or 120000,
			"warehouse": kwargs.get("warehouse") or "_Test Warehouse - _TC",
			"location": kwargs.get("location") or "Test Location",
			"asset_owner": "Company",
			"asset_type": "Existing Asset",
			"asset_quantity": 1,
			"finance_books": [
				{
					"finance_book": kwargs.get("finance_book"),
					"depreciation_method": kwargs.get("depreciation_method") or "Straight Line",
					"frequency_of_depreciation": kwargs.get("frequency_of_depreciation") or 1,
					"total_number_of_depreciations": kwargs.get("total_number_of_depreciations") or 12,
					"expected_value_after_useful_life": kwargs.get("expected_value_after_useful_life") or 0,
					"depreciation_start_date": kwargs.get("depreciation_start_date") or "2026-01-31",
					"daily_prorata_based": kwargs.get("daily_prorata_based") or 0,
					"shift_based": kwargs.get("shift_based") or 0,
					"rate_of_depreciation": kwargs.get("rate_of_depreciation") or 0,
				}
			],
		}
	)
	asset.insert()
	asset.submit()
	return asset


def _submit_usage(asset, from_date, mode, percentage=None, to_date=None, reason="test"):
	doc = frappe.get_doc(
		{
			"doctype": "Asset Usage Period",
			"asset": asset.name if hasattr(asset, "name") else asset,
			"from_date": from_date,
			"to_date": to_date,
			"depreciation_mode": mode,
			"depreciation_percentage": percentage,
			"reason": reason,
		}
	)
	doc.insert()
	doc.submit()
	return doc


def _active_schedule(asset_name):
	from erpnext.assets.doctype.asset_depreciation_schedule.asset_depreciation_schedule import (
		get_asset_depr_schedule_doc,
	)

	asset = frappe.get_doc("Asset", asset_name)
	fb = asset.finance_books[0].finance_book
	return get_asset_depr_schedule_doc(asset_name, "Active", fb)


def _unposted_amounts(ads):
	return [flt(r.depreciation_amount) for r in ads.depreciation_schedule if not r.journal_entry]


def _post_first_n(ads_name, n):
	"""Mark the first n schedule rows as posted by linking a real submitted Depreciation Entry JE.

	Uses direct link after creating a JE so the test does not depend on ERPNext's
	JE↔schedule matching quirks in this site (persian_calendar overrides).
	"""
	from erpnext.assets.doctype.asset.depreciation import get_depreciation_accounts

	ads = frappe.get_doc("Asset Depreciation Schedule", ads_name)
	asset = frappe.get_doc("Asset", ads.asset)
	_fa, accum, expense = get_depreciation_accounts(asset.asset_category, asset.company)

	posted = 0
	for row in ads.depreciation_schedule:
		if posted >= n:
			break
		if row.journal_entry:
			posted += 1
			continue

		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Depreciation Entry",
				"company": asset.company,
				"posting_date": row.schedule_date,
				"finance_book": ads.finance_book,
				"accounts": [
					{
						"account": expense,
						"debit_in_account_currency": row.depreciation_amount,
						"reference_type": "Asset",
						"reference_name": asset.name,
					},
					{
						"account": accum,
						"credit_in_account_currency": row.depreciation_amount,
						"reference_type": "Asset",
						"reference_name": asset.name,
					},
				],
			}
		)
		je.flags.ignore_permissions = True
		# Avoid double NBV updates from JE.submit asset hooks during test setup
		je.flags.ignore_links = True
		je.insert()
		# Submit without relying on schedule matcher — link manually
		frappe.db.set_value("Journal Entry", je.name, "docstatus", 1)
		frappe.db.set_value("Depreciation Schedule", row.name, "journal_entry", je.name)
		# Reduce NBV like core would
		fb = asset.finance_books[0]
		fb.value_after_depreciation = flt(fb.value_after_depreciation) - flt(row.depreciation_amount)
		fb.db_update()
		posted += 1

	ads.reload()


class TestAssetUsageReplanIntegration(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		ensure_custom_fields()

	def tearDown(self):
		frappe.db.rollback()

	def test_monthly_percentage_extend_does_not_inflate_next(self):
		_ensure_company_handling("_Test Company", HANDLING_EXTEND)
		asset = _make_sl_asset()
		ads = _active_schedule(asset.name)
		standard = flt(ads.depreciation_schedule[0].depreciation_amount)

		_submit_usage(asset, "2026-02-01", "Percentage", 30, to_date="2026-02-28")

		ads = _active_schedule(asset.name)
		self.assertAlmostEqual(flt(ads.depreciation_schedule[0].depreciation_amount), standard)
		self.assertAlmostEqual(flt(ads.depreciation_schedule[1].depreciation_amount), flt(standard * 0.3))
		self.assertAlmostEqual(flt(ads.depreciation_schedule[2].depreciation_amount), standard)
		self.assertGreaterEqual(len(ads.depreciation_schedule), 12)

	def test_mid_month_non_daily_uses_schedule_date(self):
		_ensure_company_handling("_Test Company", HANDLING_EXTEND)
		asset = _make_sl_asset()
		ads = _active_schedule(asset.name)
		apr_before = next(
			r for r in ads.depreciation_schedule if getdate(r.schedule_date) == getdate("2026-04-30")
		)
		standard = flt(apr_before.depreciation_amount)

		_submit_usage(asset, "2026-04-15", "Percentage", 30, to_date="2026-04-30")

		ads = _active_schedule(asset.name)
		apr = next(r for r in ads.depreciation_schedule if getdate(r.schedule_date) == getdate("2026-04-30"))
		self.assertAlmostEqual(flt(apr.depreciation_amount), flt(standard * 0.3))

	def test_mode_b_spreads_shortfall(self):
		_ensure_company_handling("_Test Company", HANDLING_REDISTRIBUTE)
		asset = _make_sl_asset()
		ads_before = _active_schedule(asset.name)
		end_before = getdate(ads_before.depreciation_schedule[-1].schedule_date)
		count_before = len(ads_before.depreciation_schedule)

		_submit_usage(asset, "2026-01-01", "Percentage", 30, to_date="2026-01-31")

		ads = _active_schedule(asset.name)
		self.assertEqual(len(ads.depreciation_schedule), count_before)
		self.assertEqual(getdate(ads.depreciation_schedule[-1].schedule_date), end_before)
		jan = flt(ads.depreciation_schedule[0].depreciation_amount)
		feb = flt(ads.depreciation_schedule[1].depreciation_amount)
		self.assertLess(jan, feb)
		asset.reload()
		remaining = flt(asset.finance_books[0].value_after_depreciation) - flt(
			asset.finance_books[0].expected_value_after_useful_life
		)
		self.assertAlmostEqual(sum(_unposted_amounts(ads)), remaining, places=2)

	def test_mode_b_all_zero_errors(self):
		_ensure_company_handling("_Test Company", HANDLING_REDISTRIBUTE)
		asset = _make_sl_asset()
		with self.assertRaises(frappe.ValidationError):
			_submit_usage(asset, "2026-01-01", "No Depreciation", to_date=None)

	def test_posted_rows_immutable(self):
		_ensure_company_handling("_Test Company", HANDLING_EXTEND)
		asset = _make_sl_asset()
		ads = _active_schedule(asset.name)
		_post_first_n(ads.name, 2)
		ads = _active_schedule(asset.name)
		posted = [
			(getdate(r.schedule_date), flt(r.depreciation_amount), r.journal_entry)
			for r in ads.depreciation_schedule
			if r.journal_entry
		]
		self.assertEqual(len(posted), 2)

		_submit_usage(asset, "2026-01-01", "Percentage", 30, to_date="2026-06-30")

		ads = _active_schedule(asset.name)
		posted_after = [
			(getdate(r.schedule_date), flt(r.depreciation_amount), r.journal_entry)
			for r in ads.depreciation_schedule
			if r.journal_entry
		]
		self.assertEqual(posted, posted_after)

	def test_manual_blocked(self):
		_ensure_company_handling("_Test Company", HANDLING_EXTEND)
		asset = _make_sl_asset(depreciation_method="Manual")
		with self.assertRaises(frappe.ValidationError):
			_submit_usage(asset, "2026-02-01", "Percentage", 30, to_date="2026-02-28")

	def test_open_ended_zero_no_infinite_rows(self):
		_ensure_company_handling("_Test Company", HANDLING_EXTEND)
		asset = _make_sl_asset()
		_submit_usage(asset, "2026-01-01", "No Depreciation", to_date=None)
		ads = _active_schedule(asset.name)
		self.assertLess(len(ads.depreciation_schedule), 50)
		self.assertEqual(sum(1 for a in _unposted_amounts(ads) if a > 0), 0)

	def test_cancel_usage_replans(self):
		_ensure_company_handling("_Test Company", HANDLING_EXTEND)
		asset = _make_sl_asset()
		ads0 = _active_schedule(asset.name)
		standard = flt(ads0.depreciation_schedule[1].depreciation_amount)
		usage = _submit_usage(asset, "2026-02-01", "Percentage", 30, to_date="2026-02-28")
		usage.cancel()
		ads = _active_schedule(asset.name)
		self.assertAlmostEqual(flt(ads.depreciation_schedule[1].depreciation_amount), standard)

	def test_daily_prorata_mid_period(self):
		_ensure_company_handling("_Test Company", HANDLING_EXTEND)
		asset = _make_sl_asset(daily_prorata_based=1)
		ads = _active_schedule(asset.name)
		apr = next(r for r in ads.depreciation_schedule if getdate(r.schedule_date) == getdate("2026-04-30"))
		standard = flt(apr.depreciation_amount)

		_submit_usage(asset, "2026-04-11", "Percentage", 30, to_date="2026-04-30")

		ads = _active_schedule(asset.name)
		apr = next(r for r in ads.depreciation_schedule if getdate(r.schedule_date) == getdate("2026-04-30"))
		expected_factor = (10 * 1.0 + 20 * 0.3) / 30.0
		self.assertAlmostEqual(flt(apr.depreciation_amount), flt(standard * expected_factor), places=2)
