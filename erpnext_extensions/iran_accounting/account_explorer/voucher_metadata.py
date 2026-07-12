# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe

VOUCHER_TITLE_FIELDS: dict[str, list[str]] = {
	"Sales Invoice": ["title", "name"],
	"Purchase Invoice": ["bill_no", "title", "name"],
	"Payment Entry": ["reference_no", "name"],
	"Journal Entry": ["user_remark", "cheque_no", "name"],
	"Stock Entry": ["purpose", "name"],
	"Delivery Note": ["name"],
	"Purchase Receipt": ["name"],
}


def enrich_voucher_rows(rows: list[dict]) -> None:
	by_type: dict[str, list[dict]] = {}
	for row in rows:
		by_type.setdefault(row.get("voucher_type") or "", []).append(row)

	for voucher_type, type_rows in by_type.items():
		if not voucher_type:
			continue
		names = [row["voucher_no"] for row in type_rows if row.get("voucher_no")]
		if not names:
			continue
		fields = _title_fields_for(voucher_type)
		if not fields:
			continue
		meta_fields = ["name", *fields]
		try:
			docs = frappe.get_all(voucher_type, filters={"name": ("in", names)}, fields=meta_fields)
		except frappe.exceptions.DoesNotExistError:
			continue
		doc_map = {doc.name: doc for doc in docs}
		for row in type_rows:
			doc = doc_map.get(row.get("voucher_no"))
			if not doc:
				row.setdefault("voucher_title", row.get("voucher_no"))
				continue
			row["voucher_title"] = _pick_title(doc, fields) or row.get("voucher_no")
			row["reference"] = _pick_reference(doc, voucher_type)


def _title_fields_for(voucher_type: str) -> list[str]:
	if voucher_type in VOUCHER_TITLE_FIELDS:
		return VOUCHER_TITLE_FIELDS[voucher_type]
	meta = frappe.get_meta(voucher_type)
	candidates = []
	for fieldname in ("title", "reference_no", "bill_no", "user_remark", "purpose", "remarks"):
		if meta.has_field(fieldname):
			candidates.append(fieldname)
	return candidates or ["name"]


def _pick_title(doc, fields: list[str]) -> str | None:
	for fieldname in fields:
		value = doc.get(fieldname)
		if value:
			return str(value)
	return doc.get("name")


def _pick_reference(doc, voucher_type: str) -> str | None:
	if voucher_type == "Sales Invoice":
		return doc.get("po_no") or doc.get("name")
	if voucher_type == "Purchase Invoice":
		return doc.get("bill_no") or doc.get("name")
	if voucher_type == "Payment Entry":
		return doc.get("reference_no")
	return None
