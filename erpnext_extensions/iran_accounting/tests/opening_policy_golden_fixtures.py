# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Deterministic golden rows for OpeningEntryPolicy v4.5.0 (GF-01 … GF-17).

Expected OFF/ON measures are declared explicitly (hand-computed from row semantics).
Tests must not derive expected values via aggregate_measures_from_rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from erpnext_extensions.iran_accounting.account_explorer.measures import measures_from_opening_period
from erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy import (
	AccountAxisEngine,
	PeriodWindow,
)

FROM_DATE = date(2026, 4, 1)
TO_DATE = date(2026, 4, 30)
PCV_END = date(2025, 12, 31)
GAP_START = date(2026, 1, 1)


def _row(
	posting_date: date,
	*,
	debit: float = 0.0,
	credit: float = 0.0,
	is_opening: str = "No",
	is_cancelled: int = 0,
	voucher_type: str = "Journal Entry",
	finance_book: str = "",
	party: str = "",
) -> dict[str, Any]:
	return {
		"posting_date": posting_date,
		"debit": debit,
		"credit": credit,
		"is_opening": is_opening,
		"is_cancelled": is_cancelled,
		"voucher_type": voucher_type,
		"finance_book": finance_book,
		"party": party,
	}


def _m(od: float, oc: float, pd: float, pc: float) -> dict[str, float]:
	return measures_from_opening_period(od, oc, pd, pc)


@dataclass
class GoldenFixture:
	fixture_id: str
	description: str
	rows: list[dict[str, Any]]
	window: PeriodWindow = field(default_factory=lambda: PeriodWindow(FROM_DATE, TO_DATE))
	expected_off: dict[str, float] = field(default_factory=dict)
	expected_on: dict[str, float] = field(default_factory=dict)
	expected_engine: AccountAxisEngine | None = None
	engine_context: dict[str, Any] = field(default_factory=dict)


GF_01 = GoldenFixture(
	fixture_id="GF-01",
	description="Normal GL pre-period",
	rows=[_row(date(2026, 3, 15), debit=800)],
	expected_off=_m(800, 0, 0, 0),
	expected_on=_m(800, 0, 0, 0),
)

GF_02 = GoldenFixture(
	fixture_id="GF-02",
	description="Normal GL in-period",
	rows=[_row(date(2026, 4, 10), debit=500, credit=100)],
	expected_off=_m(0, 0, 500, 100),
	expected_on=_m(0, 0, 500, 100),
)

GF_03 = GoldenFixture(
	fixture_id="GF-03",
	description="Opening GL pre-period",
	rows=[_row(date(2026, 3, 20), debit=200, is_opening="Yes")],
	expected_off=_m(0, 0, 0, 0),
	expected_on=_m(200, 0, 0, 0),
)

GF_04 = GoldenFixture(
	fixture_id="GF-04",
	description="Opening GL on from_date",
	rows=[_row(FROM_DATE, debit=300, is_opening="Yes")],
	expected_off=_m(0, 0, 0, 0),
	expected_on=_m(0, 0, 300, 0),
)

GF_05 = GoldenFixture(
	fixture_id="GF-05",
	description="Opening GL mid-period",
	rows=[_row(date(2026, 4, 10), debit=300, is_opening="Yes")],
	expected_off=_m(0, 0, 0, 0),
	expected_on=_m(0, 0, 300, 0),
)

GF_06 = GoldenFixture(
	fixture_id="GF-06",
	description="Period Closing Voucher row excluded by default",
	rows=[
		_row(date(2026, 4, 5), debit=100),
		_row(date(2026, 4, 5), debit=999, voucher_type="Period Closing Voucher"),
	],
	expected_off=_m(0, 0, 100, 0),
	expected_on=_m(0, 0, 100, 0),
)

GF_07 = GoldenFixture(
	fixture_id="GF-07",
	description="Cancelled GL excluded by default",
	rows=[
		_row(date(2026, 4, 8), debit=250),
		_row(date(2026, 4, 8), debit=999, is_cancelled=1),
	],
	expected_off=_m(0, 0, 250, 0),
	expected_on=_m(0, 0, 250, 0),
)

GF_08 = GoldenFixture(
	fixture_id="GF-08",
	description="Non-default finance book row present (aggregate layer sees row; scope filters in Phase 2)",
	rows=[_row(date(2026, 4, 12), debit=120, finance_book="Non-Default FB")],
	expected_off=_m(0, 0, 120, 0),
	expected_on=_m(0, 0, 120, 0),
)

GF_09 = GoldenFixture(
	fixture_id="GF-09",
	description="Unspecified party bucket row (empty party)",
	rows=[_row(date(2026, 4, 14), debit=75, party="")],
	expected_off=_m(0, 0, 75, 0),
	expected_on=_m(0, 0, 75, 0),
)

