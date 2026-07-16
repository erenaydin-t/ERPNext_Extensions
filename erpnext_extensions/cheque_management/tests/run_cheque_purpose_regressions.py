"""Run selected Cheque/PDC regression modules under site context.

bench --site development.localhost execute \\
  erpnext_extensions.cheque_management.tests.run_cheque_purpose_regressions.run
"""

from __future__ import annotations

import importlib
import json
import unittest


MODULES = [
	"erpnext_extensions.cheque_management.tests.test_pdc_workflow_rollback",
	"erpnext_extensions.cheque_management.tests.test_pdc_import_cleanup",
	"erpnext_extensions.cheque_management.tests.test_cheque_leaf_void",
	"erpnext_extensions.cheque_management.tests.test_pdc_list_filter_sanitize",
	"erpnext_extensions.cheque_management.tests.test_pdc_opening_import_rollback_integration",
	"erpnext_extensions.cheque_management.tests.test_pdc_direct_cancel",
]


def run():
	summary = []
	all_ok = True
	for name in MODULES:
		mod = importlib.import_module(name)
		suite = unittest.defaultTestLoader.loadTestsFromModule(mod)
		result = unittest.TextTestRunner(verbosity=1).run(suite)
		ok = result.wasSuccessful()
		all_ok = all_ok and ok
		summary.append(
			{
				"module": name,
				"ok": ok,
				"testsRun": result.testsRun,
				"failures": len(result.failures or []),
				"errors": len(result.errors or []),
				"skipped": len(result.skipped or []),
			}
		)
	out = {"ok": all_ok, "summary": summary}
	print(json.dumps(out, indent=2))
	return out
