# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

MODULE = "Consignment Stock"

F_IS_LOAN_ISSUE = "custom_is_material_loan_issue"
F_IS_LOAN_RETURN = "custom_is_material_loan_return"

F_PARTY_TYPE = "custom_material_loan_party_type"
F_PARTY = "custom_material_loan_party"
F_PHYSICAL_STATUS = "custom_material_loan_status"
F_RECOGNITION_STATUS = "custom_material_loan_recognition_status"
F_SETTLEMENT_STATUS = "custom_material_loan_settlement_status"
F_EXPECTED_RETURN_DATE = "custom_material_loan_expected_return_date"
F_EXTERNAL_REF = "custom_material_loan_external_reference"
F_ISSUE_REF_HEADER = "custom_material_loan_issue_reference"
F_RECOGNITION_JE = "custom_material_loan_recognition_je"
F_SETTLEMENT_JE = "custom_material_loan_settlement_je"

F_ISSUE_SE = "custom_material_loan_issue"
F_ISSUE_DETAIL = "custom_material_loan_issue_detail"
F_ISSUE_RATE = "custom_material_loan_issue_rate"
F_ISSUE_VALUE = "custom_material_loan_issue_value"
F_ISSUE_QTY = "custom_material_loan_issue_qty"
F_PREV_RETURNED_QTY = "custom_material_loan_previously_returned_qty"
F_REMAINING_QTY = "custom_material_loan_remaining_returnable_qty"
F_RETURN_VALUE = "custom_material_loan_return_value"
F_SETTLEMENT_AMOUNT = "custom_material_loan_settlement_amount"

F_JE_ROLE = "custom_material_loan_je_role"
JE_ROLE_RECOGNITION = "Recognition"
JE_ROLE_SETTLEMENT = "Settlement"

STATUS_DRAFT = "Draft"
STATUS_ISSUED = "Issued"
STATUS_PARTIALLY_RETURNED = "Partially Returned"
STATUS_FULLY_RETURNED = "Fully Returned"
STATUS_OVERDUE = "Overdue"
STATUS_CANCELLED = "Cancelled"

PHYSICAL_STATUS_OPTIONS = "\n".join(
	[
		STATUS_DRAFT,
		STATUS_ISSUED,
		STATUS_PARTIALLY_RETURNED,
		STATUS_FULLY_RETURNED,
		STATUS_OVERDUE,
		STATUS_CANCELLED,
	]
)

REC_NOT_CREATED = "Not Created"
REC_DRAFT = "Draft"
REC_SUBMITTED = "Submitted"
REC_CANCELLED = "Cancelled"

RECOGNITION_STATUS_OPTIONS = "\n".join(
	[REC_NOT_CREATED, REC_DRAFT, REC_SUBMITTED, REC_CANCELLED]
)

SET_NOT_REQUIRED = "Not Required"
SET_PENDING = "Pending"
SET_PARTIALLY_SETTLED = "Partially Settled"
SET_FULLY_SETTLED = "Fully Settled"

SETTLEMENT_STATUS_OPTIONS = "\n".join(
	[SET_NOT_REQUIRED, SET_PENDING, SET_PARTIALLY_SETTLED, SET_FULLY_SETTLED]
)
