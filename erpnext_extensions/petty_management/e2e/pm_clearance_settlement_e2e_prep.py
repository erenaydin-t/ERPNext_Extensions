"""E2E prep for PM Clearance settlement line UX tests.

Creates:
- Employee + PM Holder
- Funded PM Request (for allocation line)
- Submitted Purchase Invoice (outstanding)
- Submitted Purchase Order (for supplier advance)
- Ensures Supplier has a unique supplier_name for search-by-name.
"""

from __future__ import annotations

import frappe

from erpnext_extensions.petty_management.tests import test_pm_clearance as tpm


@frappe.whitelist()
def prepare() -> dict:
	frappe.set_user("Administrator")
	tpm._ensure_company_context()
	if not tpm.COMPANY:
		frappe.throw("No Company on site")

	# Employee + holder
	emp = tpm._make_employee()
	holder = tpm._make_holder(emp)
	petty_cash_account = frappe.db.get_value("PM Holder", holder, "petty_cash_account")
	currency = frappe.db.get_value("Company", tpm.COMPANY, "default_currency") or "IRR"

	# Ensure supplier has an explicit, searchable supplier_name (Persian-friendly)
	suppliers = frappe.get_all("Supplier", fields=["name", "supplier_name"], limit=1)
	if not suppliers:
		frappe.throw("No Supplier exists on site")
	supplier = suppliers[0].name
	unique_suffix = frappe.generate_hash(length=6)
	supplier_name = f"PM Supplier Search {unique_suffix}"
	frappe.db.set_value("Supplier", supplier, "supplier_name", supplier_name, update_modified=False)

	# Funded PM Request for allocations
	pm_request, _pe = tpm._fund_pm_request(emp, 100_000.0)

	# Purchase Invoice (submitted; outstanding > 0)
	pi = tpm._make_pi_outstanding(10_000)
	pi.supplier = supplier
	pi.insert(ignore_permissions=True)
	pi.submit()

	# Purchase Order (submitted)
	po = tpm._make_purchase_order_for_company(qty=2, rate=5_000)
	# Ensure supplier matches PI supplier for consistent search
	if po.supplier != supplier:
		frappe.db.set_value("Purchase Order", po.name, "supplier", supplier, update_modified=False)
		po.reload()

	# Supplier advance account must be a proper Payable (party-capable) ledger account.
	# A previous fallback that grabbed an arbitrary leaf account produced an account with
	# a blank account_type, which made the settlement JE unsubmittable ("Against Journal
	# Entry ... is already adjusted against some other voucher"). Always use the shared
	# helper so we get a valid Payable advance account.
	advance_account = tpm._supplier_advance_test_account()

	frappe.db.commit()
	return {
		"company": tpm.COMPANY,
		"currency": currency,
		"employee": emp,
		"holder": holder,
		"petty_cash_account": petty_cash_account,
		"pm_request": pm_request,
		"supplier": supplier,
		"supplier_name": supplier_name,
		"purchase_invoice": pi.name,
		"purchase_order": po.name,
		"supplier_advance_account": advance_account,
	}

