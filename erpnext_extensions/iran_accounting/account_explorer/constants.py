# Copyright (c) 2026, Farbod Siyahpoosh and contributors

MEASURE_FIELDS = (
	"opening_debit",
	"opening_credit",
	"period_debit",
	"period_credit",
	"closing_debit",
	"closing_credit",
	"net_balance",
	"debit_balance",
	"credit_balance",
)

SORTABLE_FIELDS = frozenset(
	{
		"display_code",
		"display_title",
		"opening_debit",
		"opening_credit",
		"period_debit",
		"period_credit",
		"debit_balance",
		"credit_balance",
		"net_balance",
	}
)

VIRTUAL_UNCLASSIFIED_KEY = "virtual:unclassified"
VIRTUAL_PREFIX_KEY_PREFIX = "virtual:prefix"
REAL_ACCOUNT_KEY_PREFIX = "account"

DEFAULT_LEVELS = (
	{"sequence": 1, "enabled": 1, "code_length": 2, "title": "Group", "title_fa": "گروه"},
	{"sequence": 2, "enabled": 1, "code_length": 4, "title": "General Ledger", "title_fa": "کل"},
	{"sequence": 3, "enabled": 1, "code_length": 6, "title": "Subsidiary Ledger", "title_fa": "معین"},
	{"sequence": 4, "enabled": 1, "code_length": 8, "title": "Account Level 4", "title_fa": "سطح چهار"},
	{"sequence": 5, "enabled": 1, "code_length": 10, "title": "Account Level 5", "title_fa": "سطح پنج"},
)

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
