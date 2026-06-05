"""TRUE live E2E: Cheque Opening Import document → Preview → Execute Import (development.localhost).

Does NOT call import_row directly. Uses real COI + File + xlsx workflow.

bench --site development.localhost execute \\
  erpnext_extensions.cheque_management.doctype.cheque_opening_import.run_live_cheque_opening_import_full_e2e.run
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

import frappe
from frappe.utils import cint, getdate, today

from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
	TEMPLATE_HEADERS,
)


def _counts_for_pdc(pdc_name: str | None) -> dict:
	if not pdc_name:
		return {"journal_reference_count": None, "journal_entry_count": None, "references": []}
	refs = frappe.get_all(
		"PDC Journal Reference",
		filters={"parent": pdc_name, "parenttype": "Post Dated Cheque"},
		fields=["name", "journal_entry", "purpose"],
	)
	jes = {r.journal_entry for r in refs if r.journal_entry}
	return {
		"journal_reference_count": len(refs),
		"journal_entry_count": len(jes),
		"references": refs,
	}


def run():
	frappe.set_user("Administrator")
	started_at = frappe.utils.now()

	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	customer = frappe.db.get_value("Customer", {"disabled": 0}, "name", order_by="modified desc")
	drawer_bank = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")
	if not (company and customer and drawer_bank):
		frappe.throw(f"Missing site data company={company} customer={customer} drawer_bank={drawer_bank}")

	suffix = str(int(time.time()))
	cheque_no = f"COI-FULL-{suffix}"
	sayad = f"OB-SAYAD-{suffix}"[:32]
	t0 = getdate(today())
	due = t0 + timedelta(days=30)

	import openpyxl

	fname = f"cheque_opening_import_full_e2e_{suffix}.xlsx"
	site_path = frappe.get_site_path("private", "files", fname)

	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = "Data"
	ws.append(TEMPLATE_HEADERS)
	# Receivable → Registered (walks Draft→Registered inside import_row via execute_import)
	row = [
		"Receivable",
		company,
		"",  # bank not required for Registered receivable
		"",
		cheque_no,
		due,
		"250.5",
		"Customer",
		customer,
		"Registered",
		drawer_bank,
		t0,
		None,
		None,
		None,
		None,
		None,
		sayad,
	]
	ws.append(row)
	wb.save(site_path)

	file_url = f"/private/files/{fname}"
	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": fname,
			"file_url": file_url,
			"is_private": 1,
			"folder": "Home",
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()

	coi = frappe.get_doc({"doctype": "Cheque Opening Import", "import_file": file_url})
	coi.insert(ignore_permissions=True)
	frappe.db.commit()

	preview_result = coi.preview_file()
	frappe.db.commit()
	coi.reload()

	if (coi.import_status or "").strip() != "Previewed":
		out = {
			"passed": False,
			"phase": "preview",
			"coi_name": coi.name,
			"import_status": coi.import_status,
			"preview_result": preview_result,
			"items": [
				{
					"row_number": i.row_number,
					"row_status": i.row_status,
					"validation_message": i.validation_message,
					"error_detail": i.error_detail,
				}
				for i in (coi.items or [])
			],
		}
		print(json.dumps(out, indent=2, default=str))
		frappe.throw(f"Preview failed: {coi.import_status}")

	execute_result = coi.execute_import()
	frappe.db.commit()
	coi.reload()

	pdc_name = None
	for item in coi.items or []:
		if (item.row_status or "") == "Imported":
			pdc_name = item.imported_pdc or item.post_dated_cheque
			break

	pdc_row = None
	if pdc_name:
		pdc_row = frappe.db.get_value(
			"Post Dated Cheque",
			pdc_name,
			["name", "workflow_state", "docstatus", "is_opening_import", "opening_import", "cheque_no"],
			as_dict=True,
		)

	counts = _counts_for_pdc(pdc_name)

	sql_evidence = {}
	if pdc_name:
		sql_evidence["pdc_journal_reference_count"] = frappe.db.sql(
			"SELECT COUNT(*) FROM `tabPDC Journal Reference` WHERE parent = %s",
			(pdc_name,),
		)[0][0]
		je_names = [r.journal_entry for r in counts["references"] if r.journal_entry]
		if je_names:
			sql_evidence["journal_entry_count"] = frappe.db.sql(
				"SELECT COUNT(*) FROM `tabJournal Entry` WHERE name IN ({})".format(
					", ".join(["%s"] * len(je_names))
				),
				tuple(je_names),
			)[0][0]
		else:
			sql_evidence["journal_entry_count"] = 0

	errors = []
	if not frappe.db.exists("Cheque Opening Import", coi.name):
		errors.append("COI document missing in DB")
	if (coi.import_status or "").strip() != "Completed":
		errors.append(f"import_status expected Completed, got {coi.import_status!r}")
	if not pdc_name:
		errors.append("no imported PDC on COI items")
	if pdc_row and not cint(pdc_row.is_opening_import):
		errors.append("PDC is_opening_import not set")
	if pdc_row and pdc_row.opening_import != coi.name:
		errors.append(f"PDC opening_import link expected {coi.name}, got {pdc_row.opening_import}")
	if counts["journal_entry_count"] != 0 or counts["journal_reference_count"] != 0:
		errors.append(f"expected 0 JE/refs, got {counts}")

	ended_at = frappe.utils.now()

	out = {
		"passed": not errors,
		"errors": errors,
		"site": frappe.local.site,
		"started_at": started_at,
		"ended_at": ended_at,
		"coi_name": coi.name,
		"import_file": file_url,
		"import_status": coi.import_status,
		"preview_result": preview_result,
		"execute_result": execute_result,
		"pdc_name": pdc_name,
		"pdc": pdc_row,
		"counts": counts,
		"sql_evidence": sql_evidence,
		"coi_items": [
			{
				"row_number": i.row_number,
				"row_status": i.row_status,
				"validation_message": i.validation_message,
				"imported_pdc": i.imported_pdc,
				"post_dated_cheque": i.post_dated_cheque,
			}
			for i in (coi.items or [])
		],
	}
	print(json.dumps(out, indent=2, default=str))
	if errors:
		frappe.throw("Cheque Opening Import full E2E failed:\n" + "\n".join(errors))
	return out
