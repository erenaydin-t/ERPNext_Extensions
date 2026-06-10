# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from decimal import Decimal
from typing import Any

import frappe
from frappe.utils import cint, flt

from erpnext_extensions.facility_management.facility_balances import get_facility_balance_row
from erpnext_extensions.facility_management.facility_monetary import (
	get_exact_currency_decimal,
	parse_facility_amount,
)
from erpnext_extensions.facility_management.facility_settings_doc import (
	DEFAULT_RECEIPT_BANK_ROW,
	DEFAULT_RECEIPT_DEFERRED_ROW,
	DEFAULT_RECEIPT_LOAN_ROW,
	DEFAULT_RECEIPT_REMARKS,
	DEFAULT_REPAYMENT_BANK_ROW,
	DEFAULT_REPAYMENT_PENALTY_ROW,
	DEFAULT_REPAYMENT_PRINCIPAL_ROW,
	DEFAULT_REPAYMENT_PROFIT_ROW,
	DEFAULT_REPAYMENT_REMARKS,
	dimensions_for_je_row,
	get_facility_settings_doc,
	resolve_account,
	template_chain,
)
from erpnext_extensions.facility_management.facility_templates import (
	build_template_context,
	render_facility_template,
)


def get_facility_dimension_fieldname() -> str | None:
	rows = frappe.get_all(
		"Accounting Dimension",
		filters={"document_type": "Facility", "disabled": 0},
		pluck="fieldname",
		limit=1,
	)
	if not rows:
		return None
	return (rows[0] or "").strip() or None


def facility_dimension_on_row(facility_name: str) -> dict[str, Any]:
	fn = get_facility_dimension_fieldname()
	if not fn or not facility_name:
		return {}
	return {fn: facility_name}


def _je_amount_pair(amount: Decimal, *, debit: bool) -> dict[str, str]:
	s = format(amount, "f")
	if debit:
		return {"debit_in_account_currency": s, "debit": s}
	return {"credit_in_account_currency": s, "credit": s}


def _merge_row_dims(facility_name: str, extra: dict[str, Any]) -> dict[str, Any]:
	row = dict(facility_dimension_on_row(facility_name))
	row.update(extra or {})
	return row


def _append_je_row(
	je,
	*,
	account: str,
	amount: Decimal,
	debit: bool,
	row_dims: dict[str, Any],
	user_remark: str | None = None,
):
	if amount <= 0:
		return
	payload = {"account": account, **_je_amount_pair(amount, debit=debit), **row_dims}
	if user_remark and frappe.get_meta("Journal Entry Account").has_field("user_remark"):
		payload["user_remark"] = user_remark
	je.append("accounts", payload)


def _planned_receipt_rows(principal: Decimal, profit: Decimal) -> list[tuple[Decimal, str]]:
	rows: list[tuple[Decimal, str]] = [(principal, "debit")]
	if profit > 0:
		rows.append((profit, "debit"))
	rows.append((principal + profit, "credit"))
	return rows


def _planned_repayment_rows(
	principal: Decimal, profit: Decimal, penalty: Decimal
) -> list[tuple[Decimal, str]]:
	total = principal + profit + penalty
	rows: list[tuple[Decimal, str]] = [(total, "credit")]
	if principal > 0:
		rows.append((principal, "debit"))
	if profit > 0:
		rows.append((profit, "debit"))
	if penalty > 0:
		rows.append((penalty, "debit"))
	return rows


