# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from erpnext_extensions.consignment_stock.constants import (
	F_HAS_RECEIPT_REF,
	F_IS_RECEIPT,
	F_IS_RETURN,
	F_JE_ROLE,
	F_ORIGINAL_QTY,
	F_ORIGINAL_RATE,
	F_PARTY,
	F_PARTY_TYPE,
	F_PREV_RETURNED_QTY,
	F_RECEIPT_DETAIL,
	F_RECEIPT_REF,
	F_RECEIPT_SE,
	F_RECOGNITION_JE,
	F_REMAINING_QTY,
	F_SETTLEMENT_AMOUNT,
	F_SETTLEMENT_JE,
	F_STATUS,
	JE_ROLE_RECOGNITION,
	JE_ROLE_SETTLEMENT,
	MODULE,
	STATUS_OPTIONS,
)

_JE_REFERENCE_OPTIONS = (
	"\nSales Invoice\nPurchase Invoice\nJournal Entry\nSales Order\nPurchase Order\n"
	"Expense Claim\nAsset\nLoan\nPayroll Entry\nEmployee Advance\nExchange Rate Revaluation\n"
	"Invoice Discounting\nFees\nFull and Final Statement\nPayment Entry\nBank Transaction\n"
	"Stock Entry"
)


def get_custom_fields() -> dict:
	return {
		"Stock Entry Type": [
			{
				"fieldname": F_IS_RECEIPT,
				"label": "Consignment Receipt",
				"fieldtype": "Check",
				"insert_after": "add_to_transit",
				"depends_on": "eval:doc.purpose=='Material Receipt'",
				"description": "Material Receipt for consigned raw materials",
				"module": MODULE,
			},
			{
				"fieldname": F_IS_RETURN,
				"label": "Consignment Return",
				"fieldtype": "Check",
				"insert_after": F_IS_RECEIPT,
				"depends_on": "eval:doc.purpose=='Material Issue'",
				"description": "Material Issue returning consigned raw materials",
				"module": MODULE,
			},
		],
		"Stock Entry": [
			{
				"fieldname": "custom_consignment_section",
				"label": "Consignment",
				"fieldtype": "Section Break",
				"insert_after": "remarks",
				"collapsible": 1,
				"depends_on": f"eval:doc.{F_IS_RECEIPT}||doc.{F_IS_RETURN}",
				"module": MODULE,
			},
			{
				"fieldname": F_IS_RECEIPT,
				"label": "Is Consignment Receipt",
				"fieldtype": "Check",
				"read_only": 1,
				"fetch_from": f"stock_entry_type.{F_IS_RECEIPT}",
				"insert_after": "custom_consignment_section",
				"module": MODULE,
			},
			{
				"fieldname": F_IS_RETURN,
				"label": "Is Consignment Return",
				"fieldtype": "Check",
				"read_only": 1,
				"fetch_from": f"stock_entry_type.{F_IS_RETURN}",
				"insert_after": F_IS_RECEIPT,
				"module": MODULE,
			},
			{
				"fieldname": F_PARTY_TYPE,
				"label": "Consignment Party Type",
				"fieldtype": "Link",
				"options": "Party Type",
				"insert_after": F_IS_RETURN,
				"depends_on": f"eval:doc.{F_IS_RECEIPT}||doc.{F_IS_RETURN}",
				"mandatory_depends_on": f"eval:doc.{F_IS_RECEIPT}||doc.{F_IS_RETURN}",
				"module": MODULE,
			},
			{
				"fieldname": F_PARTY,
				"label": "Consignment Party",
				"fieldtype": "Dynamic Link",
				"options": F_PARTY_TYPE,
				"insert_after": F_PARTY_TYPE,
				"depends_on": f"eval:doc.{F_IS_RECEIPT}||doc.{F_IS_RETURN}",
				"mandatory_depends_on": f"eval:doc.{F_IS_RECEIPT}||doc.{F_IS_RETURN}",
				"module": MODULE,
			},
			{
				"fieldname": "custom_consignment_col_break",
				"fieldtype": "Column Break",
				"insert_after": F_PARTY,
				"module": MODULE,
			},
			{
				"fieldname": F_HAS_RECEIPT_REF,
				"label": "Has Receipt Reference",
				"fieldtype": "Check",
				"default": "1",
				"insert_after": "custom_consignment_col_break",
				"depends_on": f"eval:doc.{F_IS_RETURN}",
				"read_only": 1,
				"description": "3.8.0 requires every return to reference receipt rows",
				"module": MODULE,
			},
			{
				"fieldname": F_RECEIPT_REF,
				"label": "Default Receipt Reference",
				"fieldtype": "Link",
				"options": "Stock Entry",
				"insert_after": F_HAS_RECEIPT_REF,
				"depends_on": f"eval:doc.{F_IS_RETURN}",
				"module": MODULE,
			},
			{
				"fieldname": F_RECOGNITION_JE,
				"label": "Recognition Journal Entry",
				"fieldtype": "Link",
				"options": "Journal Entry",
				"insert_after": F_RECEIPT_REF,
				"read_only": 1,
				"no_copy": 1,
				"depends_on": f"eval:doc.{F_IS_RECEIPT}",
				"module": MODULE,
			},
			{
				"fieldname": F_SETTLEMENT_JE,
				"label": "Settlement Journal Entry",
				"fieldtype": "Link",
				"options": "Journal Entry",
				"insert_after": F_RECOGNITION_JE,
				"read_only": 1,
				"no_copy": 1,
				"depends_on": f"eval:doc.{F_IS_RETURN}",
				"module": MODULE,
			},
			{
				"fieldname": F_STATUS,
				"label": "Consignment Status",
				"fieldtype": "Select",
				"options": STATUS_OPTIONS,
				"insert_after": F_SETTLEMENT_JE,
				"read_only": 1,
				"no_copy": 1,
				"depends_on": f"eval:doc.{F_IS_RECEIPT}||doc.{F_IS_RETURN}",
				"module": MODULE,
			},
		],
		"Stock Entry Detail": [
			{
				"fieldname": "custom_consignment_detail_section",
				"label": "Consignment Reference",
				"fieldtype": "Section Break",
				"insert_after": "expense_account",
				"collapsible": 1,
				"module": MODULE,
			},
			{
				"fieldname": F_RECEIPT_SE,
				"label": "Consignment Receipt",
				"fieldtype": "Link",
				"options": "Stock Entry",
				"insert_after": "custom_consignment_detail_section",
				"module": MODULE,
			},
			{
				"fieldname": F_RECEIPT_DETAIL,
				"label": "Consignment Receipt Row",
				"fieldtype": "Data",
				"insert_after": F_RECEIPT_SE,
				"module": MODULE,
			},
			{
				"fieldname": F_ORIGINAL_RATE,
				"label": "Original Receipt Rate",
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"read_only": 1,
				"insert_after": F_RECEIPT_DETAIL,
				"module": MODULE,
			},
			{
				"fieldname": F_ORIGINAL_QTY,
				"label": "Original Receipt Qty",
				"fieldtype": "Float",
				"read_only": 1,
				"insert_after": F_ORIGINAL_RATE,
				"module": MODULE,
			},
			{
				"fieldname": F_PREV_RETURNED_QTY,
				"label": "Previously Returned Qty",
				"fieldtype": "Float",
				"read_only": 1,
				"insert_after": F_ORIGINAL_QTY,
				"module": MODULE,
			},
			{
				"fieldname": F_REMAINING_QTY,
				"label": "Remaining Returnable Qty",
				"fieldtype": "Float",
				"read_only": 1,
				"insert_after": F_PREV_RETURNED_QTY,
				"module": MODULE,
			},
			{
				"fieldname": F_SETTLEMENT_AMOUNT,
				"label": "Consignment Settlement Amount",
				"fieldtype": "Currency",
				"options": "Company:company:default_currency",
				"read_only": 1,
				"insert_after": F_REMAINING_QTY,
				"module": MODULE,
			},
		],
		"Journal Entry": [
			{
				"fieldname": F_JE_ROLE,
				"label": "Consignment JE Role",
				"fieldtype": "Select",
				"options": f"\n{JE_ROLE_RECOGNITION}\n{JE_ROLE_SETTLEMENT}",
				"insert_after": "user_remark",
				"read_only": 1,
				"no_copy": 1,
				"module": MODULE,
			},
		],
	}


def ensure_stock_entry_reference_type_option() -> None:
	"""Extend Journal Entry Account.reference_type Select with Stock Entry (standard field)."""
	meta = frappe.get_meta("Journal Entry Account")
	field = meta.get_field("reference_type")
	if not field:
		return
	current = field.options or ""
	if "Stock Entry" in current.split("\n"):
		# Still ensure Property Setter exists for fresh installs that already have core options without SE
		pass
	make_property_setter(
		"Journal Entry Account",
		"reference_type",
		"options",
		_JE_REFERENCE_OPTIONS,
		"Text",
		validate_fields_for_doctype=False,
	)


def ensure_custom_fields() -> None:
	create_custom_fields(get_custom_fields(), update=True)
	ensure_stock_entry_reference_type_option()
