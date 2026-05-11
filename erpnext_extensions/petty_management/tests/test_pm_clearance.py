# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Tests for PM Clearance settlement + PM Request allocation (real ``build_clearance_je_accounts`` / JE insert).

Cheque-management style: lives under ``petty_management/tests/``. Uses ``_Test Company`` when present;
otherwise the first Company on the site and its bank/supplier/item links.

**Import note:** PM Clearance helpers are imported **inside** test methods or via ``_pm()`` so this module
does not pull ERPNext accounting code during Frappe test discovery (avoids fiscal-year bootstrap errors).

Run from bench root (recommended: **module only**; do not combine ``--lightmode`` with ``--app`` — lightmode
prioritizes ``--app`` and loads every ``test_*.py`` in the app)::

    bench --site development.localhost run-tests \\
        --module erpnext_extensions.petty_management.tests.test_pm_clearance \\
        --skip-before-tests

Shim path (same tests via star-import)::

    bench --site development.localhost run-tests \\
        --module erpnext_extensions.petty_management.doctype.pm_clearance.test_pm_clearance \\
        --skip-before-tests

**Site requirements:** valid fiscal years for the chosen company; Payment Entry / Purchase Invoice helpers
may raise ``NameError`` (fiscal overlap) if the site has overlapping ``Fiscal Year`` rows (e.g. Gregorian vs Jalali).
Lightmode (single-module import, no full type-validator walk)::

    bench --site development.localhost run-tests \\
        --module erpnext_extensions.petty_management.tests.test_pm_clearance \\
        --lightmode

