from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import getdate


def execute(filters=None):
	filters = frappe._dict(filters or {})

	columns = [
		{
			"label": "PDC",
			"fieldname": "pdc",
			"fieldtype": "Link",
			"options": "Post Dated Cheque",
			"width": 140,
		},
		{"label": "Cheque Direction", "fieldname": "cheque_direction", "fieldtype": "Data", "width": 110},
		{
			"label": "Party",
			"fieldname": "party",
			"fieldtype": "Dynamic Link",
			"options": "party_type",
			"width": 180,
		},
		{"label": "Company", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 140},
		{
			"label": "Bank Account",
			"fieldname": "bank_account",
			"fieldtype": "Link",
			"options": "Bank Account",
			"width": 140,
		},
		{"label": "Cheque No", "fieldname": "cheque_no", "fieldtype": "Data", "width": 120},
		{"label": "Cheque Purpose", "fieldname": "cheque_purpose", "fieldtype": "Data", "width": 180},
		{"label": "Due Date", "fieldname": "cheque_due_date", "fieldtype": "Date", "width": 110},
		{"label": "Amount", "fieldname": "cheque_amount", "fieldtype": "Currency", "width": 120},
		{"label": "Workflow State", "fieldname": "workflow_state", "fieldtype": "Data", "width": 120},
		{"label": "Cheque Status", "fieldname": "cheque_status", "fieldtype": "Data", "width": 120},
		{"label": "Days To Due", "fieldname": "days_to_due", "fieldtype": "Int", "width": 90},
		{"label": "Overdue Days", "fieldname": "overdue_days", "fieldtype": "Int", "width": 90},
	]

	where = []
	params: dict[str, Any] = {}

	if filters.company:
		where.append("company = %(company)s")
		params["company"] = filters.company

	if filters.cheque_direction:
		where.append("cheque_direction = %(cheque_direction)s")
		params["cheque_direction"] = filters.cheque_direction

	if filters.from_due_date:
		where.append("cheque_due_date >= %(from_due_date)s")
		params["from_due_date"] = filters.from_due_date

	if filters.to_due_date:
		where.append("cheque_due_date <= %(to_due_date)s")
		params["to_due_date"] = filters.to_due_date

	if filters.cheque_status:
		where.append("cheque_status = %(cheque_status)s")
		params["cheque_status"] = filters.cheque_status

	if filters.workflow_state:
		where.append("workflow_state = %(workflow_state)s")
		params["workflow_state"] = filters.workflow_state

	if filters.cheque_purpose:
		where.append("cheque_purpose like %(cheque_purpose)s")
		params["cheque_purpose"] = f"%{filters.cheque_purpose}%"

	conditions = (" where " + " and ".join(where)) if where else ""

	rows = frappe.db.sql(
		f"""
		select
			name as pdc,
			cheque_direction,
			party_type,
			party,
			company,
			bank_account,
			cheque_no,
			cheque_purpose,
			cheque_due_date,
			cheque_amount,
			workflow_state,
			cheque_status
		from `tabPost Dated Cheque`
		{conditions}
		order by cheque_due_date asc, modified desc
		""",
		params,
		as_dict=True,
	)

	today = getdate()
	data = []
	for r in rows:
		due = getdate(r.cheque_due_date) if r.cheque_due_date else None
		if due:
			days_to_due = int((due - today).days)
			overdue_days = int(-days_to_due) if days_to_due < 0 else None
		else:
			days_to_due = None
			overdue_days = None

		# Apply maturity filters after computing days_to_due (DataTable column filter is contains-based).
		if days_to_due is None:
			continue

		if filters.get("days_to_due_exact") is not None and filters.days_to_due_exact != "":
			if int(filters.days_to_due_exact) != days_to_due:
				continue

		if int(filters.get("overdue_only") or 0) == 1 and not (days_to_due < 0):
			continue

		if int(filters.get("due_today") or 0) == 1 and days_to_due != 0:
			continue

		if filters.get("near_due_days") not in (None, ""):
			near = int(filters.near_due_days)
			if not (0 <= days_to_due <= near):
				continue

		data.append(
			{
				"pdc": r.pdc,
				"cheque_direction": r.cheque_direction,
				"party_type": r.party_type,
				"party": r.party,
				"company": r.company,
				"bank_account": r.bank_account,
				"cheque_no": r.cheque_no,
				"cheque_purpose": r.cheque_purpose,
				"cheque_due_date": r.cheque_due_date,
				"cheque_amount": r.cheque_amount,
				"workflow_state": r.workflow_state,
				"cheque_status": r.cheque_status,
				"days_to_due": days_to_due,
				"overdue_days": overdue_days,
			}
		)

	return columns, data
