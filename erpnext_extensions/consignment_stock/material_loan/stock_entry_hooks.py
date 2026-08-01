# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext_extensions.consignment_stock.constants import F_IS_RECEIPT, F_IS_RETURN
from erpnext_extensions.consignment_stock.material_loan.accounting import (
	force_temporary_clearing_on_items,
	get_material_loan_settings,
	require_material_loan_accounts,
	validate_loan_warehouses,
)
from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_EXPECTED_RETURN_DATE,
	F_IS_LOAN_ISSUE,
	F_IS_LOAN_RETURN,
	F_ISSUE_DETAIL,
	F_ISSUE_REF_HEADER,
	F_ISSUE_SE,
	F_PARTY,
	F_PARTY_TYPE,
	F_RECOGNITION_JE,
	F_SETTLEMENT_JE,
)
from erpnext_extensions.consignment_stock.material_loan.frozen_valuation import snapshot_issue_rows
from erpnext_extensions.consignment_stock.material_loan.party_account import validate_party_for_tracking
from erpnext_extensions.consignment_stock.material_loan.returnable_qty import (
	has_submitted_loan_returns,
	populate_return_row_snapshots,
	validate_return_quantities,
)
from erpnext_extensions.consignment_stock.material_loan import status as ml_status
from erpnext_extensions.consignment_stock.material_loan.stock_entry_rates import (
	lock_issue_outgoing_rates,
	prepare_return_rates,
)


def _sync_flags_from_type(doc) -> None:
	if not doc.stock_entry_type:
		return
	values = frappe.db.get_value(
		"Stock Entry Type",
		doc.stock_entry_type,
		[F_IS_LOAN_ISSUE, F_IS_LOAN_RETURN],
		as_dict=True,
	)
	if not values:
		return
	doc.set(F_IS_LOAN_ISSUE, cint(values.get(F_IS_LOAN_ISSUE)))
	doc.set(F_IS_LOAN_RETURN, cint(values.get(F_IS_LOAN_RETURN)))


def _is_issue(doc) -> bool:
	return bool(cint(doc.get(F_IS_LOAN_ISSUE)))


def _is_return(doc) -> bool:
	return bool(cint(doc.get(F_IS_LOAN_RETURN)))


def _validate_no_additional_costs(doc) -> None:
	if not (_is_issue(doc) or _is_return(doc)):
		return
	if doc.get("additional_costs"):
		frappe.throw(_("Additional Costs are not allowed on Material Loan Stock Entries."))
	for row in doc.get("items") or []:
		if flt(row.get("additional_cost")):
			frappe.throw(
				_("Row {0}: Additional Cost is not allowed on Material Loan Stock Entries.").format(
					row.idx
				)
			)


def before_validate(doc, method=None):
	_sync_flags_from_type(doc)
	if _is_issue(doc) or _is_return(doc):
		_validate_no_additional_costs(doc)


def validate(doc, method=None):
	_sync_flags_from_type(doc)
	if not (_is_issue(doc) or _is_return(doc)):
		return

	if cint(doc.get(F_IS_RECEIPT)) or cint(doc.get(F_IS_RETURN)):
		frappe.throw(_("Material Loan cannot be combined with inbound Consignment flags."))

	settings = get_material_loan_settings(doc.company)
	require_material_loan_accounts(settings)
	validate_party_for_tracking(doc.get(F_PARTY_TYPE), doc.get(F_PARTY))
	_validate_no_additional_costs(doc)
	force_temporary_clearing_on_items(doc)
	validate_loan_warehouses(doc)
	_apply_default_warehouses(doc, settings)

	if _is_issue(doc):
		if doc.purpose != "Material Issue":
			frappe.throw(_("Material Loan Issue Stock Entry must have Purpose Material Issue."))
		lock_issue_outgoing_rates(doc)
		if cint(settings.require_expected_return_date) and not doc.get(F_EXPECTED_RETURN_DATE):
			frappe.throw(_("Expected Return Date is required for Material Loan Issue."))
		ml_status.sync_draft_status(doc)

	if _is_return(doc):
		if doc.purpose != "Material Receipt":
			frappe.throw(_("Material Loan Return Stock Entry must have Purpose Material Receipt."))
		_apply_header_issue_default(doc)
		_validate_return_references(doc, settings)
		_validate_recognition_before_return(doc)
		prepare_return_rates(doc)
		populate_return_row_snapshots(doc)
		validate_return_quantities(doc)
		ml_status.sync_draft_status(doc)


def before_submit(doc, method=None):
	validate(doc, method)


def on_submit(doc, method=None):
	_sync_flags_from_type(doc)
	if _is_issue(doc):
		snapshot_issue_rows(doc)
		ml_status.on_issue_submit(doc)
	elif _is_return(doc):
		ml_status.on_return_submit(doc)


