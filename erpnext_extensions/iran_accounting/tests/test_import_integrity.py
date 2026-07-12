# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import ast
import importlib
import unittest
from collections import defaultdict
from pathlib import Path

import erpnext_extensions.iran_accounting.core.rounding as core_rounding
from erpnext_extensions.iran_accounting.integration.bootstrap import apply
from erpnext_extensions.iran_accounting.worker.guard import CORE_REQUIRED, ensure_runtime_ready


class TestImportIntegrity(unittest.TestCase):
	def test_core_rounding_exports_required_symbols(self):
		for name in CORE_REQUIRED:
			self.assertTrue(hasattr(core_rounding, name), name)

	def test_ensure_runtime_ready_idempotent(self):
		ensure_runtime_ready()
		apply()
		for name in CORE_REQUIRED:
			self.assertTrue(hasattr(core_rounding, name), name)

	def test_no_import_cycle_monkey_patches_stock_reconciliation(self):
		base = Path(__file__).resolve().parents[1]
		mods = {
			"core.rounding": base / "core" / "rounding.py",
			"domain.qty_rate_amount": base / "domain" / "qty_rate_amount.py",
			"domain.stock_reconciliation": base / "domain" / "stock_reconciliation.py",
			"domain.stock_reconciliation_sync": base / "domain" / "stock_reconciliation_sync.py",
			"domain.stock_ledger": base / "domain" / "stock_ledger.py",
			"integration.monkey_patches": base / "integration" / "monkey_patches.py",
		}
		edges: dict[str, set[str]] = defaultdict(set)
		for mod, path in mods.items():
			tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
			for node in ast.walk(tree):
				if isinstance(node, ast.ImportFrom) and node.module:
					m = node.module
					if not m.startswith("erpnext_extensions.iran_accounting."):
						continue
					dep = m.replace("erpnext_extensions.iran_accounting.", "")
					dep_root = dep.split(".", 1)[0]
					for key in mods:
						if key.startswith(dep_root) or dep.startswith(key.replace(".", ".")):
							if key != mod and (dep in key or key.endswith(dep.split(".")[-1])):
								pass
					# normalize to first two segments
					parts = dep.split(".")
					label = ".".join(parts[:2]) if len(parts) > 1 else parts[0]
					if label in mods and label != mod:
						edges[mod].add(label)
					elif parts[0] in ("core", "domain", "integration", "worker"):
						short = f"{parts[0]}.{parts[1]}" if len(parts) > 1 else parts[0]
						if short in mods and short != mod:
							edges[mod].add(short)
		self.assertNotIn(
			"domain.stock_reconciliation",
			edges.get("integration.monkey_patches", set()),
		)
		self.assertIn("domain.stock_reconciliation_sync", edges.get("integration.monkey_patches", set()))

	def test_qty_rate_amount_imports_domain_currency(self):
		src = (Path(__file__).resolve().parents[1] / "domain" / "qty_rate_amount.py").read_text(
			encoding="utf-8"
		)
		self.assertIn("import erpnext_extensions.iran_accounting.domain.currency as rounding", src)
		importlib.import_module("erpnext_extensions.iran_accounting.domain.qty_rate_amount")