If discovery fails with overlapping fiscal year / ``before_tests`` errors, add ``--skip-before-tests``.
"""

from __future__ import annotations

import unittest

import frappe
from frappe.exceptions import ValidationError
from frappe.utils import flt, today

# Resolved in ``_ensure_company_context`` (setUpClass).
COMPANY = ""
PETTY_ACCOUNT = ""
BANK_ACCOUNT = ""


def _pm():
	"""Lazy import of ``pm_clearance`` module (avoid import-time side effects)."""
	from erpnext_extensions.petty_management.doctype.pm_clearance import pm_clearance as mod

	return mod


def _ensure_company_context() -> None:
	"""Set module-level COMPANY / PETTY_ACCOUNT / BANK_ACCOUNT (idempotent)."""
	global COMPANY, PETTY_ACCOUNT, BANK_ACCOUNT
	if COMPANY:
		return
	if frappe.db.exists("Company", "_Test Company"):
		COMPANY = "_Test Company"
	else:
		names = frappe.get_all("Company", pluck="name", limit=1)
		if not names:
			return
		COMPANY = names[0]
	abbr = frappe.db.get_value("Company", COMPANY, "abbr")
	PETTY_ACCOUNT = f"Petty Cash PM Test - {abbr}"
	BANK_ACCOUNT = frappe.db.get_value("Company", COMPANY, "default_bank_account")
	if not BANK_ACCOUNT:
		row = frappe.db.sql(
			"""
			select name from `tabAccount`
			where company=%s and ifnull(is_group,0)=0 and account_type in ('Bank', 'Cash')
			limit 1
			""",
			COMPANY,
		)
		BANK_ACCOUNT = row[0][0] if row else ""


def _petty_parent_account() -> str:
	abbr = frappe.db.get_value("Company", COMPANY, "abbr")
	cand = f"Current Assets - {abbr}"
	if frappe.db.exists("Account", cand):
		return cand
	return (
		f"Application of Funds (Assets) - {abbr}"
		if frappe.db.exists("Account", f"Application of Funds (Assets) - {abbr}")
		else cand
	)


def _ensure_petty_account() -> str:
	if frappe.db.exists("Account", PETTY_ACCOUNT):
		return PETTY_ACCOUNT
	from erpnext.accounts.doctype.account.test_account import create_account

	parent = _petty_parent_account()
	create_account(
		account_name="Petty Cash PM Test",
		parent_account=parent,
		company=COMPANY,
		account_type="Cash",
	)
	return PETTY_ACCOUNT


def _workflow_state_for(document_type: str, state_title: str) -> str | None:
	wf_name = frappe.db.get_value(
		"Workflow",
		{"document_type": document_type, "is_active": 1},
		"name",
	)
	if not wf_name:
		return None
	wf = frappe.get_doc("Workflow", wf_name)
	for s in wf.states:
		title = frappe.db.get_value("Workflow State", s.state, "workflow_state_name")
		if title == state_title:
			return s.state
	return None


def _make_employee() -> str:
	from erpnext.setup.doctype.employee.test_employee import make_employee

	email = frappe.generate_hash(length=8) + "_pm_clearance_test@example.com"
	return make_employee(email, company=COMPANY)


def _make_holder(employee: str) -> str:
	petty = _ensure_petty_account()
	if frappe.db.exists("PM Holder", {"employee": employee, "company": COMPANY}):
		return frappe.db.get_value("PM Holder", {"employee": employee, "company": COMPANY}, "name")
	h = frappe.new_doc("PM Holder")
	h.employee = employee
	h.company = COMPANY
	h.petty_cash_account = petty
	h.insert()
	return h.name


def _fund_pm_request(employee: str, amount: float) -> tuple[str, str]:
	from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_payment_entry

	petty = _ensure_petty_account()
	req = frappe.new_doc("PM Request")
	req.company = COMPANY
	req.employee = employee
	req.transaction_date = today()
	req.append("details", {"advance_amount": amount})
	req.insert()
	req.submit()

	pe = create_payment_entry(
		company=COMPANY,
		party_type="Employee",
		party=employee,
		paid_from=BANK_ACCOUNT,
		paid_to=petty,
		paid_amount=amount,
		save=True,
		submit=True,
	)
	req.reload()
	req.db_set("payment_entry", pe.name, update_modified=False)
	req.db_set("payment_status", "Paid", update_modified=False)
	req.db_set("status", "Paid", update_modified=False)
	return req.name, pe.name


def _make_pi_outstanding(amount: float):
	from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice

	supplier = "_Test Supplier" if frappe.db.exists("Supplier", "_Test Supplier") else None
	if not supplier:
		suppliers = frappe.get_all("Supplier", pluck="name", limit=1)
		if not suppliers:
			raise unittest.SkipTest("No Supplier on site; cannot create Purchase Invoice.")
		supplier = suppliers[0]
	item_code = "_Test Item" if frappe.db.exists("Item", "_Test Item") else None
	if not item_code:
		items = frappe.get_all("Item", filters={"disabled": 0}, pluck="name", limit=1)
		if not items:
			raise unittest.SkipTest("No Item on site; cannot create Purchase Invoice.")
		item_code = items[0]

	return make_purchase_invoice(
		company=COMPANY,
		supplier=supplier,
		item_code=item_code,
		qty=1,
		rate=amount,
		do_not_submit=True,
	)


def _insert_legacy_allocation_row(parent: str, total: float) -> None:
	"""Same shape as migration patch (submitted-parent path)."""
	name = frappe.generate_hash(length=10)
	user = "Administrator"
	frappe.db.sql(
		"""
		INSERT INTO `tabPM Clearance Request Allocation`
		(`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`,
		 `parent`, `parenttype`, `parentfield`, `idx`,
		 `is_legacy_row`, `allocated_amount`, `request_amount`, `paid_amount`,
		 `previously_allocated_amount`, `available_amount`, `pm_request`)
		VALUES
		(%s, NOW(), NOW(), %s, %s, 0,
		 %s, 'PM Clearance', 'request_allocations', 1,
		 1, %s, 0, 0, 0, 0, NULL)
		""",
		(name, user, user, parent, total),
	)


def _default_warehouse_for_company() -> str | None:
	w = frappe.db.get_value("Company", COMPANY, "default_warehouse")
	if w and frappe.db.exists("Warehouse", w):
		return w
	row = frappe.db.sql(
		"""
		select name from `tabWarehouse`
		where company=%s and ifnull(disabled,0)=0
		limit 1
		""",
		COMPANY,
	)
	return row[0][0] if row else None


def _supplier_advance_test_account() -> str:
	acc = frappe.db.get_value("Company", COMPANY, "default_advance_paid_account")
	if acc:
		return acc
	from erpnext.accounts.doctype.account.test_account import create_account

	abbr = frappe.db.get_value("Company", COMPANY, "abbr")
	for label in ("Creditors", "Accounts Payable"):
		parent = f"{label} - {abbr}"
		if frappe.db.exists("Account", parent):
			return create_account(
				account_name="PM Test Supplier Advance",
				parent_account=parent,
				company=COMPANY,
				account_type="Payable",
			)
	raise unittest.SkipTest("No default_advance_paid_account and no Creditors parent for test advance account.")


def _make_purchase_order_for_company(qty: float = 5, rate: float = 1000):
	from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order

	wh = _default_warehouse_for_company()
	if not wh:
		raise unittest.SkipTest("No warehouse for Purchase Order in this company.")

	supplier = "_Test Supplier" if frappe.db.exists("Supplier", "_Test Supplier") else None
	if not supplier:
		suppliers = frappe.get_all("Supplier", pluck="name", limit=1)
		if not suppliers:
			raise unittest.SkipTest("No Supplier on site.")
		supplier = suppliers[0]
	item_code = "_Test Item" if frappe.db.exists("Item", "_Test Item") else None
	if not item_code:
		items = frappe.get_all("Item", filters={"disabled": 0}, pluck="name", limit=1)
		if not items:
			raise unittest.SkipTest("No Item on site.")
		item_code = items[0]

	return create_purchase_order(
		company=COMPANY,
		supplier=supplier,
		item=item_code,
		warehouse=wh,
		qty=qty,
		rate=rate,
	)


class TestPMClearanceAllocation(unittest.TestCase):
	"""Allocation validation, reservation, preview, settlement, legacy guards."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		_ensure_company_context()
		if not COMPANY:
			raise unittest.SkipTest("No Company on site.")
		if not BANK_ACCOUNT:
			raise unittest.SkipTest(f"No bank/cash account resolved for company {COMPANY!r}.")
		_ensure_petty_account()

	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup_names: list[tuple[str, str]] = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for doctype, name in reversed(self._cleanup_names):
			try:
				if doctype == "PM Request" and frappe.db.exists("PM Request", name):
					pe = frappe.db.get_value("PM Request", name, "payment_entry")
					if pe and frappe.db.exists("Payment Entry", pe):
						pe_doc = frappe.get_doc("Payment Entry", pe)
						if pe_doc.docstatus == 1:
							pe_doc.cancel()
						frappe.delete_doc("Payment Entry", pe, force=True, ignore_permissions=True)
				if doctype == "Purchase Order" and frappe.db.exists("Purchase Order", name):
					po_doc = frappe.get_doc("Purchase Order", name)
					if po_doc.docstatus == 1:
						po_doc.reload()
						po_doc.cancel()
					frappe.delete_doc("Purchase Order", name, force=True, ignore_permissions=True)
					continue
				doc = frappe.get_doc(doctype, name)
				if getattr(doc, "docstatus", 0) == 1:
					doc.reload()
					doc.cancel()
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			except Exception:
				pass
		frappe.db.commit()

	def _track(self, doctype: str, name: str) -> None:
		self._cleanup_names.append((doctype, name))

	def _base_clearance(self, employee: str, pi, pi_amount: float):
		cl = frappe.new_doc("PM Clearance")
		cl.company = COMPANY
		cl.employee = employee
		cl.transaction_date = today()
		cl.append(
			"details",
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": pi_amount,
			},
		)
		return cl

	def test_funding_makes_pm_request_available_for_allocation(self):
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 50_000.0)
		self._track("PM Request", req_name)

		mod = _pm()
		prev = mod.sum_prior_pm_request_allocations(req_name, "__nonexistent_clearance__")
		self.assertEqual(prev, 0.0)
		prev_all = mod.sum_prior_pm_request_allocations(req_name, None)
		self.assertEqual(prev_all, 0.0)

	def test_pm_request_allocation_context_stamps_paid_request_snapshot(self):
		mod = _pm()
		emp = _make_employee()
		self._track("Employee", emp)
		holder = _make_holder(emp)
		petty = frappe.db.get_value("PM Holder", holder, "petty_cash_account")
		req_name, _pe = _fund_pm_request(emp, 25_000.0)
		self._track("PM Request", req_name)

		ctx = mod.get_pm_request_allocation_context(
			req_name,
			company=COMPANY,
			employee=emp,
			holder=holder,
			petty_cash_account=petty,
		)
		self.assertEqual(ctx["pm_request"], req_name)
		self.assertEqual(flt(ctx["request_amount"]), 25_000)
		self.assertGreater(flt(ctx["paid_amount"]), 0)
		self.assertGreater(flt(ctx["available_amount"]), 0)
		self.assertEqual(ctx["employee"], emp)
		self.assertEqual(ctx["holder"], holder)
		self.assertEqual(ctx["petty_cash_account"], petty)
		self.assertEqual(ctx["company"], COMPANY)

		pi = _make_pi_outstanding(10_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 10_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 10_000})
		cl.insert()
		self._track("PM Clearance", cl.name)
		row = cl.request_allocations[0]
		self.assertEqual(flt(row.request_amount), 25_000)
		self.assertGreater(flt(row.paid_amount), 0)
		self.assertGreater(flt(row.available_amount), 0)

	def test_pm_request_query_exact_docname_uses_alias_safe_search(self):
		mod = _pm()
		emp = _make_employee()
		self._track("Employee", emp)
		holder = _make_holder(emp)
		petty = frappe.db.get_value("PM Holder", holder, "petty_cash_account")
		req_name, _pe = _fund_pm_request(emp, 12_000.0)
		self._track("PM Request", req_name)

		rows = mod.pm_request_query_for_pm_clearance(
			"PM Request",
			req_name,
			"name",
			0,
			20,
			{
				"company": COMPANY,
				"employee": emp,
				"holder": holder,
				"petty_cash_account": petty,
			},
		)
		self.assertIn(req_name, [r[0] for r in rows])

	def test_clearance_without_request_allocations_fails(self):
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		pi = _make_pi_outstanding(10_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 10_000)
		with self.assertRaises(ValidationError):
			cl.insert()

	def test_sum_mismatch_pi_vs_pm_request_fails(self):
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 50_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(10_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 10_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 9_999})
		with self.assertRaises(ValidationError) as ctx:
			cl.insert()
		self.assertIn("Total PM Request allocation", str(ctx.exception))

	def test_allocation_over_available_fails(self):
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 10_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(12_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 12_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 12_000})
		with self.assertRaises(ValidationError):
			cl.insert()

	def test_duplicate_pm_request_rows_fail(self):
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 100_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(20_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 20_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 10_000})
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 10_000})
		with self.assertRaises(ValidationError):
			cl.insert()

	def test_submitted_clearance_without_je_reserves_pm_request(self):
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 50_000.0)
		self._track("PM Request", req_name)

		pi1 = _make_pi_outstanding(30_000)
		pi1.insert()
		pi1.submit()
		self._track("Purchase Invoice", pi1.name)

		cl1 = self._base_clearance(emp, pi1, 30_000)
		cl1.append("request_allocations", {"pm_request": req_name, "allocated_amount": 30_000})
		cl1.insert()
		cl1.submit()
		self._track("PM Clearance", cl1.name)

		pi2 = _make_pi_outstanding(25_000)
		pi2.insert()
		pi2.submit()
		self._track("Purchase Invoice", pi2.name)

		cl2 = self._base_clearance(emp, pi2, 25_000)
		cl2.append("request_allocations", {"pm_request": req_name, "allocated_amount": 25_000})
		with self.assertRaises(ValidationError):
			cl2.insert()

	def test_preview_returns_pi_debit_and_petty_credit_without_creating_je(self):
		mod = _pm()
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 100_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(5_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 5_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 5_000})
		cl.insert()
		self._track("PM Clearance", cl.name)

		n_before = frappe.db.count("Journal Entry")

		out = mod.preview_pm_clearance_settlement(pm_clearance=cl.name)
		n_after = frappe.db.count("Journal Entry")
		self.assertEqual(n_before, n_after)

		accounts = out.get("accounts") or []
		self.assertGreaterEqual(len(accounts), 2)
		debit_lines = [a for a in accounts if flt(a.get("debit_in_account_currency")) > 0]
		credit_lines = [a for a in accounts if flt(a.get("credit_in_account_currency")) > 0]
		self.assertEqual(len(debit_lines), 1)
		self.assertEqual(len(credit_lines), 1)
		self.assertEqual(debit_lines[0].get("account"), pi.credit_to)
		self.assertEqual(debit_lines[0].get("reference_type"), "Purchase Invoice")
		self.assertEqual(debit_lines[0].get("reference_name"), pi.name)
		petty = _ensure_petty_account()
		self.assertEqual(credit_lines[0].get("account"), petty)
		self.assertEqual(flt(credit_lines[0].get("credit_in_account_currency")), 5_000)

	def test_preview_unsaved_doc_validates_allocations_without_mutating_source(self):
		mod = _pm()
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 50_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(6_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 6_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 6_000})
		self.assertEqual(flt(cl.request_allocations[0].paid_amount), 0)

		out = mod.preview_pm_clearance_settlement(doc=frappe.as_json(cl.as_dict()))
		accounts = out.get("accounts") or []
		self.assertEqual(len([a for a in accounts if flt(a.get("debit_in_account_currency")) > 0]), 1)
		self.assertEqual(len([a for a in accounts if flt(a.get("credit_in_account_currency")) > 0]), 1)
		self.assertEqual(flt(cl.request_allocations[0].paid_amount), 0)

	def test_preview_saved_doc_does_not_create_je_or_extra_allocation_rows(self):
		mod = _pm()
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 50_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(4_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 4_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 4_000})
		cl.insert()
		self._track("PM Clearance", cl.name)
		before_rows = len(cl.request_allocations)
		before_snapshot = (
			flt(cl.request_allocations[0].request_amount),
			flt(cl.request_allocations[0].paid_amount),
			flt(cl.request_allocations[0].previously_allocated_amount),
			flt(cl.request_allocations[0].available_amount),
		)
		n_before = frappe.db.count("Journal Entry")

		mod.preview_pm_clearance_settlement(pm_clearance=cl.name)

		cl.reload()
		self.assertEqual(frappe.db.count("Journal Entry"), n_before)
		self.assertEqual(len(cl.request_allocations), before_rows)
		after_snapshot = (
			flt(cl.request_allocations[0].request_amount),
			flt(cl.request_allocations[0].paid_amount),
			flt(cl.request_allocations[0].previously_allocated_amount),
			flt(cl.request_allocations[0].available_amount),
		)
		self.assertEqual(after_snapshot, before_snapshot)

	def test_allocation_snapshot_validation_is_idempotent(self):
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 50_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(3_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 3_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 3_000})
		cl.insert()
		self._track("PM Clearance", cl.name)
		cl.reload()
		before_rows = len(cl.request_allocations)
		before_snapshot = (
			flt(cl.request_allocations[0].request_amount),
			flt(cl.request_allocations[0].paid_amount),
			flt(cl.request_allocations[0].previously_allocated_amount),
			flt(cl.request_allocations[0].available_amount),
		)

		cl.validate()
		cl.validate()

		self.assertEqual(len(cl.request_allocations), before_rows)
		after_snapshot = (
			flt(cl.request_allocations[0].request_amount),
			flt(cl.request_allocations[0].paid_amount),
			flt(cl.request_allocations[0].previously_allocated_amount),
			flt(cl.request_allocations[0].available_amount),
		)
		self.assertEqual(after_snapshot, before_snapshot)

	def test_preview_uses_same_builder_as_insert_path(self):
		mod = _pm()
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 20_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(7_500)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 7_500)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 7_500})
		cl.insert()
		self._track("PM Clearance", cl.name)

		cl.reload()
		direct = mod.build_clearance_je_accounts(cl)
		prev = mod.preview_pm_clearance_settlement(pm_clearance=cl.name)["accounts"]
		self.assertEqual(len(direct), len(prev))
		for a, b in zip(direct, prev, strict=True):
			self.assertEqual(a.get("account"), b.get("account"))
			self.assertEqual(flt(a.get("debit_in_account_currency")), flt(b.get("debit_in_account_currency")))
			self.assertEqual(flt(a.get("credit_in_account_currency")), flt(b.get("credit_in_account_currency")))

	def test_settle_creates_je_and_sets_settled(self):
		mod = _pm()
		approved = _workflow_state_for("PM Clearance", "Approved")
		if not approved:
			self.skipTest("Active PM Clearance workflow with Approved state not found.")

		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_a, _pe_a = _fund_pm_request(emp, 40_000.0)
		self._track("PM Request", req_a)
		req_b, _pe_b = _fund_pm_request(emp, 60_000.0)
		self._track("PM Request", req_b)

		pi = _make_pi_outstanding(45_440)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)
		pi.reload()
		outstanding_before = flt(pi.outstanding_amount)
		alloc_a = 40_000.0
		alloc_b = outstanding_before - alloc_a
		self.assertGreater(alloc_b, 0)

		cl = self._base_clearance(emp, pi, outstanding_before)
		cl.append("request_allocations", {"pm_request": req_a, "allocated_amount": alloc_a})
		cl.append("request_allocations", {"pm_request": req_b, "allocated_amount": alloc_b})
		cl.insert()
		cl.submit()
		self._track("PM Clearance", cl.name)

		frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)

		out = mod.settle_petty_cash(cl.name)
		je_name = out["journal_entry"]
		self._track("Journal Entry", je_name)

		cl.reload()
		self.assertEqual(cl.status, "Settled")
		self.assertEqual(cl.journal_entry, je_name)

		je = frappe.get_doc("Journal Entry", je_name)
		if je.docstatus == 0:
			je.submit()

		rows = je.get("accounts") or []
		dr = [r for r in rows if flt(r.debit_in_account_currency) > 0]
		cr = [r for r in rows if flt(r.credit_in_account_currency) > 0]
		self.assertEqual(len(dr), 1)
		self.assertEqual(len(cr), 1)
		self.assertEqual(dr[0].account, pi.credit_to)
		self.assertEqual(dr[0].reference_type, "Purchase Invoice")
		self.assertEqual(dr[0].reference_name, pi.name)
		self.assertEqual(cr[0].account, _ensure_petty_account())
		self.assertEqual(flt(cr[0].credit_in_account_currency), outstanding_before)

		pi.reload()
		self.assertLess(flt(pi.outstanding_amount), outstanding_before)

		meta_pi = frappe.get_meta("Purchase Invoice")
		if meta_pi.has_field("custom_pm_clearance"):
			self.assertEqual(
				frappe.db.get_value("Purchase Invoice", pi.name, "custom_pm_clearance"),
				cl.name,
			)
		if meta_pi.has_field("custom_pm_holder"):
			self.assertEqual(
				frappe.db.get_value("Purchase Invoice", pi.name, "custom_pm_holder"),
				cl.holder,
			)

	def test_pm_request_query_excludes_other_employee_requests(self):
		mod = _pm()
		emp_a = _make_employee()
		emp_b = _make_employee()
		self._track("Employee", emp_a)
		self._track("Employee", emp_b)
		_make_holder(emp_a)
		_make_holder(emp_b)
		req_b, _pe_b = _fund_pm_request(emp_b, 50_000.0)
		self._track("PM Request", req_b)

		holder_a = frappe.db.get_value("PM Holder", {"employee": emp_a, "company": COMPANY}, "name")
		petty_a = frappe.db.get_value("PM Holder", holder_a, "petty_cash_account")
		rows = mod.pm_request_query_for_pm_clearance(
			"PM Request",
			"",
			"name",
			0,
			20,
			{
				"employee": emp_a,
				"company": COMPANY,
				"holder": holder_a,
				"petty_cash_account": petty_a,
			},
		)
		names = [r[0] for r in rows]
		self.assertNotIn(req_b, names)

	def test_clearance_rejects_pm_request_from_other_employee(self):
		emp_a = _make_employee()
		emp_b = _make_employee()
		self._track("Employee", emp_a)
		self._track("Employee", emp_b)
		_make_holder(emp_a)
		_make_holder(emp_b)
		req_b, _pe_b = _fund_pm_request(emp_b, 20_000.0)
		self._track("PM Request", req_b)

		pi = _make_pi_outstanding(5_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp_a, pi, 5_000)
		cl.append("request_allocations", {"pm_request": req_b, "allocated_amount": 5_000})
		with self.assertRaises(ValidationError) as ctx:
			cl.insert()
		self.assertIn(req_b, str(ctx.exception))

	def test_petty_cash_account_matches_request_after_insert(self):
		mod = _pm()
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 30_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(8_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 8_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 8_000})
		cl.insert()
		self._track("PM Clearance", cl.name)

		cl.reload()
		req_doc = frappe.get_doc("PM Request", req_name)
		req_petty = mod.pm_request_petty_cash_from_holder(req_doc)
		clr_petty = mod.clearance_petty_cash_account(cl)
		self.assertTrue(clr_petty)
		self.assertEqual(req_petty, clr_petty)

	def test_settlement_totals_mismatch_with_pi_and_supplier_advance(self):
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 200_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(10_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)
		po = _make_purchase_order_for_company(qty=1, rate=5_000)
		self._track("Purchase Order", po.name)
		sa_acc = _supplier_advance_test_account()

		cl = frappe.new_doc("PM Clearance")
		cl.company = COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		cl.append(
			"details",
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": 10_000,
			},
		)
		cl.append(
			"details",
			{
				"settlement_type": "Supplier Advance",
				"purchase_order": po.name,
				"supplier_advance_account": sa_acc,
				"allocated_amount": 5_000,
			},
		)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 10_000})
		with self.assertRaises(ValidationError) as ctx:
			cl.insert()
		self.assertIn("Total PM Request allocation", str(ctx.exception))

	def test_preview_supplier_advance_debit_and_single_petty_credit(self):
		mod = _pm()
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 50_000.0)
		self._track("PM Request", req_name)

		po = _make_purchase_order_for_company(qty=2, rate=3_000)
		self._track("Purchase Order", po.name)
		sa_acc = _supplier_advance_test_account()
		alloc = 6_000.0

		cl = frappe.new_doc("PM Clearance")
		cl.company = COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		cl.append(
			"details",
			{
				"settlement_type": "Supplier Advance",
				"purchase_order": po.name,
				"supplier_advance_account": sa_acc,
				"allocated_amount": alloc,
			},
		)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": alloc})
		cl.insert()
		self._track("PM Clearance", cl.name)

		out = mod.preview_pm_clearance_settlement(pm_clearance=cl.name)
		accounts = out.get("accounts") or []
		debit_lines = [a for a in accounts if flt(a.get("debit_in_account_currency")) > 0]
		credit_lines = [a for a in accounts if flt(a.get("credit_in_account_currency")) > 0]
		self.assertEqual(len(debit_lines), 1)
		self.assertEqual(len(credit_lines), 1)
		self.assertEqual(debit_lines[0].get("account"), sa_acc)
		self.assertEqual(debit_lines[0].get("party_type"), "Supplier")
		self.assertEqual(debit_lines[0].get("party"), po.supplier)
		self.assertEqual(debit_lines[0].get("reference_type"), "Purchase Order")
		self.assertEqual(debit_lines[0].get("reference_name"), po.name)
		self.assertEqual(flt(credit_lines[0].get("credit_in_account_currency")), alloc)
		self.assertEqual(credit_lines[0].get("account"), _ensure_petty_account())

	def test_preview_mixed_pi_and_supplier_advance_matches_builder(self):
		mod = _pm()
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 200_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(12_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)
		po = _make_purchase_order_for_company(qty=1, rate=8_000)
		self._track("Purchase Order", po.name)
		sa_acc = _supplier_advance_test_account()
		pi_alloc = 12_000.0
		sa_alloc = 8_000.0
		total = pi_alloc + sa_alloc

		cl = frappe.new_doc("PM Clearance")
		cl.company = COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		cl.append(
			"details",
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": pi_alloc,
			},
		)
		cl.append(
			"details",
			{
				"settlement_type": "Supplier Advance",
				"purchase_order": po.name,
				"supplier_advance_account": sa_acc,
				"allocated_amount": sa_alloc,
			},
		)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": total})
		cl.insert()
		self._track("PM Clearance", cl.name)

		cl.reload()
		direct = mod.build_clearance_je_accounts(cl)
		prev = mod.preview_pm_clearance_settlement(pm_clearance=cl.name)["accounts"]
		self.assertEqual(len(direct), len(prev))
		for a, b in zip(direct, prev, strict=True):
			self.assertEqual(a.get("account"), b.get("account"))
			self.assertEqual(flt(a.get("debit_in_account_currency")), flt(b.get("debit_in_account_currency")))
			self.assertEqual(flt(a.get("credit_in_account_currency")), flt(b.get("credit_in_account_currency")))
			self.assertEqual(a.get("reference_type"), b.get("reference_type"))
			self.assertEqual(a.get("reference_name"), b.get("reference_name"))

		debit_lines = [a for a in prev if flt(a.get("debit_in_account_currency")) > 0]
		credit_lines = [a for a in prev if flt(a.get("credit_in_account_currency")) > 0]
		self.assertEqual(len(debit_lines), 2)
		self.assertEqual(len(credit_lines), 1)
		self.assertEqual(flt(credit_lines[0].get("credit_in_account_currency")), total)
		accts = {d.get("account") for d in debit_lines}
		self.assertIn(pi.credit_to, accts)
		self.assertIn(sa_acc, accts)

	def test_settle_supplier_advance_creates_je(self):
		mod = _pm()
		approved = _workflow_state_for("PM Clearance", "Approved")
		if not approved:
			self.skipTest("Active PM Clearance workflow with Approved state not found.")

		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 80_000.0)
		self._track("PM Request", req_name)

		po = _make_purchase_order_for_company(qty=1, rate=15_000)
		self._track("Purchase Order", po.name)
		sa_acc = _supplier_advance_test_account()
		alloc = 15_000.0

		cl = frappe.new_doc("PM Clearance")
		cl.company = COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		cl.append(
			"details",
			{
				"settlement_type": "Supplier Advance",
				"purchase_order": po.name,
				"supplier_advance_account": sa_acc,
				"allocated_amount": alloc,
			},
		)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": alloc})
		cl.insert()
		cl.submit()
		self._track("PM Clearance", cl.name)
		frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)

		out = mod.settle_petty_cash(cl.name)
		je_name = out["journal_entry"]
		self._track("Journal Entry", je_name)

		je = frappe.get_doc("Journal Entry", je_name)
		if je.docstatus == 0:
			je.submit()

		rows = je.get("accounts") or []
		dr = [r for r in rows if flt(r.debit_in_account_currency) > 0]
		cr = [r for r in rows if flt(r.credit_in_account_currency) > 0]
		self.assertEqual(len(dr), 1)
		self.assertEqual(len(cr), 1)
		self.assertEqual(dr[0].account, sa_acc)
		self.assertEqual(dr[0].party_type, "Supplier")
		self.assertEqual(dr[0].reference_type, "Purchase Order")
		self.assertEqual(dr[0].reference_name, po.name)
		self.assertEqual(flt(cr[0].credit_in_account_currency), alloc)

	def test_settle_mixed_pi_and_supplier_advance_one_credit(self):
		mod = _pm()
		approved = _workflow_state_for("PM Clearance", "Approved")
		if not approved:
			self.skipTest("Active PM Clearance workflow with Approved state not found.")

		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 500_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(20_440)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)
		po = _make_purchase_order_for_company(qty=1, rate=20_000)
		self._track("Purchase Order", po.name)
		sa_acc = _supplier_advance_test_account()
		pi_alloc = 20_440.0
		sa_alloc = 20_000.0
		total = pi_alloc + sa_alloc
		pi.reload()
		outstanding_before = flt(pi.outstanding_amount)

		cl = frappe.new_doc("PM Clearance")
		cl.company = COMPANY
		cl.employee = emp
		cl.transaction_date = today()
		cl.append(
			"details",
			{
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi.name,
				"allocated_amount": pi_alloc,
			},
		)
		cl.append(
			"details",
			{
				"settlement_type": "Supplier Advance",
				"purchase_order": po.name,
				"supplier_advance_account": sa_acc,
				"allocated_amount": sa_alloc,
			},
		)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": total})
		cl.insert()
		cl.submit()
		self._track("PM Clearance", cl.name)
		frappe.db.set_value("PM Clearance", cl.name, "workflow_state", approved, update_modified=False)

		out = mod.settle_petty_cash(cl.name)
		je_name = out["journal_entry"]
		self._track("Journal Entry", je_name)

		je = frappe.get_doc("Journal Entry", je_name)
		if je.docstatus == 0:
			je.submit()

		rows = je.get("accounts") or []
		dr = [r for r in rows if flt(r.debit_in_account_currency) > 0]
		cr = [r for r in rows if flt(r.credit_in_account_currency) > 0]
		self.assertEqual(len(dr), 2)
		self.assertEqual(len(cr), 1)
		self.assertEqual(flt(cr[0].credit_in_account_currency), total)

		pi.reload()
		self.assertLess(flt(pi.outstanding_amount), outstanding_before)

	def test_new_clearance_cannot_use_legacy_row_without_db_legacy(self):
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 50_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(1_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 1_000)
		cl.append(
			"request_allocations",
			{"is_legacy_row": 1, "allocated_amount": 1_000},
		)
		with self.assertRaises(ValidationError):
			cl.insert()

	def test_legacy_row_validate_passes_when_present_in_db_like_migration(self):
		"""Simulate migration: DB already has legacy child → clearance may keep legacy-only allocation."""
		emp = _make_employee()
		self._track("Employee", emp)
		_make_holder(emp)
		req_name, _pe = _fund_pm_request(emp, 50_000.0)
		self._track("PM Request", req_name)

		pi = _make_pi_outstanding(5_000)
		pi.insert()
		pi.submit()
		self._track("Purchase Invoice", pi.name)

		cl = self._base_clearance(emp, pi, 5_000)
		cl.append("request_allocations", {"pm_request": req_name, "allocated_amount": 5_000})
		cl.insert()
		self._track("PM Clearance", cl.name)
		total = flt(cl.total_expense_amount)

		frappe.db.sql(
			"delete from `tabPM Clearance Request Allocation` where parent=%s and parenttype='PM Clearance'",
			(cl.name,),
		)
		_insert_legacy_allocation_row(cl.name, total)
		frappe.db.commit()

		doc = frappe.get_doc("PM Clearance", cl.name)
		doc.validate()


if __name__ == "__main__":
	unittest.main()
