"""One-off E2E: Cheque Opening Import with DECIMAL(30,9) amount. bench execute path below."""

from __future__ import annotations

import time
from datetime import date

import frappe

TARGET_AMOUNT_STR = "123456789012345.123456789"


def run():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name")
	bank = frappe.db.get_value("Bank Account", {"company": company, "disabled": 0}, "name")
	supplier = frappe.db.get_value("Supplier", {}, "name")
	if not (company and bank and supplier):
		frappe.throw("Missing Company / Bank Account / Supplier for E2E")

	import openpyxl
	from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
		TEMPLATE_HEADERS,
	)

	suffix = str(int(time.time()))[-8:]
	fname = f"cheque_opening_import_large_amount_{suffix}.xlsx"
	site_path = frappe.get_site_path("private", "files", fname)

	wb = openpyxl.Workbook()
	ws = wb.active
	ws.title = "Data"
	ws.append(TEMPLATE_HEADERS)
	data_row = [
			"Payable",
			company,
			bank,
			"",
			f"OB-LARGE-{suffix}",
			date.today(),
			TARGET_AMOUNT_STR,
			"Supplier",
			supplier,
			"Draft",
			None,
			None,
			None,
			None,
			None,
			None,
			None,
			f"SAYAD-LARGE-{suffix}",
			None,
	]
	ws.append(data_row)
	amt_col = TEMPLATE_HEADERS.index("cheque_amount") + 1
	amt_cell = ws.cell(row=2, column=amt_col)
	amt_cell.value = TARGET_AMOUNT_STR
	amt_cell.number_format = "@"
	wb.save(site_path)

	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": fname,
			"file_url": f"/private/files/{fname}",
			"is_private": 1,
			"folder": "Home",
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()

	doc = frappe.get_doc({"doctype": "Cheque Opening Import", "import_file": f"/private/files/{fname}"})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	preview = doc.preview_file()
	frappe.db.commit()
	doc.reload()

	if (doc.import_status or "").strip() != "Previewed":
		return {"error": "preview_failed", "status": doc.import_status, "preview": preview}

	exec_result = doc.execute_import()
	frappe.db.commit()
	doc.reload()

	pdc_name = None
	for row in doc.items or []:
		if (row.row_status or "") == "Imported":
			pdc_name = row.imported_pdc or row.post_dated_cheque
			break

	db_amount = None
	if pdc_name:
		db_amount = frappe.db.sql(
			"SELECT CAST(cheque_amount AS CHAR) FROM `tabPost Dated Cheque` WHERE name=%s",
			(pdc_name,),
		)[0][0]

	orm_amount = frappe.db.get_value("Post Dated Cheque", pdc_name, "cheque_amount") if pdc_name else None

	return {
		"import_doc": doc.name,
		"file": fname,
		"preview": preview,
		"execute": exec_result,
		"import_status": doc.import_status,
		"pdc": pdc_name,
		"db_amount_char": db_amount,
		"db_exact": db_amount == TARGET_AMOUNT_STR,
		"orm_amount": orm_amount,
		"items": [
			{
				"row": r.row_number,
				"status": r.row_status,
				"msg": (r.validation_message or "")[:200],
				"pdc": r.imported_pdc,
			}
			for r in (doc.items or [])
		],
	}
