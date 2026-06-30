# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import ast
import importlib
import unittest
from collections import defaultdict
from pathlib import Path

import erpnext_extensions.iran_accounting.rounding as rounding
from erpnext_extensions.iran_accounting.monkey_patches import (
	_ROUNDING_REQUIRED,
	_ensure_rounding_module_complete,
	apply_monkey_patches,
)


class TestImportIntegrity(unittest.TestCase):
	def test_rounding_leaf_exports_required_symbols(self):
		for name in _ROUNDING_REQUIRED:
			self.assertTrue(hasattr(rounding, name), name)

	def test_ensure_rounding_module_complete_idempotent(self):
		_ensure_rounding_module_complete()
		for name in _ROUNDING_REQUIRED:
			self.assertTrue(hasattr(rounding, name), name)

	def test_apply_monkey_patches_loads_rounding(self):
		apply_monkey_patches()
		for name in _ROUNDING_REQUIRED:
			self.assertTrue(hasattr(rounding, name), name)

	def test_no_import_cycle_rounding_qty_stock_sync(self):
		base = Path(__file__).resolve().parents[1]
		mods = {
			"rounding": base / "rounding.py",
			"qty_rate_amount": base / "qty_rate_amount.py",
			"stock_reconciliation": base / "stock_reconciliation.py",
			"stock_reconciliation_sync": base / "stock_reconciliation_sync.py",
			"stock_ledger": base / "stock_ledger.py",
			"monkey_patches": base / "monkey_patches.py",
		}
		edges: dict[str, set[str]] = defaultdict(set)
		for mod, path in mods.items():
			tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
			for node in ast.walk(tree):
				if isinstance(node, ast.ImportFrom) and node.module:
					m = node.module
					if m.startswith("erpnext_extensions.iran_accounting."):
						dep = m.split("erpnext_extensions.iran_accounting.", 1)[1].split(".", 1)[0]
						if dep in mods and dep != mod:
							edges[mod].add(dep)
		# monkey_patches must not import stock_reconciliation (diagnostics cycle broken)
		self.assertNotIn("stock_reconciliation", edges.get("monkey_patches", set()))
		self.assertIn("stock_reconciliation_sync", edges.get("monkey_patches", set()))

	def test_qty_rate_amount_imports_rounding_only_as_module(self):
		base = Path(__file__).resolve().parents[1] / "qty_rate_amount.py"
		src = base.read_text(encoding="utf-8")
		self.assertIn("import erpnext_extensions.iran_accounting.rounding as rounding", src)
		importlib.import_module("erpnext_extensions.iran_accounting.qty_rate_amount")
