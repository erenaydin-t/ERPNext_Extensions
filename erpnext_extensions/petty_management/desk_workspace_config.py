"""Desk workspace / sidebar icon map (Frappe Icon field — Lucide-style names)."""

from __future__ import annotations

# Workspace center cards (Card Break labels)
WORKSPACE_CARD_ICONS: dict[str, str] = {
	"Setup": "settings",
	"Transactions": "repeat",
	"Reports": "bar-chart-2",
}

# Workspace link rows: (label, link_type, link_to, extra)
WORKSPACE_SETUP_LINKS = (
	("PM Settings", "DocType", "PM Settings", {"icon": "settings"}),
	("PM Holder", "DocType", "PM Holder", {"icon": "users"}),
)

WORKSPACE_TRANSACTION_LINKS = (
	("PM Request", "DocType", "PM Request", {"icon": "credit-card"}),
	("PM Clearance", "DocType", "PM Clearance", {"icon": "check-square"}),
	("Purchase Invoice", "DocType", "Purchase Invoice", {"icon": "file-text"}),
	("Payment Entry", "DocType", "Payment Entry", {"icon": "dollar-sign"}),
	("Journal Entry", "DocType", "Journal Entry", {"icon": "book-open"}),
)

WORKSPACE_REPORT_LINKS = (
	("PM Balance Report", "Report", "PM Balance Report", {"icon": "pie-chart", "is_query_report": 1}),
	("PM Ledger Report", "Report", "PM Ledger Report", {"icon": "book"}),
	("PM Pending Clearance Report", "Report", "PM Pending Clearance Report", {"icon": "clock"}),
	("PM Settlement Ledger", "Report", "PM Settlement Ledger", {"icon": "archive"}),
	(
		"PM Request Availability Report",
		"Report",
		"PM Request Availability Report",
		{"icon": "bar-chart-2", "is_query_report": 1},
	),
)

# Sidebar: section label -> icon; link label -> icon
SIDEBAR_HOME_ICON = "home"
SIDEBAR_SECTION_ICONS: dict[str, str] = {
	"Setup": "settings",
	"Transactions": "repeat",
	"Reports": "bar-chart-2",
}

SIDEBAR_LINK_ICONS: dict[str, str] = {
	"PM Settings": "settings",
	"PM Holder": "users",
	"PM Request": "credit-card",
	"PM Clearance": "check-square",
	"Purchase Invoice": "file-text",
	"Payment Entry": "dollar-sign",
	"Journal Entry": "book-open",
	"PM Balance Report": "pie-chart",
	"PM Ledger Report": "book",
	"PM Pending Clearance Report": "clock",
	"PM Settlement Ledger": "archive",
	"PM Request Availability Report": "bar-chart-2",
}
