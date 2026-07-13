# Copyright (c) 2026, Farbod Siyahpoosh and contributors

"""Account Explorer whitelisted API entry points."""

from __future__ import annotations

import frappe


@frappe.whitelist()
def get_account_explorer_metadata():
	from erpnext_extensions.iran_accounting.account_explorer.api import get_metadata

	return get_metadata()


@frappe.whitelist()
def validate_document_scope(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import validate_document_scope as _validate

	return _validate(payload)


@frappe.whitelist()
def get_account_summary(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_account_summary as _summary

	return _summary(payload)


@frappe.whitelist()
def get_party_summary(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_party_summary as _summary

	return _summary(payload)


@frappe.whitelist()
def get_unified_party_summary(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_unified_party_summary as _summary

	return _summary(payload)


@frappe.whitelist()
def get_unified_party_member_breakdown(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import (
		get_unified_party_member_breakdown as _breakdown,
	)

	return _breakdown(payload)


@frappe.whitelist()
def get_unified_party_suggestions(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_unified_party_suggestions as _suggest

	return _suggest(payload)


@frappe.whitelist()
def get_currency_summary(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_currency_summary as _summary

	return _summary(payload)


@frappe.whitelist()
def get_dimension_summary(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_dimension_summary as _summary

	return _summary(payload)


@frappe.whitelist()
def get_voucher_summary(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_voucher_summary as _summary

	return _summary(payload)


@frappe.whitelist()
def get_grouped_gl_entries(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_grouped_gl_entries as _entries

	return _entries(payload)


@frappe.whitelist()
def get_voucher_navigation_target(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_voucher_navigation_target as _target

	return _target(payload)


@frappe.whitelist()
def get_account_scope_preview(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_account_scope_preview as _preview

	return _preview(payload)
