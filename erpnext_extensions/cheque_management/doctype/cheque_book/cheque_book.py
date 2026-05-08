from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


MAX_LEAVES_PER_BOOK = 5000


def recompute_cheque_book_summary(cheque_book_name: str | None) -> None:
	"""Recompute Cheque Book leaf counts and **status** from **Cheque Leaf** rows.

	Does not touch **generation_log**. Skips books in **Cancelled** status (admin override).

	Called after leaf insert/update/delete, after **Generate Leaves**, and from **Recalculate Counts**.
	"""
	if not cheque_book_name or not frappe.db.exists("Cheque Book", cheque_book_name):
		return

	cur_status = (frappe.db.get_value("Cheque Book", cheque_book_name, "status") or "").strip()
	if cur_status == "Cancelled":
		return

	rows = frappe.db.sql(
		"""
		SELECT `status`, COUNT(*) AS c
		FROM `tabCheque Leaf`
		WHERE `cheque_book` = %s
		GROUP BY `status`
		""",
		(cheque_book_name,),
		as_dict=True,
	)
	by: dict[str, int] = {}
	for r in rows or []:
		st = (r.get("status") or "").strip()
		by[st] = by.get(st, 0) + int(r.get("c") or 0)

	available = int(by.get("Available", 0))
	reserved = int(by.get("Reserved", 0))
	used = int(by.get("Used", 0))
	void = int(by.get("Void", 0))
	generated = int(sum(by.values()))

	if generated == 0:
		new_status = "Draft"
		available = reserved = used = void = 0
	elif available == generated:
		new_status = "Generated"
	elif available == 0:
		new_status = "Exhausted"
	else:
		new_status = "Partially Used"

	frappe.db.set_value(
		"Cheque Book",
		cheque_book_name,
		{
			"generated_leaves_count": generated,
			"available_leaves_count": available,
			"used_leaves_count": used,
			"reserved_leaves_count": reserved,
			"void_leaves_count": void,
			"status": new_status,
		},
		update_modified=False,
	)


@dataclass(frozen=True)
class GeneratedLeaf:
	sequence_no: int
	cheque_number: str


def _normalize_prefix(prefix: str | None) -> str:
	return (prefix or "").strip()


def _format_cheque_number(prefix: str, sequence_no: int, number_width: int | None) -> str:
	if number_width and int(number_width) > 0:
		num = str(int(sequence_no)).zfill(int(number_width))
	else:
		num = str(int(sequence_no))
	return f"{prefix}{num}"


def _validate_bank_account_company(bank_account: str, company: str) -> None:
	# Best-effort: Bank Account doctypes vary across ERPNext versions.
	if not bank_account or not company:
		return
	try:
		ba_company = frappe.db.get_value("Bank Account", bank_account, "company")
		if ba_company and ba_company != company:
			frappe.throw(
				frappe._("Bank Account {0} does not belong to Company {1}.").format(bank_account, company),
				title=frappe._("Cheque Book"),
			)
	except frappe.DoesNotExistError:
		# If Bank Account not found, core validation will handle.
		return


