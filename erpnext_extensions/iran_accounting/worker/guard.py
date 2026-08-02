# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import importlib
import sys

import erpnext_extensions.iran_accounting.core.rounding as core_rounding

CORE_REQUIRED = ("round_currency", "round_currency_amount", "round_row_amount", "round_rate")

DOMAIN_CURRENCY_REQUIRED = (
	"round_currency_amount",
	"round_row_amount",
	"round_monetary_rate",
	"round_irr_rate",
	"get_currency_precision",
	"amount_is_fractional",
	"rate_is_fractional",
)


def _ensure_module_attrs(module_name: str, required: tuple[str, ...]) -> None:
	mod = sys.modules.get(module_name)
	if mod is None:
		mod = importlib.import_module(module_name)
	missing = [name for name in required if not hasattr(mod, name)]
	if not missing:
		return
	mod = importlib.reload(mod)
	missing = [name for name in required if not hasattr(mod, name)]
	if missing:
		raise ImportError(f"{module_name} incomplete after reload; missing: {missing}")


def ensure_core_rounding() -> None:
	_ensure_module_attrs("erpnext_extensions.iran_accounting.core.rounding", CORE_REQUIRED)


def ensure_domain_currency() -> None:
	_ensure_module_attrs("erpnext_extensions.iran_accounting.domain.currency", DOMAIN_CURRENCY_REQUIRED)


def ensure_legacy_rounding_shim() -> None:
	legacy_required = DOMAIN_CURRENCY_REQUIRED + (
		"round_sle_monetary_fields",
		"round_gl_entry_amounts",
		"round_stock_entry_totals",
	)
	_ensure_module_attrs("erpnext_extensions.iran_accounting.rounding", legacy_required)


def ensure_runtime_ready() -> None:
	"""Call before submit/cancel hooks and background jobs (idempotent)."""
	ensure_core_rounding()
	ensure_domain_currency()
	ensure_legacy_rounding_shim()
	for name in CORE_REQUIRED:
		if not hasattr(core_rounding, name):
			raise ImportError(f"core.rounding missing {name}")
