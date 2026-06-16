"""HTTP POST frappe.client.insert — same path as Desk Save on new PM Clearance."""

from __future__ import annotations

import json

import frappe
import requests


def execute():
	frappe.set_user("Administrator")
	oa = frappe.db.get_value("PM Opening Advance", {"docstatus": 1}, "name", order_by="creation desc")
	pi = frappe.db.sql(
		"""
		select name from `tabPurchase Invoice`
		where docstatus = 1 and outstanding_amount >= 1000
		order by modified desc limit 1
		""",
		pluck=1,
	)[0]
	holder = frappe.db.get_value("PM Opening Advance", oa, "holder")
	emp = frappe.db.get_value("PM Holder", holder, "employee")
	company = frappe.db.get_value("PM Opening Advance", oa, "company") or frappe.db.get_value(
		"Purchase Invoice", pi, "company"
	)
	doc = {
		"doctype": "PM Clearance",
		"company": company,
		"employee": emp,
		"transaction_date": frappe.utils.today(),
		"details": [
			{
				"doctype": "PM Clearance Detail",
				"settlement_type": "Purchase Invoice",
				"purchase_invoice": pi,
				"allocated_amount": 1000,
				"bill_no": "HTTP-SAVE-1",
			}
		],
		"request_allocations": [
			{
				"doctype": "PM Clearance Request Allocation",
				"funding_source_type": "PM Opening Advance",
				"pm_opening_advance": oa,
				"allocated_amount": 1000,
			}
		],
	}
	sid = frappe.session.sid or frappe.db.get_value("Sessions", {"user": frappe.session.user}, "sid")
	if not sid:
		from frappe.sessions import Session

		s = Session()
		sid = s.sid
	cookies = {"sid": sid}
	url = f"http://127.0.0.1:8000/api/method/frappe.client.insert"
	headers = {"Host": "development.localhost", "Content-Type": "application/json"}
	resp = requests.post(
		url,
		json={"doc": frappe.as_json(doc)},
		cookies=cookies,
		headers=headers,
		timeout=120,
	)
	out = {"status_code": resp.status_code, "body": resp.text[:2000]}
	if resp.ok:
		body = resp.json()
		out["pm_clearance"] = (body.get("message") or {}).get("name")
	print(json.dumps(out, indent=2))
