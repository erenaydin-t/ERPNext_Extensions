# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from erpnext_extensions.facility_management.facility_accounting import (
	cancel_journal_entry,
	create_and_submit_repayment_je,
	refresh_facility_paid_fields,
)
from erpnext_extensions.facility_management.facility_accounting import (
	preview_repayment_journal_entry as build_repayment_je_preview,
)
from erpnext_extensions.facility_management.facility_balances import get_facility_balance_row
from erpnext_extensions.facility_management.facility_monetary import (
	FACILITY_REPAYMENT_CURRENCY_FIELDS,
	parse_facility_amount,
	persist_exact_currency_fields,
)
from erpnext_extensions.facility_management.facility_settings_doc import (
	get_facility_settings_doc,
	resolve_account,
	validate_repayment_je_prerequisites,
)

_REPAYMENT_ACCOUNT_FIELDS = (
	"bank_account",
	"loan_payable_account",
	"deferred_loan_interest_account",
	"interest_expense_account",
	"penalty_expense_account",
)


class FacilityRepayment(Document):
	def _repayment_amounts_decimal(self):
		return {fn: parse_facility_amount(self.get(fn)) for fn in FACILITY_REPAYMENT_CURRENCY_FIELDS}

	def _recalculate_total_payment(self) -> None:
		amounts = self._repayment_amounts_decimal()
		total = sum(amounts.values())
		self.total_payment_amount = flt(total)

	def _capture_exact_currency(self) -> None:
		self._exact_currency = {}
		flag_exact = getattr(self.flags, "facility_exact_currency", None) or {}
		for fn in FACILITY_REPAYMENT_CURRENCY_FIELDS:
			if fn in flag_exact:
				self._exact_currency[fn] = flag_exact[fn]
				continue
			val = self.get(fn)
			if val not in (None, "") and isinstance(val, str):
				self._exact_currency[fn] = val

	def _exact_persist_fields(self) -> dict[str, object]:
		fields = dict(getattr(self, "_exact_currency", None) or {})
		if not fields:
			fields = {fn: self.get(fn) for fn in FACILITY_REPAYMENT_CURRENCY_FIELDS}
		total = sum(
			parse_facility_amount(fields.get(fn, self.get(fn))) for fn in FACILITY_REPAYMENT_CURRENCY_FIELDS
		)
		fields["total_payment_amount"] = format(total, "f")
		return fields

	def _persist_amount_columns(self) -> None:
		if self.is_new():
			return
		persist_exact_currency_fields("Facility Repayment", self.name, self._exact_persist_fields())

	def _fill_empty_repayment_accounts(self, facility, settings) -> None:
		for fn in _REPAYMENT_ACCOUNT_FIELDS:
			if self.get(fn):
				continue
			val = resolve_account(fn, repayment=self, facility=facility, settings=settings, required=False)
			if val:
				self.set(fn, val)

	def before_save(self):
		self._capture_exact_currency()
		self._recalculate_total_payment()

	def validate(self):
		self._capture_exact_currency()
		self._recalculate_total_payment()
		if flt(self.total_payment_amount) <= 0:
			frappe.throw(_("Enter at least one of principal, profit, or penalty amount."))
		facility = frappe.get_doc("Facility", self.facility)
		if facility.status != "Active":
			frappe.throw(_("Facility must be Active to record a repayment."))
		bal = get_facility_balance_row(facility)
		if flt(self.principal_amount) > flt(bal["remaining_principal"]):
			frappe.throw(_("Principal amount exceeds remaining principal."))
		if flt(self.profit_amount) > flt(bal["remaining_profit"]):
			frappe.throw(_("Profit amount exceeds remaining profit."))
		settings = get_facility_settings_doc(facility.company)
		self._fill_empty_repayment_accounts(facility, settings)
		validate_repayment_je_prerequisites(
			self,
			facility,
			settings,
			principal=self.principal_amount,
			profit=self.profit_amount,
			penalty=self.penalty_amount,
		)

	def after_insert(self):
		persist_exact_currency_fields("Facility Repayment", self.name, self._exact_persist_fields())

	def on_update(self):
		if self.docstatus == 0:
			self._persist_amount_columns()

	def on_submit(self):
		persist_exact_currency_fields("Facility Repayment", self.name, self._exact_persist_fields())
		je = create_and_submit_repayment_je(self)
		self.db_set("journal_entry", je, update_modified=False)
		refresh_facility_paid_fields(self.facility)

	def on_cancel(self):
		cancel_journal_entry(self.journal_entry)
		self.db_set("journal_entry", None, update_modified=False)
		refresh_facility_paid_fields(self.facility)


@frappe.whitelist()
def preview_repayment_journal_entry(doc=None):
	"""Build repayment JE lines without submitting (same builder as on_submit)."""
	if isinstance(doc, str):
		doc = frappe.parse_json(doc)
	if not doc:
		frappe.throw(_("Document required for preview."))
	payload = dict(doc)
	payload.setdefault("doctype", "Facility Repayment")
	repayment = frappe.get_doc(payload)
	return build_repayment_je_preview(repayment)
