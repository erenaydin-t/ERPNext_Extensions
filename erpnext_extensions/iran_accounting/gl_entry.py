# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

from erpnext_extensions.iran_accounting.rounding import (
	get_company_currency,
	is_irr_company,
	round_gl_entry_amounts,
)


def validate_gl_entry(doc, method=None):
	if not doc.company or not is_irr_company(doc.company):
		return
	round_gl_entry_amounts(doc)


def before_insert_gl_entry(doc, method=None):
	validate_gl_entry(doc, method)
