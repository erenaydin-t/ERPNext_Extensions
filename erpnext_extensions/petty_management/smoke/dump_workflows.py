import json

import frappe


def execute():
	out = {}
	for wf_name in ("PM Request Workflow", "PM Clearance Workflow"):
		if not frappe.db.exists("Workflow", wf_name):
			out[wf_name] = "MISSING"
			continue
		w = frappe.get_doc("Workflow", wf_name)
		out[wf_name] = {
			"is_active": w.is_active,
			"states": [{"state": s.state, "doc_status": s.doc_status} for s in w.states],
			"transitions": [
				{
					"state": t.state,
					"action": t.action,
					"next_state": t.next_state,
					"allowed": t.allowed,
				}
				for t in w.transitions
			],
		}
	print(json.dumps(out, indent=2))