def before_cancel(doc, method=None):
	_sync_flags_from_type(doc)
	if _is_issue(doc):
		_block_issue_cancel(doc)
	elif _is_return(doc):
		_block_return_cancel(doc)


def on_cancel(doc, method=None):
	_sync_flags_from_type(doc)
	if _is_issue(doc):
		ml_status.on_issue_cancel(doc)
	elif _is_return(doc):
		ml_status.on_return_cancel(doc)


def on_update_after_submit(doc, method=None):
	_sync_flags_from_type(doc)
	if _is_issue(doc):
		ml_status.refresh_issue_statuses(doc.name)


def _apply_default_warehouses(doc, settings) -> None:
	if _is_issue(doc):
		default_wh = settings.get("default_material_loan_source_warehouse")
		if default_wh:
			for row in doc.get("items") or []:
				if not row.s_warehouse:
					row.s_warehouse = default_wh
	if _is_return(doc):
		default_wh = settings.get("default_material_loan_return_warehouse")
		if default_wh:
			for row in doc.get("items") or []:
				if not row.t_warehouse:
					row.t_warehouse = default_wh


def _apply_header_issue_default(doc) -> None:
	default_issue = doc.get(F_ISSUE_REF_HEADER)
	if not default_issue:
		return
	for row in doc.get("items") or []:
		if not row.get(F_ISSUE_SE):
			row.set(F_ISSUE_SE, default_issue)


def _validate_recognition_before_return(doc) -> None:
	issues = {row.get(F_ISSUE_SE) for row in doc.get("items") or [] if row.get(F_ISSUE_SE)}
	for issue_name in issues:
		je = frappe.db.get_value("Stock Entry", issue_name, F_RECOGNITION_JE)
		if not je:
			frappe.throw(
				_("Material Loan Issue {0} has no Recognition Journal Entry.").format(issue_name)
			)
		if frappe.db.get_value("Journal Entry", je, "docstatus") != 1:
			frappe.throw(
				_(
					"Material Loan Recognition Journal Entry for {0} must be submitted before return."
				).format(issue_name)
			)


def _validate_return_references(doc, settings) -> None:
	party_type = doc.get(F_PARTY_TYPE)
	party = doc.get(F_PARTY)
	allow_diff_wh = cint(settings.allow_return_to_different_warehouse)

	for row in doc.get("items") or []:
		issue_name = row.get(F_ISSUE_SE)
		if not issue_name:
			frappe.throw(_("Row {0}: Material Loan Issue reference is required.").format(row.idx))

		issue = frappe.db.get_value(
			"Stock Entry",
			issue_name,
			["docstatus", "company", F_IS_LOAN_ISSUE, F_PARTY_TYPE, F_PARTY, F_RECOGNITION_JE],
			as_dict=True,
		)
		if not issue:
			frappe.throw(_("Row {0}: Material Loan Issue {1} not found.").format(row.idx, issue_name))
		if issue.docstatus != 1:
			frappe.throw(
				_("Row {0}: Material Loan Issue {1} must be submitted.").format(row.idx, issue_name)
			)
		if not cint(issue.get(F_IS_LOAN_ISSUE)):
			frappe.throw(
				_("Row {0}: {1} is not a Material Loan Issue.").format(row.idx, issue_name)
			)
		if issue.company != doc.company:
			frappe.throw(
				_("Row {0}: Material Loan Issue {1} belongs to another company.").format(
					row.idx, issue_name
				)
			)
		if issue.get(F_PARTY_TYPE) != party_type or issue.get(F_PARTY) != party:
			frappe.throw(
				_("Row {0}: Return party must match Material Loan Issue {1} party.").format(
					row.idx, issue_name
				)
			)

		detail = row.get(F_ISSUE_DETAIL)
		if not detail:
			detail = _autofill_issue_detail(row, issue_name)
		issue_row = frappe.db.get_value(
			"Stock Entry Detail",
			detail,
			["parent", "item_code", "s_warehouse", "batch_no", "serial_no", "serial_and_batch_bundle"],
			as_dict=True,
		)
		if not issue_row or issue_row.parent != issue_name:
			frappe.throw(
				_("Row {0}: Material Loan Issue Detail {1} is invalid.").format(row.idx, detail)
			)
		if issue_row.item_code != row.item_code:
			frappe.throw(
				_("Row {0}: Item must match Material Loan Issue row item {1}.").format(
					row.idx, issue_row.item_code
				)
			)
		if not allow_diff_wh and row.t_warehouse and issue_row.s_warehouse:
			if row.t_warehouse != issue_row.s_warehouse:
				frappe.throw(
					_(
						"Row {0}: Return warehouse must match Issue source warehouse {1}."
					).format(row.idx, issue_row.s_warehouse)
				)
		_validate_batch_and_serial(row, issue_row, issue_detail=detail)