class ChequeBook(Document):
	def validate(self):
		self._validate_immutability_after_generation()
		self._validate_range_fields()
		_validate_bank_account_company(self.bank_account, self.company)

	def on_trash(self):
		# Avoid casual deletion when leaves already exist.
		if frappe.db.exists("Cheque Leaf", {"cheque_book": self.name}):
			frappe.throw(
				frappe._("Cannot delete this Cheque Book because cheque leaves already exist."),
				title=frappe._("Cheque Book"),
			)

	def _validate_range_fields(self) -> None:
		if (self.generation_mode or "").strip() != "prefix_plus_sequence":
			frappe.throw(frappe._("Only generation_mode = prefix_plus_sequence is supported in v1."))

		if self.start_number is None or self.end_number is None:
			return

		start = int(self.start_number)
		end = int(self.end_number)
		if end < start:
			frappe.throw(frappe._("End Number must be greater than or equal to Start Number."), title=frappe._("Cheque Book"))

		count = (end - start) + 1
		if count > MAX_LEAVES_PER_BOOK:
			frappe.throw(
				frappe._("Cheque leaf range is too large ({0}). Maximum allowed is {1}.").format(count, MAX_LEAVES_PER_BOOK),
				title=frappe._("Cheque Book"),
			)

		# number_width is optional. Treat blank/null/0 as "no padding".
		if self.number_width is not None and str(self.number_width).strip():
			w = int(self.number_width)
			if w < 0:
				frappe.throw(frappe._("Number Width cannot be negative."), title=frappe._("Cheque Book"))
			if w > 0 and w > 32:
				frappe.throw(frappe._("Number Width must be between 1 and 32 when set."), title=frappe._("Cheque Book"))

	def _validate_immutability_after_generation(self) -> None:
		"""Once leaves exist, generation-defining fields become immutable."""
		if self.is_new():
			return

		# Server-side source of truth: leaves existing for this book.
		if not frappe.db.exists("Cheque Leaf", {"cheque_book": self.name}):
			return

		before = self.get_doc_before_save()
		if not before:
			return

		locked_fields = [
			"company",
			"bank_account",
			"generation_mode",
			"prefix",
			"start_number",
			"end_number",
			"number_width",
		]

		changed = []
		for fn in locked_fields:
			if str(getattr(before, fn, "") or "") != str(getattr(self, fn, "") or ""):
				changed.append(fn)

		if changed:
			frappe.throw(
				frappe._("Generated cheque books cannot change company, bank account, or numbering fields."),
				title=frappe._("Cheque Book"),
			)

	@frappe.whitelist()
	def generate_leaves(self):
		"""Generate Cheque Leaf records for this book (Phase 2)."""
		self.check_permission("write")
		if self.docstatus != 0:
			frappe.throw(frappe._("Leaves can only be generated while Cheque Book is in Draft."))

		# Re-run validations with latest values.
		self._validate_range_fields()
		_validate_bank_account_company(self.bank_account, self.company)

		if frappe.db.exists("Cheque Leaf", {"cheque_book": self.name}):
			frappe.throw(
				frappe._("Cheque leaves already exist for this Cheque Book. Generation is not allowed again."),
				title=frappe._("Cheque Book"),
			)

		prefix = _normalize_prefix(self.prefix)
		start = int(self.start_number)
		end = int(self.end_number)
		width = int(self.number_width) if (self.number_width is not None and str(self.number_width).strip()) else None
		if width is not None and width <= 0:
			width = None

		to_create: list[GeneratedLeaf] = []
		for seq in range(start, end + 1):
			to_create.append(GeneratedLeaf(sequence_no=seq, cheque_number=_format_cheque_number(prefix, seq, width)))

		# Uniqueness: cheque_number must not already exist for same company + bank_account.
		# We check in chunks to keep query size reasonable.
		existing = set()
		chunk_size = 500
		for i in range(0, len(to_create), chunk_size):
			chunk = to_create[i : i + chunk_size]
			nums = [x.cheque_number for x in chunk]
			rows = frappe.get_all(
				"Cheque Leaf",
				filters={"company": self.company, "bank_account": self.bank_account, "cheque_number": ["in", nums]},
				pluck="cheque_number",
			)
			existing.update(rows or [])

		if existing:
			sample = ", ".join(sorted(list(existing))[:10])
			frappe.throw(
				frappe._(
					"Cannot generate leaves because these cheque numbers already exist for this Company/Bank Account: {0}"
				).format(sample),
				title=frappe._("Cheque Book"),
			)

		# Create leaves (suppress per-leaf book recalculation until batch completes).
		frappe.flags.skip_cheque_book_recalculate = True
		try:
			for x in to_create:
				leaf = frappe.new_doc("Cheque Leaf")
				leaf.company = self.company
				leaf.bank_account = self.bank_account
				leaf.cheque_book = self.name
				leaf.cheque_number = x.cheque_number
				leaf.sequence_no = x.sequence_no
				leaf.status = "Available"
				leaf.insert(ignore_permissions=True)
		finally:
			frappe.flags.skip_cheque_book_recalculate = False

		recompute_cheque_book_summary(self.name)
		self.db_set(
			"generation_log",
			f"Generated {len(to_create)} leaves on {now_datetime().strftime('%Y-%m-%d %H:%M:%S')}.",
			update_modified=False,
		)

		return {
			"created": len(to_create),
			"status": frappe.db.get_value("Cheque Book", self.name, "status"),
		}

	@frappe.whitelist()
	def recalculate_counts(self):
		"""Recompute leaf counts and book status from **Cheque Leaf** (manual repair / refresh)."""
		self.check_permission("write")
		if (self.status or "").strip() == "Cancelled":
			frappe.msgprint(
				frappe._("This Cheque Book is **Cancelled**; counts and status are left unchanged."),
				title=frappe._("Cheque Book"),
				indicator="orange",
			)
			return {
				"generated_leaves_count": self.generated_leaves_count,
				"available_leaves_count": self.available_leaves_count,
				"used_leaves_count": self.used_leaves_count,
				"reserved_leaves_count": getattr(self, "reserved_leaves_count", None) or 0,
				"void_leaves_count": getattr(self, "void_leaves_count", None) or 0,
				"status": self.status,
				"skipped": True,
			}
		recompute_cheque_book_summary(self.name)
		self.reload()
		return {
			"generated_leaves_count": self.generated_leaves_count,
			"available_leaves_count": self.available_leaves_count,
			"used_leaves_count": self.used_leaves_count,
			"reserved_leaves_count": self.reserved_leaves_count,
			"void_leaves_count": self.void_leaves_count,
			"status": self.status,
		}

