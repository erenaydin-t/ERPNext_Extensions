# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Seed Voucher GL Print UX option defaults (idempotent).

Frappe Check fields often appear as 0 in Singles immediately after migrate.
A versioned seed applies the intended ON/select/int defaults once per version
without repeatedly overwriting intentional user toggles after that.

The version marker is a real (hidden) DocType field so settings.save() cannot
silently wipe a phantom Singles-only key.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, cstr

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_renderer import LAYOUT_STANDARD

# Bump when new defaulted print settings are introduced.
SEED_VERSION = 3
VERSION_FIELD = "voucher_gl_print_defaults_version"

ON_DEFAULTS = {
	"show_print_gl": 1,
	"voucher_gl_auto_orientation": 1,
	"voucher_gl_show_logo": 1,
	"voucher_gl_show_amount_in_words": 1,
	"voucher_gl_show_signature_block": 1,
	"voucher_gl_hide_empty_columns": 1,
	"voucher_gl_combine_dimensions": 1,
	"voucher_gl_show_account_hierarchy": 1,
	"voucher_gl_show_party_breakdown": 1,
	"voucher_gl_show_dimension_breakdown": 1,
	"voucher_gl_show_group_subtotals": 1,
	"show_amount_scale_label": 1,
}

OFF_DEFAULTS = {
	"voucher_gl_show_letterhead": 0,
	"append_source_attachments": 0,
}

SELECT_DEFAULTS = {
	"voucher_gl_layout": LAYOUT_STANDARD,
	"voucher_gl_page_layout": "Auto",
	"voucher_gl_amount_scale": "Use Default",
	"default_amount_display_scale": "Auto",
}

INT_DEFAULTS = {
	"voucher_gl_hierarchy_start_level": 2,
	"amount_scale_decimal_precision": 2,
}


def _field_value(settings, fieldname: str):
	if settings and settings.meta.has_field(fieldname):
		return settings.get(fieldname)
	rows = frappe.db.sql(
		"""
		select value from tabSingles
		where doctype=%s and field=%s
		limit 1
		""",
		("Iran Accounting Settings", fieldname),
	)
	return rows[0][0] if rows else None


def _singles_value(fieldname: str):
	"""Compatibility helper for tests and older call sites."""
	rows = frappe.db.sql(
		"""
		select value from tabSingles
		where doctype=%s and field=%s
		limit 1
		""",
		("Iran Accounting Settings", fieldname),
	)
	return rows[0][0] if rows else None


def apply_voucher_gl_print_defaults(settings=None, *, force: bool = False) -> bool:
	"""Apply defaults. Returns True when settings document was saved."""
	if not frappe.db.exists("DocType", "Iran Accounting Settings"):
		return False
	settings = settings or frappe.get_single("Iran Accounting Settings")
	version = cint(_field_value(settings, VERSION_FIELD) or 0)
	needs_version_seed = version < SEED_VERSION
	changed = False

	for fieldname, default in SELECT_DEFAULTS.items():
		if not settings.meta.has_field(fieldname):
			continue
		if force or needs_version_seed or not settings.get(fieldname):
			if settings.get(fieldname) != default:
				settings.set(fieldname, default)
				changed = True

	for fieldname, default in ON_DEFAULTS.items():
		if not settings.meta.has_field(fieldname):
			continue
		if force or needs_version_seed:
			if cint(settings.get(fieldname)) != cint(default):
				settings.set(fieldname, default)
				changed = True
		elif cint(settings.get(fieldname)) == 0 and _singles_value(fieldname) is None:
			settings.set(fieldname, default)
			changed = True
		elif cint(settings.get(fieldname)) == 0 and cstr(
			settings.meta.get_field(fieldname).default
		) in ("1", 1, "True"):
			# Migrate often writes Check=0 into Singles; promote schema default ON once.
			# Without version bump this path only runs when meta default is ON.
			pass

	for fieldname, default in OFF_DEFAULTS.items():
		if not settings.meta.has_field(fieldname):
			continue
		if force or needs_version_seed or _singles_value(fieldname) is None:
			if cint(settings.get(fieldname)) != cint(default):
				settings.set(fieldname, default)
				changed = True

	for fieldname, default in INT_DEFAULTS.items():
		if not settings.meta.has_field(fieldname):
			continue
		if force or needs_version_seed or settings.get(fieldname) in (None, ""):
			if cint(settings.get(fieldname)) != cint(default):
				settings.set(fieldname, default)
				changed = True

	if needs_version_seed or force:
		if settings.meta.has_field(VERSION_FIELD) and cint(settings.get(VERSION_FIELD)) != SEED_VERSION:
			settings.set(VERSION_FIELD, SEED_VERSION)
			changed = True

	if changed:
		settings.flags.ignore_permissions = True
		settings.flags.ignore_mandatory = True
		settings.save()
		frappe.db.commit()
		return True

	return False


def execute():
	apply_voucher_gl_print_defaults()
