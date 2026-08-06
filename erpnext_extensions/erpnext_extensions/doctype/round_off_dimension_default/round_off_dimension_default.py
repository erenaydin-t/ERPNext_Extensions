# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


FORBIDDEN_ROUND_OFF_DIMENSIONS = frozenset({"cost_center", "account"})


class RoundOffDimensionDefault(Document):
	def validate(self):
		self._normalize_dimension()
		self._validate_forbidden()
		self._validate_against_accounting_dimension()
		self._validate_default_value()
		self._validate_unique_on_parent()

	def _validate_unique_on_parent(self):
		if not self.parent or not self.accounting_dimension:
			return
		if getattr(self, "parent_doc", None):
			matches = [
				row
				for row in (self.parent_doc.get("round_off_dimension_defaults") or [])
				if (row.accounting_dimension or "").strip() == self.accounting_dimension
			]
			if len(matches) > 1:
				frappe.throw(
					_("Accounting Dimension {0} is duplicated in Round Off Dimension Defaults.").format(
						frappe.bold(self.accounting_dimension)
					),
					title=_("Duplicate Round Off Dimension"),
				)
			return

		filters = {
			"parent": self.parent,
			"parenttype": "Company",
			"accounting_dimension": self.accounting_dimension,
		}
		if self.name:
			filters["name"] = ("!=", self.name)
		if frappe.db.exists("Round Off Dimension Default", filters):
			frappe.throw(
				_("Accounting Dimension {0} is duplicated in Round Off Dimension Defaults.").format(
					frappe.bold(self.accounting_dimension)
				),
				title=_("Duplicate Round Off Dimension"),
			)

	def _normalize_dimension(self):
		fieldname = (self.accounting_dimension or "").strip()
		self.accounting_dimension = fieldname

	def _validate_forbidden(self):
		if self.accounting_dimension in FORBIDDEN_ROUND_OFF_DIMENSIONS:
			frappe.throw(
				_(
					"Round Off Dimension Defaults must not include {0}. "
					"Use Company Round Off Cost Center / Round Off Account instead."
				).format(frappe.bold(self.accounting_dimension)),
				title=_("Invalid Round Off Dimension"),
			)

	def _validate_against_accounting_dimension(self):
		if not self.accounting_dimension:
			frappe.throw(_("Accounting Dimension fieldname is required."))

		row = frappe.db.get_value(
			"Accounting Dimension",
			{"fieldname": self.accounting_dimension, "disabled": 0},
			["name", "document_type", "fieldname", "disabled"],
			as_dict=True,
		)
		if not row:
			# Also allow match by name when fieldname stored equals name-derived field
			row = frappe.db.get_value(
				"Accounting Dimension",
				{"name": self.accounting_dimension, "disabled": 0},
				["name", "document_type", "fieldname", "disabled"],
				as_dict=True,
			)
			if row:
				self.accounting_dimension = row.fieldname

		if not row:
			frappe.throw(
				_(
					"Accounting Dimension fieldname {0} is not an enabled Accounting Dimension."
				).format(frappe.bold(self.accounting_dimension)),
				title=_("Invalid Accounting Dimension"),
			)

		self.reference_doctype = row.document_type
		if not self.reference_doctype:
			frappe.throw(
				_("Accounting Dimension {0} has no document type.").format(frappe.bold(row.name))
			)

	def _validate_default_value(self):
		if not self.default_value:
			frappe.throw(_("Default Value is required."))
		if not self.reference_doctype:
			return
		if not frappe.db.exists(self.reference_doctype, self.default_value):
			frappe.throw(
				_("{0} {1} does not exist.").format(
					frappe.bold(self.reference_doctype), frappe.bold(self.default_value)
				),
				title=_("Invalid Default Value"),
			)
		meta = frappe.get_meta(self.reference_doctype)
		if meta.has_field("disabled") and cint(
			frappe.db.get_value(self.reference_doctype, self.default_value, "disabled")
		):
			frappe.throw(
				_("{0} {1} is disabled.").format(
					frappe.bold(self.reference_doctype), frappe.bold(self.default_value)
				),
				title=_("Disabled Default Value"),
			)
		if meta.has_field("company") and self.parent:
			value_company = frappe.db.get_value(
				self.reference_doctype, self.default_value, "company"
			)
			if value_company and value_company != self.parent:
				frappe.throw(
					_("{0} {1} belongs to Company {2}, not {3}.").format(
						frappe.bold(self.reference_doctype),
						frappe.bold(self.default_value),
						frappe.bold(value_company),
						frappe.bold(self.parent),
					),
					title=_("Company Mismatch"),
				)
