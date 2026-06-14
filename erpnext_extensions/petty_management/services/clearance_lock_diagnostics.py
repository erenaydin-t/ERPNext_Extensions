"""InnoDB lock diagnostics when PM Clearance save hits QueryTimeoutError."""

from __future__ import annotations

import json
import re

import frappe
from frappe.utils import cstr

_SQL_TABLE_RE = re.compile(r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+[`']?([^`'\s]+)", re.I)


def _table_from_sql(sql: str | None) -> str | None:
	if not sql:
		return None
	m = _SQL_TABLE_RE.search(sql)
	return m.group(1) if m else None


def log_pm_clearance_lock_diagnostics(
	*,
	phase: str,
	doc=None,
	last_sql: str | None = None,
) -> None:
	"""Capture processlist / InnoDB trx / status at lock timeout (Error Log + error logger)."""
	payload: dict = {
		"phase": phase,
		"doctype": getattr(doc, "doctype", None) if doc else "PM Clearance",
		"doc_name": getattr(doc, "name", None) if doc else None,
		"employee": getattr(doc, "employee", None) if doc else None,
		"last_sql": last_sql or getattr(frappe.db, "last_query", None),
	}
	payload["sql_target_table"] = _table_from_sql(payload.get("last_sql"))

	for label, sql in (
		("processlist", "SHOW FULL PROCESSLIST"),
		("innodb_status", "SHOW ENGINE INNODB STATUS"),
	):
		try:
			rows = frappe.db.sql(sql, as_dict=True) if label == "processlist" else frappe.db.sql(sql)
			if label == "innodb_status" and rows:
				payload[label] = cstr(rows[0][2] if len(rows[0]) > 2 else rows[0])
			else:
				payload[label] = rows
		except Exception as exc:
			payload[f"{label}_error"] = cstr(exc)

	try:
		payload["innodb_trx"] = frappe.db.sql(
			"""
			SELECT trx_id, trx_state, trx_started, trx_mysql_thread_id,
			       trx_query, trx_tables_locked, trx_rows_locked
			FROM information_schema.innodb_trx
			""",
			as_dict=True,
		)
	except Exception as exc:
		payload["innodb_trx_error"] = cstr(exc)

	try:
		payload["innodb_lock_waits"] = frappe.db.sql(
			"""
			SELECT
				r.trx_id waiting_trx_id,
				r.trx_mysql_thread_id waiting_thread,
				b.trx_id blocking_trx_id,
				b.trx_mysql_thread_id blocking_thread,
				l.lock_table,
				l.lock_index,
				l.lock_mode,
				l.lock_type
			FROM information_schema.innodb_lock_waits w
			INNER JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
			INNER JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id
			INNER JOIN performance_schema.data_locks l ON l.engine_lock_id = w.requesting_engine_lock_id
			""",
			as_dict=True,
		)
	except Exception as exc:
		payload["innodb_lock_waits_error"] = cstr(exc)

	message = json.dumps(payload, indent=2, default=str)
	frappe.log_error(message=message, title="PM Clearance lock timeout diagnostics")
	frappe.logger("pm_clearance").error(message)
