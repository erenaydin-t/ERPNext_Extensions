from __future__ import annotations

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# Legacy PDC Allocation.allocation_type → allocation_mode (strict: no other values allowed).
_LEGACY_ALLOCATION_TYPE_TO_MODE = {
	"Against Invoice": "direct_settlement",
	"Payment Request": "direct_settlement",
	"Other Settlement": "direct_settlement",
	"Advance": "advance",
}


def execute():
	"""Schema/data migration for Advance PDC v1 (Task 1).

	- PDC Allocation: migrate ``allocated_amount`` / ``allocation_type`` → ``amount`` / ``allocation_mode`` (strict legacy mapping).
	- PDC Invoice Application: rename legacy ``currency`` → ``invoice_currency`` if present.
	- Purchase Invoice / Sales Invoice: Custom Field ``pdc_invoice_applications`` (fail if incompatible existing field).
	"""

	_migrate_pdc_allocation_columns()
	_migrate_pdc_invoice_application_invoice_currency_field()
	_ensure_invoice_pdc_application_fields()


def _migrate_pdc_allocation_columns():
	table = "tabPDC Allocation"
	has_allocated = frappe.db.has_column("PDC Allocation", "allocated_amount")
	has_amount = frappe.db.has_column("PDC Allocation", "amount")
	has_old_type = frappe.db.has_column("PDC Allocation", "allocation_type")
	has_mode = frappe.db.has_column("PDC Allocation", "allocation_mode")

	if has_allocated and has_amount:
		frappe.db.sql(
			f"""
			UPDATE `{table}`
			SET `amount` = COALESCE(`allocated_amount`, 0)
			WHERE ( `amount` IS NULL OR `amount` = 0 ) AND COALESCE(`allocated_amount`, 0) != 0
			"""
		)
		frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `allocated_amount`")
	elif has_allocated and not has_amount:
		frappe.db.sql_ddl(
			f"ALTER TABLE `{table}` CHANGE COLUMN `allocated_amount` `amount` DECIMAL(21,9) NOT NULL DEFAULT 0"
		)

	if not has_old_type:
		return

	if has_mode:
		_map_legacy_allocation_type_then_drop(table)
	else:
		frappe.db.sql_ddl(
			f"ALTER TABLE `{table}` CHANGE COLUMN `allocation_type` `allocation_mode` VARCHAR(140)"
		)
		_map_allocation_mode_values_after_rename(table)


def _map_legacy_allocation_type_then_drop(table: str):
	"""``allocation_type`` and ``allocation_mode`` columns both exist: map then drop ``allocation_type``."""

	rows = frappe.db.sql(
		f"SELECT `name`, `allocation_type`, `allocation_mode` FROM `{table}`",
		as_dict=True,
	)
	for row in rows:
		name = row["name"]
		raw_type = row.get("allocation_type")
		atype = (raw_type or "").strip()
		existing_mode = (row.get("allocation_mode") or "").strip()

		if atype:
			if atype not in _LEGACY_ALLOCATION_TYPE_TO_MODE:
				frappe.throw(
					_(
						"Migration stopped: unknown legacy `allocation_type` {0!r} on PDC Allocation {1}. "
						"Allowed legacy values: {2}. Fix or extend migration before continuing."
					).format(atype, name, ", ".join(sorted(_LEGACY_ALLOCATION_TYPE_TO_MODE)))
				)
			frappe.db.set_value(
				"PDC Allocation",
				name,
				"allocation_mode",
				_LEGACY_ALLOCATION_TYPE_TO_MODE[atype],
				update_modified=False,
			)
		elif not existing_mode:
			frappe.throw(
				_(
					"Migration stopped: PDC Allocation {0} has empty legacy `allocation_type` and empty `allocation_mode`."
				).format(name)
			)

	frappe.db.sql_ddl(f"ALTER TABLE `{table}` DROP COLUMN `allocation_type`")


