# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AccountScope:
	mode: str = "tree"
	selected_account: str | None = None
	virtual_row_key: str | None = None
	is_virtual_group: bool = False
	level_sequence: int | None = None
	tree_root_account: str | None = None


@dataclass
class PartyScope:
	party_type: str | None = None
	selected_party: str | None = None


@dataclass
class DimensionScope:
	dimension_field: str | None = None
	selected_value: str | None = None


@dataclass
class PaginationState:
	page: int = 1
	page_size: int = 50
	sort_field: str = "display_code"
	sort_order: str = "asc"


@dataclass
class AccountExplorerQuerySpec:
	company: str
	from_date: Any = None
	to_date: Any = None
	fiscal_year: str | None = None
	finance_book: str | None = None
	include_default_book_entries: bool = True
	include_cancelled_entries: bool = False
	include_opening_entries: bool = True
	include_period_closing_vouchers: bool = False
	hide_zero_rows: bool = True
	account_scope: AccountScope = field(default_factory=AccountScope)
	party_scope: PartyScope = field(default_factory=PartyScope)
	dimension_scope: DimensionScope = field(default_factory=DimensionScope)
	view_axis: str = "account_level"
	level_sequence: int | None = None
	pagination: PaginationState = field(default_factory=PaginationState)
	presentation_currency: str = "company"
	# Server-resolved; never supplied by client as authoritative
	included_account_names: list[str] | None = None

	def requires_bounded_dates(self) -> bool:
		return bool(self.company and self.from_date and self.to_date)
