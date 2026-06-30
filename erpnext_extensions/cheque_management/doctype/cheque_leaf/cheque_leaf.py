from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from erpnext_extensions.cheque_management.doctype.cheque_book.cheque_book import recompute_cheque_book_summary

_VOID_ROLES = frozenset({"Accounts Manager", "System Manager"})


def user_may_void_cheque_leaf(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(_VOID_ROLES & set(frappe.get_roles(user)))


@frappe.whitelist()
def void_cheque_leaf(leaf_name: str, reason: str, void_attachment: str | None = None) -> dict:
	"""Mark a cheque leaf as void/spoiled with audit fields."""
	if not user_may_void_cheque_leaf():
		frappe.throw(_("Not permitted to void cheque leaf."), title=_("Cheque Leaf"))

	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Void reason is required."), title=_("Cheque Leaf"))

	leaf_name = (leaf_name or "").strip()
	if not leaf_name or not frappe.db.exists("Cheque Leaf", leaf_name):
		frappe.throw(_("Cheque Leaf {0} does not exist.").format(leaf_name), title=_("Cheque Leaf"))

	doc = frappe.get_doc("Cheque Leaf", leaf_name)
	linked_pdc = (doc.linked_post_dated_cheque or "").strip()
	if linked_pdc:
		frappe.throw(
			_("This cheque leaf is linked to Post Dated Cheque {0} and cannot be voided.").format(linked_pdc),
			title=_("Cheque Leaf"),
		)

	if (doc.reserved_by_pdc or "").strip():
		frappe.throw(
			_("This Cheque Leaf is reserved by Post Dated Cheque {0} and cannot be voided.").format(
				doc.reserved_by_pdc
			),
			title=_("Cheque Leaf"),
		)

	status = (doc.status or "").strip()
	if status == "Void":
		frappe.throw(_("Cheque Leaf is already void."), title=_("Cheque Leaf"))
	if status != "Available":
		frappe.throw(_("Only available cheque leaves can be voided."), title=_("Cheque Leaf"))

	frappe.flags.void_cheque_leaf = True
	doc.status = "Void"
	doc.void_reason = reason
	doc.voided_on = now_datetime()
	doc.voided_by = frappe.session.user
	if void_attachment:
		doc.void_attachment = void_attachment
	doc.reserved_by_pdc = None
	doc.reserved_on = None
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"name": doc.name,
		"status": doc.status,
		"void_reason": doc.void_reason,
		"voided_on": str(doc.voided_on) if doc.voided_on else None,
		"voided_by": doc.voided_by,
	}


class ChequeLeaf(Document):
	def validate(self):
		self._validate_immutable_master_fields()
		self._validate_status_safety()
		self._validate_void_fields()
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
					frappe._("Cheque Number {0} already exists for this Company and Bank Account.").format(
						self.cheque_number
					),
					title=frappe._("Cheque Leaf"),
				)

	def _validate_void_fields(self) -> None:
		status = (self.status or "").strip()
		reason = (self.void_reason or "").strip()
		if status == "Void":
			if not reason:
				frappe.throw(_("Void Reason is required when status is Void."), title=_("Cheque Leaf"))
			if not self.voided_on:
				frappe.throw(_("Voided On is required when status is Void."), title=_("Cheque Leaf"))
			if not (self.voided_by or "").strip():
				frappe.throw(_("Voided By is required when status is Void."), title=_("Cheque Leaf"))
			return
		# Non-void: void audit fields must stay empty (unless system void from PDC cancel sets flag).
		if frappe.flags.get("void_cheque_leaf") or frappe.flags.get("skip_cheque_leaf_void_field_guard"):
			return
		for fn in ("void_reason", "voided_on", "voided_by", "void_attachment"):
			if getattr(self, fn, None) not in (None, ""):
				frappe.throw(
					_("Field {0} can only be set when Cheque Leaf status is Void.").format(fn),
					title=_("Cheque Leaf"),
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
		if prev == cur:
			return
		if frappe.flags.get("void_cheque_leaf"):
			if prev == "Available" and cur == "Void":
				return
		# Direct UI edit to Void without void_cheque_leaf method.
		if cur == "Void" and not frappe.flags.get("void_cheque_leaf"):
			frappe.throw(
				_("Use the Void Cheque Leaf action to mark a leaf as void."),
				title=_("Cheque Leaf"),
			)
		# Hard blocks required by spec:
		if prev == "Void" and cur in ("Available", "Reserved", "Used"):
			frappe.throw(
				frappe._("Cannot change status from {0} to {1}.").format(prev, cur),
				title=_("Cheque Leaf"),
			)
		if prev in ("Used", "Void") and cur in ("Available", "Reserved") and cur != prev:
			frappe.throw(
				frappe._("Cannot change status from {0} to {1}.").format(prev, cur),
				title=_("Cheque Leaf"),
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
