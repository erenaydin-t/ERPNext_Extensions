# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint
from erpnext.accounts.party import get_party_account

from erpnext_extensions.consignment_stock.constants import ALLOWED_PARTY_TYPES


def validate_consignment_party(party_type: str | None, party: str | None, company: str) -> str:
	"""Validate party and return resolved party account."""
	if not party_type or not party:
		frappe.throw(_("Consignment Party Type and Party are required."))

	if party_type not in ALLOWED_PARTY_TYPES:
		frappe.throw(
			_("Consignment Party Type must be one of {0}.").format(", ".join(ALLOWED_PARTY_TYPES))
		)

	if not frappe.db.exists("Party Type", party_type):
		frappe.throw(_("Party Type {0} does not exist.").format(party_type))

	account_type = frappe.get_cached_value("Party Type", party_type, "account_type")
	if account_type not in ("Payable", "Receivable"):
		frappe.throw(
			_("Party Type {0} must have account type Payable or Receivable.").format(party_type)
		)

	if not frappe.db.exists(party_type, party):
		frappe.throw(_("{0} {1} does not exist.").format(party_type, party))

	return resolve_party_account(party_type, party, company)


def resolve_party_account(party_type: str, party: str, company: str) -> str:
	account = get_party_account(party_type, party, company)
	if not account:
		frappe.throw(
			_("No {0} account found for {1} {2} in company {3}.").format(
				party_type, party_type, party, company
			)
		)

	meta = frappe.db.get_value(
		"Account",
		account,
		["company", "is_group", "disabled", "account_type"],
		as_dict=True,
	)
	if not meta:
		frappe.throw(_("Party account {0} does not exist.").format(account))
	if meta.company != company:
		frappe.throw(_("Party account {0} does not belong to company {1}.").format(account, company))
	if cint(meta.is_group):
		frappe.throw(_("Party account {0} cannot be a group.").format(account))
	if cint(meta.disabled):
		frappe.throw(_("Party account {0} is disabled.").format(account))

	expected = frappe.get_cached_value("Party Type", party_type, "account_type")
	if meta.account_type != expected:
		frappe.throw(
			_("Party account {0} type {1} does not match Party Type account type {2}.").format(
				account, meta.account_type, expected
			)
		)
	return account
