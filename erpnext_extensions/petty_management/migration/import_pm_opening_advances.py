"""Import PM Opening Advances from CSV rows (bench execute).

Example::

    bench --site SITE execute erpnext_extensions.petty_management.migration.import_pm_opening_advances.run \\
        --kwargs "{'rows': [{'holder': 'EMP-CO', 'opening_date': '2026-06-01', 'opening_advance_amount': 100000}]}"

Or pass ``csv_path`` absolute path with header row matching import columns.
"""

from __future__ import annotations

import csv
from typing import Any

import frappe
from frappe.utils import flt, getdate

REQUIRED_COLUMNS = (
	"holder",
	"opening_date",
	"opening_advance_amount",
)


def run(
	rows: list[dict[str, Any]] | None = None,
	csv_path: str | None = None,
	submit: int | bool = 1,
	dry_run: int | bool = 0,
) -> dict[str, Any]:
	"""Create PM Opening Advance documents (no migration batch)."""
	frappe.flags.ignore_permissions = True
	data = list(rows or [])
	if csv_path:
		data.extend(_read_csv(csv_path))
	summary = {"created": [], "skipped": [], "errors": []}
	for idx, row in enumerate(data, start=1):
		try:
			result = _import_one_row(row, submit=bool(int(submit)), dry_run=bool(int(dry_run)))
			if result.get("skipped"):
				summary["skipped"].append(result)
			else:
				summary["created"].append(result)
		except Exception as exc:
			summary["errors"].append({"row": idx, "data": row, "error": str(exc)})
	if not dry_run:
		frappe.db.commit()
	return summary


def _read_csv(path: str) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	with open(path, newline="", encoding="utf-8") as fh:
		reader = csv.DictReader(fh)
		for row in reader:
			out.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k})
	return out


def _import_one_row(row: dict[str, Any], *, submit: bool, dry_run: bool) -> dict[str, Any]:
	for col in REQUIRED_COLUMNS:
		if not row.get(col):
			raise frappe.ValidationError(f"Missing required column: {col}")

	holder = row["holder"]
	if not frappe.db.exists("PM Holder", holder):
		raise frappe.ValidationError(f"PM Holder not found: {holder}")

	if dry_run:
		return {"dry_run": True, "holder": holder}

	doc = frappe.new_doc("PM Opening Advance")
	doc.holder = holder
	doc.opening_date = getdate(row.get("opening_date"))
	doc.opening_source_type = row.get("opening_source_type") or "Opening Balance"
	doc.opening_advance_amount = flt(row.get("opening_advance_amount"))
	doc.previously_settled_before_migration = flt(row.get("previously_settled_before_migration"))
	doc.reference_no = row.get("reference_no") or ""
	doc.opening_reconciliation_reference = row.get("opening_reconciliation_reference") or ""
	doc.opening_reconciliation_note = row.get("opening_reconciliation_note") or ""
	doc.remarks = row.get("remarks") or ""
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return {"name": doc.name, "holder": holder, "submitted": submit}
