# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

MODULE = "Consignment Stock"

# Stock Entry Type / Stock Entry flags
F_IS_RECEIPT = "custom_is_consignment_receipt"
F_IS_RETURN = "custom_is_consignment_return"

# Stock Entry header
F_PARTY_TYPE = "custom_consignment_party_type"
F_PARTY = "custom_consignment_party"

# Stock Entry Dynamic Link controllers must be Link/DocType (Frappe v16).
# 3.8.9 workflows allow only Customer and Supplier on Stock Entry.
ALLOWED_PARTY_TYPES = ("Customer", "Supplier")
F_HAS_RECEIPT_REF = "custom_has_consignment_receipt_reference"
F_RECEIPT_REF = "custom_consignment_receipt_reference"
F_RECOGNITION_JE = "custom_consignment_recognition_je"
F_SETTLEMENT_JE = "custom_consignment_settlement_je"
F_STATUS = "custom_consignment_status"

# Stock Entry Detail
F_RECEIPT_SE = "custom_consignment_receipt_stock_entry"
F_RECEIPT_DETAIL = "custom_consignment_receipt_detail"
F_ORIGINAL_RATE = "custom_original_receipt_rate"
F_ORIGINAL_QTY = "custom_original_receipt_qty"
F_PREV_RETURNED_QTY = "custom_previously_returned_qty"
F_REMAINING_QTY = "custom_remaining_returnable_qty"
F_SETTLEMENT_AMOUNT = "custom_consignment_settlement_amount"

# Journal Entry
F_JE_ROLE = "custom_consignment_je_role"
JE_ROLE_RECOGNITION = "Recognition"
JE_ROLE_SETTLEMENT = "Settlement"

STATUS_DRAFT = "Draft"
STATUS_RECEIPT_SUBMITTED = "Receipt Submitted"
STATUS_RECOGNIZED = "Recognized"
STATUS_PARTIALLY_RETURNED = "Partially Returned"
STATUS_FULLY_RETURNED = "Fully Returned"
STATUS_RETURN_SUBMITTED = "Return Submitted"
STATUS_SETTLED = "Settled"
STATUS_CANCELLED = "Cancelled"

STATUS_OPTIONS = "\n".join(
	[
		STATUS_DRAFT,
		STATUS_RECEIPT_SUBMITTED,
		STATUS_RECOGNIZED,
		STATUS_PARTIALLY_RETURNED,
		STATUS_FULLY_RETURNED,
		STATUS_RETURN_SUBMITTED,
		STATUS_SETTLED,
		STATUS_CANCELLED,
	]
)
