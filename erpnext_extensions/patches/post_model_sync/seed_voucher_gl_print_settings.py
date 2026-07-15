# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Seed Voucher GL Print settings defaults (idempotent)."""

from __future__ import annotations

import frappe
from frappe.utils import cint

from erpnext_extensions.iran_accounting.account_explorer.voucher_gl_print import (
	DEFAULT_VOUCHER_GL_PRINT_FORMAT,
)


def execute():
	if not frappe.db.exists("DocType", "Iran Accounting Settings"):
		return
	settings = frappe.get_single("Iran Accounting Settings")
	changed = False

	# New Check columns on existing Single docs often land as 0; enable defaults once.
	if settings.meta.has_field("show_print_voucher") and not cint(settings.get("show_print_voucher")):
		# Only flip when source format not configured either → first-time defaults.
		if not settings.get("account_explorer_voucher_print_format"):
			settings.show_print_voucher = 1
			changed = True
		# If a source format already exists, leave show_print_voucher as-is.
	elif settings.meta.has_field("show_print_voucher") and settings.get("show_print_voucher") is None:
		settings.show_print_voucher = 1
		changed = True

	if settings.meta.has_field("show_print_gl"):
		# Print GL is required for release; ensure enabled when format is available.
		if frappe.db.exists("Print Format", DEFAULT_VOUCHER_GL_PRINT_FORMAT):
			if not cint(settings.get("show_print_gl")):
				settings.show_print_gl = 1
				changed = True
			if not settings.get("voucher_gl_print_format"):
				settings.voucher_gl_print_format = DEFAULT_VOUCHER_GL_PRINT_FORMAT
				changed = True
		elif not settings.get("voucher_gl_print_format"):
			# Format not synced yet — still enable flag for next migrate.
			settings.show_print_gl = 1
			changed = True

	if changed:
		settings.flags.ignore_permissions = True
		settings.flags.ignore_mandatory = True
		settings.save()
