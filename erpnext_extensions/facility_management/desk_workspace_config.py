# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

WORKSPACE_CARD_ICONS: dict[str, str] = {
	"Transactions": "landmark",
	"Reports": "bar-chart-2",
	"Configuration": "settings",
}

WORKSPACE_TRANSACTION_LINKS = (
	("Facility", "DocType", "Facility", {"icon": "landmark"}),
	("Facility Repayment", "DocType", "Facility Repayment", {"icon": "repeat"}),
	("Journal Entry", "DocType", "Journal Entry", {"icon": "book-open"}),
)

WORKSPACE_REPORT_LINKS = (
	("Facility Balance", "Report", "Facility Balance", {"icon": "pie-chart", "is_query_report": 0}),
	("Facility Ledger", "Report", "Facility Ledger", {"icon": "book", "is_query_report": 0}),
)

WORKSPACE_CONFIGURATION_LINKS = (
	("Facility Settings", "DocType", "Facility Settings", {"icon": "settings"}),
)

SIDEBAR_HOME_ICON = "home"
SIDEBAR_SECTION_ICONS: dict[str, str] = {
	"Transactions": "landmark",
	"Reports": "bar-chart-2",
	"Configuration": "settings",
}

SIDEBAR_LINK_ICONS: dict[str, str] = {
	"Facility": "landmark",
	"Facility Repayment": "repeat",
	"Journal Entry": "book-open",
	"Facility Balance": "pie-chart",
	"Facility Ledger": "book",
	"Facility Settings": "settings",
}
