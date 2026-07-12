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

PARTY_SORTABLE_FIELDS = SORTABLE_FIELDS | frozenset({"party_type", "party", "party_identifier"})

DIMENSION_SORTABLE_FIELDS = SORTABLE_FIELDS | frozenset({"dimension_field", "dimension_value"})

VOUCHER_SORTABLE_FIELDS = frozenset(
	{
		"posting_date",
		"voucher_type",
		"voucher_no",
		"party_type",
		"party",
		"party_name",
		"voucher_title",
		"scoped_debit",
		"scoped_credit",
		"scoped_net",
		"full_voucher_debit",
		"full_voucher_credit",
	}
)

GL_GROUP_SORTABLE_FIELDS = frozenset(
	{
		"account",
		"account_name",
		"party_type",
		"party",
		"debit",
		"credit",
	}
)

VIEW_AXES = frozenset({"account_level", "party", "dimension", "voucher"})

DETAIL_MODES = frozenset({"summary", "grouped_gl"})

VIRTUAL_UNCLASSIFIED_KEY = "virtual:unclassified"
VIRTUAL_PREFIX_KEY_PREFIX = "virtual:prefix"
VIRTUAL_PARTY_UNSPECIFIED_KEY = "virtual:party:unspecified"
VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX = "virtual:dimension:unspecified"
REAL_ACCOUNT_KEY_PREFIX = "account"

NOT_SPECIFIED_LABEL = "Not Specified"
NOT_SPECIFIED_LABEL_FA = "تعیین نشده"

NATIVE_PARTY_TYPES = frozenset({"Customer", "Supplier", "Employee", "Shareholder"})

DEFAULT_PARTY_SOURCES = (
	{"sequence": 1, "enabled": 1, "party_type": "Customer", "label": "Customer", "label_fa": "مشتری"},
	{"sequence": 2, "enabled": 1, "party_type": "Supplier", "label": "Supplier", "label_fa": "تامین کننده"},
	{"sequence": 3, "enabled": 1, "party_type": "Employee", "label": "Employee", "label_fa": "کارمند"},
	{"sequence": 4, "enabled": 1, "party_type": "Shareholder", "label": "Shareholder", "label_fa": "سهامدار"},
)

DEFAULT_LEVELS = (
	{"sequence": 1, "enabled": 1, "code_length": 2, "title": "Group", "title_fa": "گروه"},
	{"sequence": 2, "enabled": 1, "code_length": 4, "title": "General Ledger", "title_fa": "کل"},
	{"sequence": 3, "enabled": 1, "code_length": 6, "title": "Subsidiary Ledger", "title_fa": "معین"},
	{"sequence": 4, "enabled": 1, "code_length": 8, "title": "Account Level 4", "title_fa": "سطح چهار"},
	{"sequence": 5, "enabled": 1, "code_length": 10, "title": "Account Level 5", "title_fa": "سطح پنج"},
)

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
