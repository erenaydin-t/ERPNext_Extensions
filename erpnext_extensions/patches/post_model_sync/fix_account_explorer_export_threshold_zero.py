"""Reset Account Explorer export background threshold when invalid (0 / empty).

Production sites stored ``export_background_threshold = 0``, which made every
non-empty export queue (``total_rows > 0``). Default and DocType default are 5000.
"""

from __future__ import annotations

import frappe

from erpnext_extensions.iran_accounting.account_explorer.export import (
	DEFAULT_EXPORT_BACKGROUND_THRESHOLD,
)


SETTINGS = "Iran Accounting Settings"


def execute():
	if not frappe.db.exists("DocType", SETTINGS):
		return

	try:
		settings = frappe.get_single(SETTINGS)
	except Exception:
		return

	raw = settings.export_background_threshold
	try:
		value = int(raw) if raw is not None and raw != "" else 0
	except (TypeError, ValueError):
		value = 0

	if value < 1:
		settings.export_background_threshold = DEFAULT_EXPORT_BACKGROUND_THRESHOLD
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.clear_cache(doctype=SETTINGS)
