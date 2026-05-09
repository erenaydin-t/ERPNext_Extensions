from __future__ import annotations

import frappe
from frappe.model.document import Document

from erpnext_extensions.cheque_management.doctype.cheque_book.cheque_book import recompute_cheque_book_summary


class ChequeLeaf(Document):
	def validate(self):
		self._validate_immutable_master_fields()
		self._validate_status_safety()
		self._validate_sayad_number_uniqueness()

		# Enforce uniqueness by check (in addition to any future DB index).
		if self.company and self.bank_account and self.cheque_number:
			exists = frappe.db.exists(
				"Cheque Leaf",
				{
					"name": ["!=", self.name],
					"company": self.company,
					"bank_account": self.bank_account,
					"cheque_number": self.cheque_number,
				},
			)
			if exists:
				frappe.throw(
					frappe._("Cheque Number {0} already exists for this Company and Bank Account.").format(self.cheque_number),
					title=frappe._("Cheque Leaf"),
				)

	def _validate_immutable_master_fields(self) -> None:
		"""Generated master fields must not be edited after insert."""
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		locked_fields = ["company", "bank_account", "cheque_book", "cheque_number", "sequence_no"]
		changed = []
		for fn in locked_fields:
			if str(getattr(before, fn, "") or "") != str(getattr(self, fn, "") or ""):
				changed.append(fn)
		if changed:
			frappe.throw(
				frappe._("Generated cheque leaf identity fields cannot be changed."),
				title=frappe._("Cheque Leaf"),
			)

	def _validate_status_safety(self) -> None:
		"""Prevent manual status changes that break lifecycle safety."""
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		prev = (before.status or "").strip()
		cur = (self.status or "").strip()
		# Hard blocks required by spec:
		# - Used -> Available / Reserved
		# - Void -> Available / Reserved
		if prev in ("Used", "Void") and cur in ("Available", "Reserved") and cur != prev:
			frappe.throw(
				frappe._("Cannot change status from {0} to {1}.").format(prev, cur),
				title=frappe._("Cheque Leaf"),
			)

	def _validate_sayad_number_uniqueness(self) -> None:
		"""Optional constraint: Sayad Number should not duplicate within a company."""
		sayad = (getattr(self, "sayad_number", None) or "").strip()
		company = (getattr(self, "company", None) or "").strip()
		if not sayad or not company:
			return
		exists = frappe.db.exists(
			"Cheque Leaf",
			{
				"name": ["!=", self.name],
				"company": company,
				"sayad_number": sayad,
			},
		)
		if exists:
			frappe.throw(
				frappe._("Sayad Number {0} already exists for company {1}.").format(sayad, company),
				title=frappe._("Cheque Leaf"),
			)

	def after_insert(self):
		self._request_cheque_book_recompute()

	def on_update(self):
		self._request_cheque_book_recompute()

	def on_trash(self):
		# Used/Void leaves should not be deleted.
		if (self.status or "").strip() in ("Used", "Void"):
			frappe.throw(
				frappe._("Cannot delete a Cheque Leaf with status {0}.").format(self.status),
				title=frappe._("Cheque Leaf"),
			)
		book = (self.cheque_book or "").strip()
		if book:
			# Row is still present during **on_trash**; recompute after commit so counts exclude this leaf.
			frappe.db.after_commit.add(lambda b=book: recompute_cheque_book_summary(b))

	def _request_cheque_book_recompute(self) -> None:
		if frappe.flags.get("skip_cheque_book_recalculate"):
			return
		book = (self.cheque_book or "").strip()
		if book:
			recompute_cheque_book_summary(book)

