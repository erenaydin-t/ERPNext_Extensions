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
def get_account_scope_preview(payload=None):
	from erpnext_extensions.iran_accounting.account_explorer.api import get_account_scope_preview as _preview

	return _preview(payload)