def _apply_exact_je_planned(je_name: str, planned: list[tuple[Decimal, str]]) -> None:
	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabJournal Entry Account`
		WHERE parent = %s
		ORDER BY idx ASC
		""",
		(je_name,),
	)
	if len(rows) != len(planned):
		frappe.throw(
			frappe._("Journal Entry {0} row count {1} does not match planned lines {2}").format(
				je_name, len(rows), len(planned)
			)
		)
	total_debit = Decimal("0")
	total_credit = Decimal("0")
	for (row_name,), (amount, kind) in zip(rows, planned, strict=True):
		amount_str = format(amount, "f")
		if kind == "debit":
			total_debit += amount
			frappe.db.sql(
				"""
				UPDATE `tabJournal Entry Account`
				SET debit_in_account_currency = %s, debit = %s,
					credit_in_account_currency = 0, credit = 0
				WHERE name = %s
				""",
				(amount_str, amount_str, row_name),
			)
		else:
			total_credit += amount
			frappe.db.sql(
				"""
				UPDATE `tabJournal Entry Account`
				SET credit_in_account_currency = %s, credit = %s,
					debit_in_account_currency = 0, debit = 0
				WHERE name = %s
				""",
				(amount_str, amount_str, row_name),
			)
	total_str = format(max(total_debit, total_credit), "f")
	frappe.db.sql(
		"""
		UPDATE `tabJournal Entry`
		SET total_debit = %s, total_credit = %s, difference = 0
		WHERE name = %s
		""",
		(total_str, total_str, je_name),
	)


def _apply_exact_gl_planned(je_name: str, planned: list[tuple[Decimal, str]]) -> None:
	gl_rows = frappe.db.sql(
		"""
		SELECT name FROM `tabGL Entry`
		WHERE voucher_type = 'Journal Entry' AND voucher_no = %s AND is_cancelled = 0
		ORDER BY creation ASC, name ASC
		""",
		(je_name,),
	)
	if len(gl_rows) != len(planned):
		return
	for (row_name,), (amount, kind) in zip(gl_rows, planned, strict=True):
		amount_str = format(amount, "f")
		if kind == "debit":
			frappe.db.sql(
				"""
				UPDATE `tabGL Entry`
				SET debit = %s, credit = 0, debit_in_account_currency = %s, credit_in_account_currency = 0
				WHERE name = %s
				""",
				(amount_str, amount_str, row_name),
			)
		else:
			frappe.db.sql(
				"""
				UPDATE `tabGL Entry`
				SET credit = %s, debit = 0, credit_in_account_currency = %s, debit_in_account_currency = 0
				WHERE name = %s
				""",
				(amount_str, amount_str, row_name),
			)


def _sync_je_credit_to_debit_sum(je_name: str) -> None:
	total = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(debit_in_account_currency), 0)
		FROM `tabJournal Entry Account`
		WHERE parent = %s
		""",
		(je_name,),
	)[0][0]
	total_str = format(Decimal(str(total)), "f")
	for (row_name,) in frappe.db.sql(
		"""
		SELECT name FROM `tabJournal Entry Account`
		WHERE parent = %s AND credit_in_account_currency > 0
		""",
		(je_name,),
	):
		frappe.db.sql(
			"""
			UPDATE `tabJournal Entry Account`
			SET credit_in_account_currency = %s, credit = %s
			WHERE name = %s
			""",
			(total_str, total_str, row_name),
		)
	frappe.db.sql(
		"""
		UPDATE `tabJournal Entry`
		SET total_debit = %s, total_credit = %s, difference = 0
		WHERE name = %s
		""",
		(total_str, total_str, je_name),
	)


def _facility_receipt_amounts(facility) -> tuple[Decimal, Decimal]:
	principal = get_exact_currency_decimal("Facility", facility.name, "principal_amount")
	profit = get_exact_currency_decimal("Facility", facility.name, "profit_amount")
	return principal, profit


def create_and_submit_receipt_je(facility) -> str:
	if facility.receipt_journal_entry:
		frappe.throw(
			frappe._("Receipt Journal Entry already exists: {0}").format(facility.receipt_journal_entry),
			title=frappe._("Facility Receipt"),
		)
	if cint(facility.is_opening_facility):
		frappe.throw(
			frappe._("Opening / migrated facilities must not create a Receipt Journal Entry."),
			title=frappe._("Facility Receipt"),
		)
	principal, profit = _facility_receipt_amounts(facility)
	if principal <= 0:
		frappe.throw(frappe._("Principal amount must be positive to receive facility."))
	if profit > 0:
		resolve_account(
			"deferred_loan_interest_account",
			facility=facility,
			settings=get_facility_settings_doc(facility.company),
			required=True,
			required_label="Deferred Loan Interest Account",
		)

	settings = get_facility_settings_doc(facility.company)
	ctx = build_template_context(facility)
	remark_tpl = template_chain(
		facility_key="receipt_remarks_template",
		settings_key="default_receipt_remarks_template",
		facility=facility,
		settings=settings,
		default=DEFAULT_RECEIPT_REMARKS,
	)
	bank_row_tpl = template_chain(
		facility_key="",
		settings_key="default_receipt_bank_row_description_template",
		facility=None,
		settings=settings,
		default=DEFAULT_RECEIPT_BANK_ROW,
	)
	deferred_row_tpl = template_chain(
		facility_key="",
		settings_key="default_receipt_deferred_interest_row_description_template",
		facility=None,
		settings=settings,
		default=DEFAULT_RECEIPT_DEFERRED_ROW,
	)
	loan_row_tpl = template_chain(
		facility_key="",
		settings_key="default_receipt_loan_payable_row_description_template",
		facility=None,
		settings=settings,
		default=DEFAULT_RECEIPT_LOAN_ROW,
	)

	bank_acc = resolve_account(
		"bank_account",
		facility=facility,
		settings=settings,
		required=True,
		required_label="Bank Account",
	)
	loan_acc = resolve_account(
		"loan_payable_account",
		facility=facility,
		settings=settings,
		required=True,
		required_label="Loan Payable Account",
	)
	deferred_acc = resolve_account(
		"deferred_loan_interest_account",
		facility=facility,
		settings=settings,
		required=profit > 0,
		required_label="Deferred Loan Interest Account",
	)

	row_dims = _merge_row_dims(
		facility.name,
		dimensions_for_je_row(facility=facility, settings=settings),
	)

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Bank Entry"
	je.company = facility.company
	je.posting_date = facility.receive_date or facility.contract_date or frappe.utils.today()
	je.cheque_no = facility.name
	je.cheque_date = je.posting_date
	remark = render_facility_template(remark_tpl, ctx)
	je.user_remark = remark
	je.remark = remark

	_append_je_row(
		je,
		account=bank_acc,
		amount=principal,
		debit=True,
		row_dims=row_dims,
		user_remark=render_facility_template(bank_row_tpl, ctx),
	)
	if profit > 0:
		_append_je_row(
			je,
			account=deferred_acc,
			amount=profit,
			debit=True,
			row_dims=row_dims,
			user_remark=render_facility_template(deferred_row_tpl, ctx),
		)
	_append_je_row(
		je,
		account=loan_acc,
		amount=principal + profit,
		debit=False,
		row_dims=row_dims,
		user_remark=render_facility_template(loan_row_tpl, ctx),
	)

	planned = _planned_receipt_rows(principal, profit)
	je.insert(ignore_permissions=True)
	_sync_je_credit_to_debit_sum(je.name)
	je.reload()
	je.submit()
	_apply_exact_je_planned(je.name, planned)
	_apply_exact_gl_planned(je.name, planned)
	_validate_je_gl_dimensions(je.name, facility.name)
	return je.name


def _repayment_line_amounts(repayment) -> tuple[Decimal, Decimal, Decimal]:
	return (
		get_exact_currency_decimal("Facility Repayment", repayment.name, "principal_amount"),
		get_exact_currency_decimal("Facility Repayment", repayment.name, "profit_amount"),
		get_exact_currency_decimal("Facility Repayment", repayment.name, "penalty_amount"),
	)


def create_and_submit_repayment_je(repayment) -> str:
	facility = frappe.get_doc("Facility", repayment.facility)
	principal, profit, penalty = _repayment_line_amounts(repayment)
	total = principal + profit + penalty
	if total <= 0:
		frappe.throw(frappe._("Total payment amount must be greater than zero."))

	settings = get_facility_settings_doc(facility.company)
	if profit > 0:
		resolve_account(
			"deferred_loan_interest_account",
			repayment=repayment,
			facility=facility,
			settings=settings,
			required=True,
			required_label="Deferred Loan Interest Account",
		)
	if penalty > 0:
		resolve_account(
			"penalty_expense_account",
			repayment=repayment,
			facility=facility,
			settings=settings,
			required=True,
			required_label="Penalty Expense Account",
		)

	ctx = build_template_context(facility, repayment)
	if getattr(repayment, "repayment_remarks_template", None):
		remark_tpl = repayment.repayment_remarks_template
	else:
		remark_tpl = template_chain(
			facility_key="repayment_remarks_template",
			settings_key="default_repayment_remarks_template",
			facility=facility,
			settings=settings,
			default=DEFAULT_REPAYMENT_REMARKS,
		)
	bank_row_tpl = template_chain(
		facility_key="",
		settings_key="default_repayment_bank_row_description_template",
		facility=None,
		settings=settings,
		default=DEFAULT_REPAYMENT_BANK_ROW,
	)
	principal_row_tpl = template_chain(
		facility_key="",
		settings_key="default_repayment_principal_row_description_template",
		facility=None,
		settings=settings,
		default=DEFAULT_REPAYMENT_PRINCIPAL_ROW,
	)
	profit_row_tpl = template_chain(
		facility_key="",
		settings_key="default_repayment_profit_row_description_template",
		facility=None,
		settings=settings,
		default=DEFAULT_REPAYMENT_PROFIT_ROW,
	)
	penalty_row_tpl = template_chain(
		facility_key="",
		settings_key="default_repayment_penalty_row_description_template",
		facility=None,
		settings=settings,
		default=DEFAULT_REPAYMENT_PENALTY_ROW,
	)

	bank_acc = resolve_account(
		"bank_account",
		repayment=repayment,
		facility=facility,
		settings=settings,
		required=True,
		required_label="Bank Account",
	)
	loan_acc = resolve_account(
		"loan_payable_account",
		repayment=repayment,
		facility=facility,
		settings=settings,
		required=principal > 0,
		required_label="Loan Payable Account",
	)
	deferred_acc = resolve_account(
		"deferred_loan_interest_account",
		repayment=repayment,
		facility=facility,
		settings=settings,
		required=profit > 0,
		required_label="Deferred Loan Interest Account",
	)
	penalty_acc = resolve_account(
		"penalty_expense_account",
		repayment=repayment,
		facility=facility,
		settings=settings,
		required=penalty > 0,
		required_label="Penalty Expense Account",
	)

	row_dims = _merge_row_dims(
		facility.name,
		dimensions_for_je_row(repayment=repayment, facility=facility, settings=settings),
	)

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Bank Entry"
	je.company = repayment.company or facility.company
	je.posting_date = repayment.posting_date
	je.cheque_no = repayment.name
	je.cheque_date = repayment.posting_date
	remark = render_facility_template(remark_tpl, ctx) if "{" in remark_tpl else remark_tpl
	je.user_remark = remark
	je.remark = remark

	_append_je_row(
		je,
		account=bank_acc,
		amount=total,
		debit=False,
		row_dims=row_dims,
		user_remark=render_facility_template(bank_row_tpl, ctx),
	)
	if principal > 0:
		_append_je_row(
			je,
			account=loan_acc,
			amount=principal,
			debit=True,
			row_dims=row_dims,
			user_remark=render_facility_template(principal_row_tpl, ctx),
		)
	if profit > 0:
		_append_je_row(
			je,
			account=deferred_acc,
			amount=profit,
			debit=True,
			row_dims=row_dims,
			user_remark=render_facility_template(profit_row_tpl, ctx),
		)
	if penalty > 0:
		_append_je_row(
			je,
			account=penalty_acc,
			amount=penalty,
			debit=True,
			row_dims=row_dims,
			user_remark=render_facility_template(penalty_row_tpl, ctx),
		)

	planned = _planned_repayment_rows(principal, profit, penalty)
	je.insert(ignore_permissions=True)
	_sync_je_credit_to_debit_sum(je.name)
	je.reload()
	je.submit()
	_apply_exact_je_planned(je.name, planned)
	_apply_exact_gl_planned(je.name, planned)
	_validate_je_gl_dimensions(je.name, facility.name)
	return je.name


def cancel_journal_entry(je_name: str | None) -> None:
	if not je_name or not frappe.db.exists("Journal Entry", je_name):
		return
	je = frappe.get_doc("Journal Entry", je_name)
	if je.docstatus == 1:
		je.cancel()


def _validate_je_gl_dimensions(je_name: str, facility_name: str) -> None:
	fn = get_facility_dimension_fieldname()
	if not fn:
		return
	je = frappe.get_doc("Journal Entry", je_name)
	for row in je.accounts:
		val = getattr(row, fn, None)
		if val and val != facility_name:
			frappe.throw(
				frappe._("Journal Entry row {0} has unexpected Facility dimension {1!r}").format(
					row.idx, val
				)
			)
		if not val:
			frappe.throw(
				frappe._("Journal Entry row {0} missing Facility dimension on account {1}").format(
					row.idx, row.account
				)
			)
	missing = frappe.db.sql(
		f"""
		SELECT name FROM `tabGL Entry`
		WHERE voucher_type = 'Journal Entry' AND voucher_no = %s AND is_cancelled = 0
		  AND ({fn} IS NULL OR {fn} = '')
		LIMIT 1
		""",
		(je_name,),
	)
	if missing:
		frappe.throw(frappe._("GL Entry missing Facility dimension for Journal Entry {0}").format(je_name))


def refresh_facility_paid_fields(facility_name: str) -> None:
	bal = get_facility_balance_row(facility_name)
	updates = {
		"paid_principal_amount": bal["paid_principal"],
		"paid_profit_amount": bal["paid_profit"],
		"paid_penalty_amount": bal["paid_penalty"],
		"remaining_principal_amount": bal["remaining_principal"],
		"remaining_profit_amount": bal["remaining_profit"],
		"remaining_total_amount": bal["remaining_total"],
	}
	if frappe.db.get_value("Facility", facility_name, "receipt_journal_entry"):
		updates["received_amount"] = flt(bal["principal_amount"])
	frappe.db.set_value("Facility", facility_name, updates, update_modified=False)


def _apply_exact_repayment_je_amounts(
	je_name: str, principal: Decimal, profit: Decimal, penalty: Decimal
) -> None:
	_apply_exact_je_planned(je_name, _planned_repayment_rows(principal, profit, penalty))


def _apply_exact_repayment_gl_amounts(
	je_name: str, principal: Decimal, profit: Decimal, penalty: Decimal
) -> None:
	_apply_exact_gl_planned(je_name, _planned_repayment_rows(principal, profit, penalty))
