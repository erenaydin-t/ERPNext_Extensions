# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""v4.6.3 — Account Levels grid respects selected presentation level under account filters."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, getdate, today

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_account_explorer,
	require_site,
)

MARKER = "AE-HIER-V463"
GROUP_CODE = "77"
GL_A_CODE = "7701"
GL_B_CODE = "7702"
SL_A_CODE = "770101"
SL_B_CODE = "770201"
AMOUNT_A = 400.0
AMOUNT_B = 250.0


def _company_currency(company: str) -> str:
	return frappe.get_cached_value("Company", company, "default_currency") or "INR"


def _company_root(company: str, root_type: str = "Asset") -> str:
	name = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": root_type, "parent_account": ("in", ["", None])},
		"name",
		order_by="lft",
	)
	if not name:
		name = frappe.db.get_value(
			"Account",
			{"company": company, "is_group": 1, "root_type": root_type},
			"name",
			order_by="lft",
		)
	if not name:
		frappe.throw(f"No {root_type} root for {company}")
	return name


def _ensure_account(
	*,
	company: str,
	code: str,
	title: str,
	is_group: int,
	parent: str,
	root_type: str = "Asset",
) -> str:
	existing = frappe.db.get_value("Account", {"company": company, "account_number": code}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": title,
			"account_number": code,
			"company": company,
			"parent_account": parent,
			"is_group": is_group,
			"root_type": root_type,
			"account_currency": _company_currency(company),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _cancel_old_jes(company: str) -> None:
	for name in frappe.get_all(
		"Journal Entry",
		filters={"company": company, "user_remark": ("like", f"{MARKER}%"), "docstatus": 1},
		pluck="name",
	):
		doc = frappe.get_doc("Journal Entry", name)
		doc.flags.ignore_permissions = True
		doc.cancel()


def _offset_expense(company: str) -> str:
	name = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 0, "root_type": "Expense", "disabled": 0},
		"name",
		order_by="name",
	)
	if not name:
		frappe.throw("Need an expense leaf for JE offset")
	return name


def _cost_center(company: str) -> str:
	name = frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 0}, "name", order_by="name"
	)
	if not name:
		frappe.throw("Need a cost center")
	return name


def ensure_hierarchy_fixture(company: str) -> dict:
	"""Create Group 77 → GL 7701/7702 → SL leaves with known activity."""
	enable_account_explorer()
	fy = current_fiscal_year(company)
	if not fy:
		frappe.throw("No fiscal year")
	fiscal_year, from_date, to_date = fy
	posting_date = getdate(to_date) if getdate(to_date) <= getdate(today()) else getdate(from_date)

	root = _company_root(company, "Asset")
	group = _ensure_account(
		company=company,
		code=GROUP_CODE,
		title=f"{MARKER} Current Assets",
		is_group=1,
		parent=root,
	)
	gl_a = _ensure_account(
		company=company, code=GL_A_CODE, title=f"{MARKER} Cash GL", is_group=1, parent=group
	)
	gl_b = _ensure_account(
		company=company, code=GL_B_CODE, title=f"{MARKER} Bank GL", is_group=1, parent=group
	)
	sl_a = _ensure_account(
		company=company, code=SL_A_CODE, title=f"{MARKER} Cash SL", is_group=0, parent=gl_a
	)
	sl_b = _ensure_account(
		company=company, code=SL_B_CODE, title=f"{MARKER} Bank SL", is_group=0, parent=gl_b
	)

	_cancel_old_jes(company)
	expense = _offset_expense(company)
	cc = _cost_center(company)

	def _je(remark: str, debit_account: str, amount: float) -> str:
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.company = company
		je.posting_date = posting_date
		je.user_remark = remark
		je.append(
			"accounts",
			{"account": debit_account, "debit_in_account_currency": amount, "cost_center": cc},
		)
		je.append(
			"accounts",
			{"account": expense, "credit_in_account_currency": amount, "cost_center": cc},
		)
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		return je.name

	_je(f"{MARKER} A", sl_a, AMOUNT_A)
	_je(f"{MARKER} B", sl_b, AMOUNT_B)
	frappe.db.commit()

	return {
		"company": company,
		"fiscal_year": fiscal_year,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"group_account": group,
		"gl_a_account": gl_a,
		"gl_b_account": gl_b,
		"sl_a_account": sl_a,
		"sl_b_account": sl_b,
		"group_code": GROUP_CODE,
		"gl_codes": [GL_A_CODE, GL_B_CODE],
		"sl_codes": [SL_A_CODE, SL_B_CODE],
		"expected_scoped_period_debit": AMOUNT_A + AMOUNT_B,
	}


