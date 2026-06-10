# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Mirror of PDC list filter empty-value rules (see post_dated_cheque_list.js)."""

from __future__ import annotations

import unittest

PDC = "Post Dated Cheque"

CONDITIONS_WITHOUT_OPERAND = frozenset(
	{
		"set",
		"not set",
		"is set",
		"is not set",
		"is null",
		"is not null",
		"is empty",
		"is not empty",
	}
)

CONDITIONS_REQUIRING_VALUE = frozenset(
	{
		"=",
		"!=",
		"like",
		"not like",
		"in",
		"not in",
		"between",
		">",
		"<",
		">=",
		"<=",
	}
)


def _is_empty(value) -> bool:
	if value is None:
		return True
	if isinstance(value, list):
		return len(value) == 0 or all(_is_empty(v) for v in value)
	if isinstance(value, str):
		return value.strip() == ""
	return False


def filter_tuple_has_invalid_empty_value(row: list) -> bool:
	if not row or len(row) < 3:
		return False
	cond = (row[2] or "").strip().lower()
	val = row[3] if len(row) > 3 else None
	if cond in CONDITIONS_WITHOUT_OPERAND:
		return False
	if cond == "is":
		return _is_empty(val)
	if cond in CONDITIONS_REQUIRING_VALUE:
		return _is_empty(val)
	return _is_empty(val)


def sanitize(rows: list[list]) -> list[list]:
	return [r for r in rows if not filter_tuple_has_invalid_empty_value(r)]


class TestPDCListFilterSanitize(unittest.TestCase):
	def test_empty_id_equals_invalid(self):
		row = [PDC, "name", "=", ""]
		self.assertTrue(filter_tuple_has_invalid_empty_value(row))

	def test_valid_id_equals(self):
		row = [PDC, "name", "=", "PDC-2026-00001"]
		self.assertFalse(filter_tuple_has_invalid_empty_value(row))

	def test_is_set_valid(self):
		row = [PDC, "name", "is", "set"]
		self.assertFalse(filter_tuple_has_invalid_empty_value(row))

	def test_sanitize_keeps_valid_only(self):
		rows = [
			[PDC, "name", "=", ""],
			[PDC, "workflow_state", "=", "Registered"],
			[PDC, "name", "is", "set"],
		]
		out = sanitize(rows)
		self.assertEqual(len(out), 2)
		self.assertNotIn([PDC, "name", "=", ""], out)


if __name__ == "__main__":
	unittest.main()
