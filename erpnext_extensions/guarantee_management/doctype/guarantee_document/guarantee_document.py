# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT. See LICENSE file for details.

"""Custody and lifecycle tracking for guarantee/collateral documents.

This DocType must never create accounting documents (Journal Entry, Payment Entry, GL, invoices).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class GuaranteeDocument(Document):
	def before_validate(self) -> None:
		if self.company and not self.currency:
			self.currency = frappe.db.get_value("Company", self.company, "default_currency")

	def validate(self) -> None:
		self._validate_required_core()
		self._normalize_party_fields()
		self._validate_party()
		self._validate_issuing_bank()
		self._validate_amount()
		self._validate_document_no()
		self._validate_status_dates()
		self._validate_date_order()
		self._validate_no_duplicate_active()

	def _validate_required_core(self) -> None:
		if not self.company:
			frappe.throw(_("Company is required."), title=_("Guarantee Document"))
		if not self.guarantee_direction:
			frappe.throw(_("Guarantee Direction is required."), title=_("Guarantee Document"))
		if not self.guarantee_type:
			frappe.throw(_("Guarantee Type is required."), title=_("Guarantee Document"))

	def _normalize_party_fields(self) -> None:
		pt = (self.party_type or "").strip()
		if pt == "Other":
			if self.party:
				frappe.throw(
					_("Party link must be empty when Party Type is Other. Use Other Party Name."),
					title=_("Guarantee Document"),
				)
		else:
			self.other_party_name = None

	def _validate_party(self) -> None:
		pt = (self.party_type or "").strip()
		if pt == "Other":
			if not (self.other_party_name or "").strip():
				frappe.throw(
					_("Other Party Name is required when Party Type is Other."), title=_("Guarantee Document")
				)
		else:
			if not self.party:
				frappe.throw(
					_("Party is required when Party Type is not Other."), title=_("Guarantee Document")
				)

	def _validate_issuing_bank(self) -> None:
		"""Issuing Bank is required for Bank Guarantee only (server-enforced).

		Does not depend on party_type. Never auto-copied from Party.
		"""
		if (self.guarantee_type or "").strip() != "Bank Guarantee":
			return
		if not (self.issuing_bank or "").strip():
			frappe.throw(
				_("Issuing Bank is required when Guarantee Type is Bank Guarantee."),
				title=_("Guarantee Document"),
			)

	def _validate_amount(self) -> None:
		if self.amount is None or self.amount == "":
			return
		if flt(self.amount) <= 0:
			frappe.throw(_("Amount must be greater than zero if set."), title=_("Guarantee Document"))

	def _validate_document_no(self) -> None:
		st = (self.status or "").strip()
		if st and st != "Draft":
			if not (self.document_no or "").strip():
				frappe.throw(
					_("Document No is required when Status is not Draft."),
					title=_("Guarantee Document"),
				)

	def _validate_status_dates(self) -> None:
		st = (self.status or "").strip()
		direction = (self.guarantee_direction or "").strip()

		if st == "Active":
			if direction == "Received":
				if not self.received_date:
					frappe.throw(
						_("Received Date is required when Status is Active for a Received guarantee."),
						title=_("Guarantee Document"),
					)
			elif direction == "Issued":
				if not self.issued_date:
					frappe.throw(
						_("Issued Date is required when Status is Active for an Issued guarantee."),
						title=_("Guarantee Document"),
					)

		if st == "Returned" and direction == "Received":
			if not self.returned_date:
				frappe.throw(
					_("Returned Date is required when Status is Returned for a Received guarantee."),
					title=_("Guarantee Document"),
				)

		if st == "Released" and direction == "Issued":
			if not self.released_date:
				frappe.throw(
					_("Released Date is required when Status is Released for an Issued guarantee."),
					title=_("Guarantee Document"),
				)

		if st == "Returned" and direction == "Issued":
			if not self.returned_date:
				frappe.throw(
					_("Returned Date is required when Status is Returned for an Issued guarantee."),
					title=_("Guarantee Document"),
				)

	def _validate_date_order(self) -> None:
		def _d(d):
			return getdate(d) if d else None

		doc_dt = _d(self.document_date)
		exp_dt = _d(self.expiry_date)
		if doc_dt and exp_dt and exp_dt < doc_dt:
			frappe.throw(
				_("Expiry Date cannot be before Document Date."),
				title=_("Guarantee Document"),
			)

		ret_dt = _d(self.returned_date)
		rel_dt = _d(self.released_date)
		rec_dt = _d(self.received_date)
		iss_dt = _d(self.issued_date)

		direction = (self.guarantee_direction or "").strip()

		if ret_dt:
			if direction == "Received" and rec_dt and ret_dt < rec_dt:
				frappe.throw(
					_("Returned Date cannot be before Received Date."),
					title=_("Guarantee Document"),
				)
			if direction == "Issued" and iss_dt and ret_dt < iss_dt:
				frappe.throw(
					_("Returned Date cannot be before Issued Date."),
					title=_("Guarantee Document"),
				)

		if rel_dt and iss_dt and rel_dt < iss_dt:
			frappe.throw(
				_("Released Date cannot be before Issued Date."),
				title=_("Guarantee Document"),
			)

	def _validate_no_duplicate_active(self) -> None:
		if (self.status or "").strip() != "Active":
			return
		doc_no = (self.document_no or "").strip()
		if not doc_no:
			return

		filters: dict = {
			"company": self.company,
			"guarantee_direction": self.guarantee_direction,
			"guarantee_type": self.guarantee_type,
			"document_no": doc_no,
			"status": "Active",
		}

		if (self.party_type or "").strip() == "Other":
			filters["party_type"] = "Other"
			filters["other_party_name"] = (self.other_party_name or "").strip()
		else:
			filters["party_type"] = self.party_type
			filters["party"] = self.party

		existing = frappe.get_all(
			"Guarantee Document",
			filters=filters,
			pluck="name",
			limit=5,
		)
		existing = [n for n in existing if n != self.name]
		if existing:
			frappe.throw(
				_(
					"Another Active guarantee already exists for this Company, direction, type, document number, and party ({0})."
				).format(existing[0]),
				title=_("Duplicate Active Guarantee"),
			)