def _parse_serials(row) -> set[str]:
	from erpnext.stock.doctype.serial_no.serial_no import get_serial_nos

	serials: set[str] = set()
	if isinstance(row, dict):
		serial_no = row.get("serial_no")
		bundle = row.get("serial_and_batch_bundle")
	else:
		serial_no = row.get("serial_no")
		bundle = row.get("serial_and_batch_bundle")
	if serial_no:
		serials.update(get_serial_nos(serial_no) or [])
	if bundle:
		from erpnext.stock.serial_batch_bundle import get_serial_nos_from_bundle

		serials.update(get_serial_nos_from_bundle(bundle) or [])
	return {s for s in serials if s}


def _validate_batch_and_serial(row, issue_row, *, issue_detail: str) -> None:
	issue_batch = issue_row.get("batch_no")
	if issue_batch:
		if not row.get("batch_no"):
			frappe.throw(
				_("Row {0}: Batch {1} is required to match the Material Loan Issue.").format(
					row.idx, issue_batch
				)
			)
		if row.batch_no != issue_batch:
			frappe.throw(
				_("Row {0}: Batch must match the Material Loan Issue batch {1}.").format(
					row.idx, issue_batch
				)
			)

	issued_serials = _parse_serials(issue_row)
	returned_serials = _parse_serials(row)
	if issued_serials:
		if not returned_serials:
			frappe.throw(
				_("Row {0}: Serial numbers are required to match the Material Loan Issue.").format(
					row.idx
				)
			)
		unknown = returned_serials - issued_serials
		if unknown:
			frappe.throw(
				_(
					"Row {0}: Serial number(s) {1} were not included in the Material Loan Issue."
				).format(row.idx, ", ".join(sorted(unknown)))
			)
		from erpnext_extensions.consignment_stock.material_loan.constants import F_IS_LOAN_RETURN

		prior = frappe.db.sql(
			f"""
			select sed.serial_no, sed.serial_and_batch_bundle
			from `tabStock Entry Detail` sed
			inner join `tabStock Entry` se on se.name = sed.parent
			where sed.docstatus = 1
			  and se.{F_IS_LOAN_RETURN} = 1
			  and sed.{F_ISSUE_DETAIL} = %s
			  and sed.parent != %s
			""",
			(issue_detail, row.parent or ""),
			as_dict=True,
		)
		already: set[str] = set()
		for p in prior:
			already |= _parse_serials(p)
		dup = returned_serials & already
		if dup:
			frappe.throw(
				_(
					"Row {0}: Serial number(s) {1} were already returned against this Material Loan Issue."
				).format(row.idx, ", ".join(sorted(dup)))
			)


def _autofill_issue_detail(row, issue_name: str) -> str:
	matches = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": issue_name, "item_code": row.item_code},
		pluck="name",
	)
	if len(matches) == 1:
		row.set(F_ISSUE_DETAIL, matches[0])
		return matches[0]
	frappe.throw(
		_("Row {0}: Material Loan Issue Detail is required (multiple issue rows for item).").format(
			row.idx
		)
	)


def _block_issue_cancel(doc) -> None:
	if has_submitted_loan_returns(doc.name):
		frappe.throw(
			_(
				"Cannot cancel Material Loan Issue {0} while submitted Material Loan Returns exist. "
				"Cancel Settlement JEs and Returns first."
			).format(doc.name)
		)
	je = doc.get(F_RECOGNITION_JE)
	if je and frappe.db.exists("Journal Entry", je):
		ds = frappe.db.get_value("Journal Entry", je, "docstatus")
		if ds == 1:
			frappe.throw(
				_(
					"Cannot cancel Material Loan Issue {0} while Recognition Journal Entry {1} is submitted. "
					"Cancel the Recognition JE first."
				).format(doc.name, je)
			)
		if ds == 0:
			frappe.throw(
				_(
					"Cancel or delete draft Recognition Journal Entry {0} before cancelling Material Loan Issue {1}."
				).format(je, doc.name)
			)


def _block_return_cancel(doc) -> None:
	je = doc.get(F_SETTLEMENT_JE)
	if je and frappe.db.exists("Journal Entry", je):
		ds = frappe.db.get_value("Journal Entry", je, "docstatus")
		if ds < 2:
			frappe.throw(
				_(
					"Cannot cancel Material Loan Return {0} while Settlement Journal Entry {1} exists. "
					"Cancel the Settlement JE first."
				).format(doc.name, je)
			)