def _map_allocation_mode_values_after_rename(table: str):
	"""Column was renamed from ``allocation_type`` to ``allocation_mode``; cell values are still legacy labels."""

	rows = frappe.db.sql(f"SELECT `name`, `allocation_mode` FROM `{table}`", as_dict=True)
	for row in rows:
		name = row["name"]
		val = (row.get("allocation_mode") or "").strip()
		if not val:
			frappe.throw(
				_("Migration stopped: PDC Allocation {0} has empty `allocation_mode` after rename.").format(
					name
				)
			)
		if val not in _LEGACY_ALLOCATION_TYPE_TO_MODE:
			frappe.throw(
				_(
					"Migration stopped: unknown value {0!r} in `allocation_mode` (from legacy allocation_type) on PDC Allocation {1}. "
					"Allowed legacy values: {2}."
				).format(val, name, ", ".join(sorted(_LEGACY_ALLOCATION_TYPE_TO_MODE)))
			)
		frappe.db.set_value(
			"PDC Allocation",
			name,
			"allocation_mode",
			_LEGACY_ALLOCATION_TYPE_TO_MODE[val],
			update_modified=False,
		)


def _migrate_pdc_invoice_application_invoice_currency_field():
	"""Rename ``currency`` → ``invoice_currency`` if an older Task-1 schema created ``currency``."""

	if not frappe.db.table_exists("tabPDC Invoice Application"):
		return

	has_old = frappe.db.has_column("PDC Invoice Application", "currency")
	has_new = frappe.db.has_column("PDC Invoice Application", "invoice_currency")

	if has_old and has_new:
		frappe.db.sql(
			"""
			UPDATE `tabPDC Invoice Application`
			SET `invoice_currency` = COALESCE(`invoice_currency`, `currency`)
			WHERE `invoice_currency` IS NULL OR `invoice_currency` = ''
			"""
		)
		frappe.db.sql_ddl("ALTER TABLE `tabPDC Invoice Application` DROP COLUMN `currency`")
	elif has_old and not has_new:
		frappe.db.sql_ddl(
			"ALTER TABLE `tabPDC Invoice Application` CHANGE COLUMN `currency` `invoice_currency` VARCHAR(140)"
		)


def _ensure_invoice_pdc_application_fields():
	def insert_after(dt: str) -> str:
		meta = frappe.get_meta(dt)
		for candidate in ("advance_paid", "rounded_total", "grand_total", "net_total"):
			if meta.has_field(candidate):
				return candidate
		return "terms" if meta.has_field("terms") else "name"

	expected_fieldtype = "Table"
	expected_options = "PDC Invoice Application"

	for dt in ("Purchase Invoice", "Sales Invoice"):
		existing = frappe.db.get_value(
			"Custom Field",
			{"dt": dt, "fieldname": "pdc_invoice_applications"},
			["name", "fieldtype", "options"],
			as_dict=True,
		)
		if not existing:
			continue
		ft = (existing.fieldtype or "").strip()
		opt = (existing.options or "").strip()
		if ft != expected_fieldtype or opt != expected_options:
			frappe.throw(
				_(
					"Migration stopped: Custom Field `{0}` on {1} already exists with incompatible definition "
					"(fieldtype={2!r}, options={3!r}; expected fieldtype={4!r}, options={5!r}). "
					"Rename or remove the conflicting field before migrating."
				).format(
					"pdc_invoice_applications",
					dt,
					ft,
					opt,
					expected_fieldtype,
					expected_options,
				)
			)

	create_custom_fields(
		{
			"Purchase Invoice": [
				{
					"fieldname": "pdc_invoice_applications",
					"label": "PDC Invoice Applications",
					"fieldtype": "Table",
					"options": "PDC Invoice Application",
					"insert_after": insert_after("Purchase Invoice"),
				}
			],
			"Sales Invoice": [
				{
					"fieldname": "pdc_invoice_applications",
					"label": "PDC Invoice Applications",
					"fieldtype": "Table",
					"options": "PDC Invoice Application",
					"insert_after": insert_after("Sales Invoice"),
				}
			],
		},
		update=True,
	)
