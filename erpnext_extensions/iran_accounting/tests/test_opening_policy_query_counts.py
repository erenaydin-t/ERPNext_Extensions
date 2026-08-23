# Copyright (c) 2026, Farbod Siyahpoosh and contributors
import json
import unittest

import frappe

from erpnext_extensions.iran_accounting.tests.opening_policy_query_counts import (
	E1_OFF_MAX,
	E1_OFF_ON_DELTA_MAX,
	E1_ON_MAX,
	ENGINE_HELPER_MAX_PER_REQUEST,
	E3_FILTERED_MAX,
	observe_opening_policy_query_counts,
)


class TestOpeningPolicyQueryCounts(unittest.TestCase):
	def test_observe_engine_and_axis_counts(self):
		frappe.set_user("Administrator")
		counts = json.loads(observe_opening_policy_query_counts("_Test Company"))
		for key, value in counts.items():
			if key.startswith("engine_") or key == "engine_helper_calls_off":
				continue
			self.assertIsInstance(value, int, key)
			self.assertGreater(value, 0, key)

		off = counts["E1_account_unfiltered_off"]
		on = counts["E1_account_unfiltered_on"]
		self.assertLessEqual(off, E1_OFF_MAX, f"E1 OFF unfiltered too many queries: {off}")
		self.assertLessEqual(on, E1_ON_MAX, f"E1 ON unfiltered too many queries: {on}")
		self.assertLessEqual(
			abs(off - on),
			E1_OFF_ON_DELTA_MAX,
			f"E1 OFF/ON query delta too large: off={off} on={on}",
		)
		self.assertLessEqual(counts["E3_account_filtered_off"], E3_FILTERED_MAX)

		helper_calls = counts["engine_helper_calls_off"]
		self.assertLessEqual(helper_calls.get("select_account_axis_engine", 0), ENGINE_HELPER_MAX_PER_REQUEST)
		self.assertLessEqual(helper_calls.get("policy_cache_entries", 99), 1)
