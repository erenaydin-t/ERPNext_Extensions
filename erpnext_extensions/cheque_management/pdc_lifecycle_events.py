# Copyright (c) 2026, ERPNext Extensions contributors
"""Append-only PDC lifecycle event log (source of truth for v4.4.4+ rollback)."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	build_pdc_accounting_transition_key,
	parse_pdc_transition_key_parts,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import _purpose_for_transition
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	PDC_ACCOUNTING_JOURNAL_ENTRY,
	normalize_workflow_state_value,
)

EVENT_TYPE_ACCOUNTING = "accounting"
EVENT_TYPE_WORKFLOW_ONLY = "workflow_only"

LIFECYCLE_EVENT_FIELDS = (
	"name",
	"event_sequence",
	"from_state",
	"to_state",
	"action",
	"event_type",
	"purpose",
	"journal_entry",
	"journal_reference_name",
	"pdc_transition_key",
	"snapshot_json",
	"is_rolled_back",
	"idx",
)

SNAPSHOT_FIELDS = (
	"workflow_state",
	"cheque_status",
	"docstatus",
	"is_at_bank",
	"sent_to_bank_date",
	"returned_from_bank_date",
	"cleared_date",
	"bounced_date",
	"returned_date",
	"return_reason",
	"handover_date",
	"recognition_je_posted",
	"clear_je_posted",
	"instrument_dead",
	"instrument_dead_reason",
	"holder_party",
	"holder_party_type",
	"cheque_leaf",
)


def event_type_from_accounting_action(action: str | None) -> str:
	if (action or "").strip() == PDC_ACCOUNTING_JOURNAL_ENTRY:
		return EVENT_TYPE_ACCOUNTING
	return EVENT_TYPE_WORKFLOW_ONLY


def snapshot_pdc_operational_fields(doc) -> str:
	"""Serialize operational fields from the pre-transition document (or current if none)."""
	data: dict[str, Any] = {}
	if doc is None:
		return json.dumps(data)
	for field in SNAPSHOT_FIELDS:
		value = getattr(doc, field, None)
		if hasattr(value, "isoformat"):
			value = str(value)
		data[field] = value
	return json.dumps(data, default=str)


def parse_snapshot_json(raw: str | None) -> dict[str, Any]:
	text = (raw or "").strip()
	if not text:
		return {}
	try:
		parsed = json.loads(text)
	except (TypeError, ValueError):
		return {}
	return parsed if isinstance(parsed, dict) else {}


def lifecycle_event_doctype_ready() -> bool:
	try:
		db = getattr(frappe, "db", None)
		if db is None:
			return False
		return bool(db.table_exists("PDC Lifecycle Event"))
	except Exception:
		return False


def load_lifecycle_events(pdc_name: str, *, active_only: bool = True) -> list[dict[str, Any]]:
	if not pdc_name or not lifecycle_event_doctype_ready():
		return []
	filters: dict[str, Any] = {"parent": pdc_name, "parenttype": "Post Dated Cheque"}
	if active_only:
		filters["is_rolled_back"] = 0
	return frappe.get_all(
		"PDC Lifecycle Event",
		filters=filters,
		fields=list(LIFECYCLE_EVENT_FIELDS),
		order_by="event_sequence asc, idx asc",
	)


def load_active_lifecycle_events(pdc_name: str) -> list[dict[str, Any]]:
	return load_lifecycle_events(pdc_name, active_only=True)


def next_event_sequence(pdc_name: str) -> int:
	if not pdc_name or not lifecycle_event_doctype_ready():
		return 1
	current = frappe.db.sql(
		"""
		select max(event_sequence) from `tabPDC Lifecycle Event`
		where parent = %s and parenttype = 'Post Dated Cheque'
		""",
		(pdc_name,),
	)
	max_seq = current[0][0] if current and current[0] else None
	return int(max_seq or 0) + 1


def latest_journal_reference_for_transition(
	pdc_name: str, from_state: str, to_state: str
) -> dict[str, Any] | None:
	from_s = normalize_workflow_state_value(from_state)
	to_s = normalize_workflow_state_value(to_state)
	rows = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry", "purpose", "pdc_transition_key", "idx"],
		order_by="idx desc, creation desc",
	)
	for row in rows:
		parts = parse_pdc_transition_key_parts(row.get("pdc_transition_key"), pdc_name)
		if not parts:
			continue
		_direction, f, t = parts
		if f == from_s and t == to_s:
			return row
	return None


def capture_pdc_lifecycle_event(
	pdc,
	from_state: str,
	to_state: str,
	accounting_action: str | None,
	*,
	snapshot_json: str | None = None,
	action: str | None = None,
) -> str | None:
	"""Append one lifecycle event after a successful workflow transition. Never deletes rows."""
	if getattr(frappe.flags, "in_pdc_workflow_rollback", None):
		return None
	if getattr(pdc.flags, "skip_pdc_lifecycle_event_capture", False):
		return None
	if not lifecycle_event_doctype_ready() or not getattr(pdc, "name", None):
		return None

	from_s = normalize_workflow_state_value(from_state)
	to_s = normalize_workflow_state_value(to_state)
	if from_s == to_s:
		return None

	active = load_active_lifecycle_events(pdc.name)
	if active:
		last = active[-1]
		if (
			normalize_workflow_state_value(last.get("to_state")) == to_s
			and normalize_workflow_state_value(last.get("from_state")) == from_s
			and not cint(last.get("is_rolled_back"))
		):
			return last.get("name")

	event_type = event_type_from_accounting_action(accounting_action)
	direction = (getattr(pdc, "cheque_direction", None) or "").strip()
	transition_key = build_pdc_accounting_transition_key(pdc.name, direction, from_s, to_s)
	purpose = ""
	journal_entry = ""
	journal_reference_name = ""
	if event_type == EVENT_TYPE_ACCOUNTING:
		ref = latest_journal_reference_for_transition(pdc.name, from_s, to_s)
		if ref:
			journal_entry = (ref.get("journal_entry") or "").strip()
			journal_reference_name = (ref.get("name") or "").strip()
			purpose = (ref.get("purpose") or "").strip()
			if ref.get("pdc_transition_key"):
				transition_key = ref.get("pdc_transition_key")
		if not purpose:
			purpose = _purpose_for_transition(direction, from_s, to_s) or ""
	else:
		purpose = _purpose_for_transition(direction, from_s, to_s) or ""

	seq = next_event_sequence(pdc.name)
	idx = frappe.db.count("PDC Lifecycle Event", {"parent": pdc.name}) + 1
	now = now_datetime()
	doc = frappe.get_doc(
		{
			"doctype": "PDC Lifecycle Event",
			"parent": pdc.name,
			"parenttype": "Post Dated Cheque",
			"parentfield": "lifecycle_events",
			"idx": idx,
			"event_sequence": seq,
			"from_state": from_s,
			"to_state": to_s,
			"action": (action or "").strip(),
			"event_type": event_type,
			"purpose": purpose,
			"journal_entry": journal_entry or None,
			"journal_reference_name": journal_reference_name,
			"pdc_transition_key": transition_key,
			"snapshot_json": snapshot_json or "",
			"is_rolled_back": 0,
			"created_on": now,
			"created_by": frappe.session.user,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def mark_lifecycle_events_rolled_back(
	pdc_name: str,
	event_names: list[str],
	*,
	rollback_log: str | None = None,
) -> None:
	if not event_names:
		return
	now = now_datetime()
	user = frappe.session.user
	for name in event_names:
		if not name or not frappe.db.exists("PDC Lifecycle Event", name):
			continue
		frappe.db.set_value(
			"PDC Lifecycle Event",
			name,
			{
				"is_rolled_back": 1,
				"rolled_back_on": now,
				"rolled_back_by": user,
				"rollback_log": rollback_log or "",
			},
			update_modified=False,
		)


def validate_lifecycle_events_immutable(doc) -> None:
	"""Prevent edit/delete of lifecycle events on normal PDC saves."""
	if doc.is_new() or getattr(frappe.flags, "in_pdc_workflow_rollback", None):
		return
	if not lifecycle_event_doctype_ready():
		return
	prev = set(frappe.get_all("PDC Lifecycle Event", filters={"parent": doc.name}, pluck="name"))
	if not prev:
		return
	current = {r.name for r in (doc.get("lifecycle_events") or []) if r.name}
	if prev - current:
		frappe.throw(_("PDC lifecycle events are immutable; rows cannot be removed."))
	immutable_fields = (
		"event_sequence",
		"from_state",
		"to_state",
		"action",
		"event_type",
		"purpose",
		"journal_entry",
		"journal_reference_name",
		"pdc_transition_key",
		"snapshot_json",
		"created_on",
		"created_by",
	)
	for row in doc.get("lifecycle_events") or []:
		if not row.name or row.name not in prev:
			continue
		old = frappe.db.get_value("PDC Lifecycle Event", row.name, immutable_fields, as_dict=True)
		for field in immutable_fields:
			if str(row.get(field) or "") != str((old or {}).get(field) or ""):
				frappe.throw(_("PDC lifecycle events are immutable; rows cannot be modified."))


__all__ = [
	"EVENT_TYPE_ACCOUNTING",
	"EVENT_TYPE_WORKFLOW_ONLY",
	"SNAPSHOT_FIELDS",
	"capture_pdc_lifecycle_event",
	"event_type_from_accounting_action",
	"latest_journal_reference_for_transition",
	"lifecycle_event_doctype_ready",
	"load_active_lifecycle_events",
	"load_lifecycle_events",
	"mark_lifecycle_events_rolled_back",
	"parse_snapshot_json",
	"snapshot_pdc_operational_fields",
	"validate_lifecycle_events_immutable",
]
