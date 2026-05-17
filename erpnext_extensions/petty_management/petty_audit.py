"""Structured audit logging for Petty Management accounting actions."""

from __future__ import annotations

import json
from typing import Any

import frappe


def log_event(event: str, **payload: Any) -> None:
	"""Emit one structured INFO line for ERP observability (audit trail).

	Does not replace accounting documents; supplements operational traceability.
	"""
	try:
		line = {
			"event": event,
			"site": getattr(frappe.local, "site", None),
			"user": frappe.session.user if frappe.session else None,
			**payload,
		}
		frappe.logger("petty_management").info(json.dumps(line, default=str))
	except Exception:
		frappe.logger("petty_management").exception("petty_audit_log_failed")
