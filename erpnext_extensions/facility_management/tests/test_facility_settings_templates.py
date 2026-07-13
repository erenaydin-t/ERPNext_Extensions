# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

from erpnext_extensions.facility_management.facility_settings_doc import (
	FACILITY_SETTINGS_TEMPLATE_DEFAULTS,
	populate_facility_settings_template_defaults,
)


class TestFacilitySettingsTemplates(unittest.TestCase):
	def test_populate_empty_templates(self):
		class Doc:
			def __init__(self):
				self._data = {fn: None for fn in FACILITY_SETTINGS_TEMPLATE_DEFAULTS}

			def get(self, k):
				return self._data.get(k)

			def set(self, k, v):
				self._data[k] = v

		doc = Doc()
		populate_facility_settings_template_defaults(doc)
		for fn, expected in FACILITY_SETTINGS_TEMPLATE_DEFAULTS.items():
			self.assertEqual(doc.get(fn), expected)

	def test_preserve_custom_templates(self):
		custom = "CUSTOM-BANK-TEMPLATE"

		class Doc:
			def __init__(self):
				self._data = dict.fromkeys(FACILITY_SETTINGS_TEMPLATE_DEFAULTS, "")
				self._data["default_repayment_bank_row_description_template"] = custom

			def get(self, k):
				return self._data.get(k)

			def set(self, k, v):
				self._data[k] = v

		doc = Doc()
		populate_facility_settings_template_defaults(doc)
		self.assertEqual(doc.get("default_repayment_bank_row_description_template"), custom)
		self.assertEqual(
			doc.get("default_repayment_remarks_template"),
			FACILITY_SETTINGS_TEMPLATE_DEFAULTS["default_repayment_remarks_template"],
		)