def _summary(company, fiscal_year, from_date, to_date, *, level: int, account: str) -> dict:
	payload = build_payload(
		company,
		fiscal_year,
		from_date,
		to_date,
		analysis={
			"view_axis": "account_level",
			"level_sequence": level,
			"account_scope": {
				"mode": "account",
				"selected_account": account,
				"tree_root_account": account,
				"is_virtual_group": 0,
			},
			"page": 1,
			"page_size": 50,
		},
		document={"hide_zero_rows": 0},
	)
	return api.get_account_summary(payload)


class TestHierarchyFilterPresentation(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.company = require_site(cls)
		frappe.set_user("Administrator")
		cls.fx = ensure_hierarchy_fixture(cls.company)

	def test_group_filter_returns_only_group_level_row(self):
		result = _summary(
			self.fx["company"],
			self.fx["fiscal_year"],
			self.fx["from_date"],
			self.fx["to_date"],
			level=1,
			account=self.fx["group_account"],
		)
		codes = [row.get("display_code") for row in result["rows"]]
		self.assertEqual(codes, [GROUP_CODE], codes)
		self.assertEqual(result["pagination"]["total_rows"], 1)
		for child in self.fx["gl_codes"] + self.fx["sl_codes"]:
			self.assertNotIn(child, codes)

	def test_gl_filter_returns_only_gl_rows(self):
		result = _summary(
			self.fx["company"],
			self.fx["fiscal_year"],
			self.fx["from_date"],
			self.fx["to_date"],
			level=2,
			account=self.fx["group_account"],
		)
		# Ignore virtual unclassified (parent group code shorter than GL length).
		codes = sorted(
			row.get("display_code")
			for row in result["rows"]
			if not row.get("is_virtual_group")
			and not str(row.get("display_code") or "").startswith("__")
		)
		self.assertEqual(codes, sorted(self.fx["gl_codes"]), codes)
		self.assertNotIn(GROUP_CODE, codes)
		for child in self.fx["sl_codes"]:
			self.assertNotIn(child, codes)

	def test_children_excluded_from_group_grid_but_available_via_deeper_level(self):
		"""Filter stays at Group (one row); advancing presentation reveals children (Analyze→navigate)."""
		group_view = _summary(
			self.fx["company"],
			self.fx["fiscal_year"],
			self.fx["from_date"],
			self.fx["to_date"],
			level=1,
			account=self.fx["group_account"],
		)
		self.assertEqual([r["display_code"] for r in group_view["rows"]], [GROUP_CODE])

		gl_view = _summary(
			self.fx["company"],
			self.fx["fiscal_year"],
			self.fx["from_date"],
			self.fx["to_date"],
			level=2,
			account=self.fx["group_account"],
		)
		gl_codes = {r["display_code"] for r in gl_view["rows"]}
		self.assertTrue(set(self.fx["gl_codes"]).issubset(gl_codes), gl_codes)
		self.assertNotIn(GROUP_CODE, gl_codes)

	def test_totals_equal_filtered_scope(self):
		for level in (1, 2, 3):
			result = _summary(
				self.fx["company"],
				self.fx["fiscal_year"],
				self.fx["from_date"],
				self.fx["to_date"],
				level=level,
				account=self.fx["group_account"],
			)
			self.assertAlmostEqual(
				flt(result["totals"]["period_debit"]),
				self.fx["expected_scoped_period_debit"],
				places=2,
				msg=f"level={level}",
			)

	def test_api_rows_respect_selected_hierarchy_level(self):
		lengths = {1: 2, 2: 4, 3: 6}
		for level, code_len in lengths.items():
			result = _summary(
				self.fx["company"],
				self.fx["fiscal_year"],
				self.fx["from_date"],
				self.fx["to_date"],
				level=level,
				account=self.fx["group_account"],
			)
			for row in result["rows"]:
				code = row.get("display_code") or ""
				if code.startswith("__"):
					continue
				self.assertEqual(
					len(code),
					code_len,
					f"level={level} row={code} expected length {code_len}",
				)
				self.assertEqual(int(row.get("level_sequence")), level)
