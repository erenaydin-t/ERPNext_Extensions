"""Run cheque_purpose tests under site context via bench execute.

bench --site development.localhost execute \\
  erpnext_extensions.cheque_management.tests.run_cheque_purpose_tests.run
"""

from __future__ import annotations

import json
import unittest


def run():
	from erpnext_extensions.cheque_management.tests import test_pdc_cheque_purpose as mod

	loader = unittest.TestLoader()
	suite = unittest.TestSuite()
	suite.addTests(loader.loadTestsFromModule(mod))
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	out = {
		"ok": result.wasSuccessful(),
		"testsRun": result.testsRun,
		"failures": [
			{"test": str(t), "traceback": tb} for t, tb in (result.failures or [])
		],
		"errors": [{"test": str(t), "traceback": tb} for t, tb in (result.errors or [])],
		"skipped": len(result.skipped or []),
	}
	print(json.dumps(out, ensure_ascii=False, indent=2))
	return out