GF_10 = GoldenFixture(
	fixture_id="GF-10",
	description="Cross-axis same GL set",
	rows=[
		_row(date(2026, 3, 10), debit=400),
		_row(date(2026, 3, 25), debit=100, is_opening="Yes"),
		_row(date(2026, 4, 10), debit=500, credit=50),
		_row(date(2026, 4, 15), debit=300, is_opening="Yes"),
	],
	# OFF: normal pre 400; opening rows excluded; in-period normal 500/50
	expected_off=_m(400, 0, 500, 50),
	# ON: pre normal 400 + pre opening 100; in-period normal 500/50 + opening 300
	expected_on=_m(500, 0, 800, 50),
)

GF_11 = GoldenFixture(
	fixture_id="GF-11",
	description="Filtered parity baseline rows (normal pre + in-period)",
	rows=[
		_row(date(2026, 3, 5), debit=1000),
		_row(date(2026, 4, 20), debit=200, credit=50),
	],
	expected_off=_m(1000, 0, 200, 50),
	expected_on=_m(1000, 0, 200, 50),
)

GF_12 = GoldenFixture(
	fixture_id="GF-12",
	description="Double-count sentinel: in-period opening must not also hit opening under ON",
	rows=[
		_row(date(2026, 3, 1), debit=100, is_opening="Yes"),
		_row(date(2026, 4, 10), debit=300, is_opening="Yes"),
		_row(date(2026, 4, 12), debit=50),
	],
	expected_off=_m(0, 0, 50, 0),
	expected_on=_m(100, 0, 350, 0),
)

GF_13 = GoldenFixture(
	fixture_id="GF-13",
	description="Opening GL before PCV (ACB would embed O_hist); policy OFF via E3 aggregate",
	rows=[
		_row(date(2025, 11, 1), debit=800),
		_row(date(2025, 11, 2), debit=200, is_opening="Yes"),
	],
	expected_off=_m(800, 0, 0, 0),
	expected_on=_m(1000, 0, 0, 0),
	expected_engine=AccountAxisEngine.E3_SCOPED_GL,
	engine_context={"acb_applicable": True, "opening_flagged_baked_in_acb": True, "policy_off": True},
)

GF_14 = GoldenFixture(
	fixture_id="GF-14",
	description="Same as GF-13 under ON",
	rows=[
		_row(date(2025, 11, 1), debit=800),
		_row(date(2025, 11, 2), debit=200, is_opening="Yes"),
	],
	expected_off=_m(800, 0, 0, 0),
	expected_on=_m(1000, 0, 0, 0),
	expected_engine=AccountAxisEngine.E1_TB_DELTA,
	engine_context={"acb_applicable": True, "opening_flagged_baked_in_acb": True, "policy_off": False},
)

GF_15 = GoldenFixture(
	fixture_id="GF-15",
	description="Opening GL after PCV before from_date (gap)",
	rows=[_row(GAP_START, debit=150, is_opening="Yes")],
	expected_off=_m(0, 0, 0, 0),
	expected_on=_m(150, 0, 0, 0),
)

GF_16 = GoldenFixture(
	fixture_id="GF-16",
	description="Opening GL inside report period after PCV",
	rows=[_row(date(2026, 4, 10), debit=300, is_opening="Yes")],
	expected_off=_m(0, 0, 0, 0),
	expected_on=_m(0, 0, 300, 0),
)

GF_17 = GoldenFixture(
	fixture_id="GF-17",
	description="Normal + opening GL before PCV",
	rows=[
		_row(date(2025, 10, 1), debit=800),
		_row(date(2025, 10, 2), debit=200, is_opening="Yes"),
	],
	expected_off=_m(800, 0, 0, 0),
	expected_on=_m(1000, 0, 0, 0),
	expected_engine=AccountAxisEngine.E3_SCOPED_GL,
	engine_context={"acb_applicable": True, "opening_flagged_baked_in_acb": True, "policy_off": True},
)


ALL_GOLDEN_FIXTURES: tuple[GoldenFixture, ...] = (
	GF_01,
	GF_02,
	GF_03,
	GF_04,
	GF_05,
	GF_06,
	GF_07,
	GF_08,
	GF_09,
	GF_10,
	GF_11,
	GF_12,
	GF_13,
	GF_14,
	GF_15,
	GF_16,
	GF_17,
)

GOLDEN_FIXTURES_BY_ID: dict[str, GoldenFixture] = {fx.fixture_id: fx for fx in ALL_GOLDEN_FIXTURES}

MARKER = "AE-OEP-GF"


def iter_golden_fixture_ids() -> list[str]:
	return [fx.fixture_id for fx in ALL_GOLDEN_FIXTURES]
